"""Auto-trigger: review a proposal when its GitHub→Slack post lands in #new-pipelines."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from nf_core_bot import config
from nf_core_bot.checks.github import NEW_PIPELINE_LABEL, get_issue_with_comments
from nf_core_bot.db.proposals import claim_review, mark_reviewed, release_claim
from nf_core_bot.proposals.parsing import extract_proposal_number, message_searchable_text
from nf_core_bot.proposals.review import generate_review_body, render_blocks
from nf_core_bot.proposals.slack_utils import (
    core_team_mention,
    make_progress_reporter,
    post_review,
    resolve_channel_id,
)

if TYPE_CHECKING:
    from slack_sdk.web.async_client import AsyncWebClient

logger = logging.getLogger(__name__)

# Subtypes we act on: a brand-new message (None) or a bot/integration post.
_ACTIONABLE_SUBTYPES = frozenset({None, "bot_message"})

# Cached bot identity (to skip our own posts and avoid loops). Resolved once;
# the flag stops a failed auth_test being retried on every message.
_self_ids: dict[str, str] = {}
_self_ids_resolved = False


def _enabled() -> bool:
    return (config.PROPOSALS_REVIEW_ENABLED or "true").strip().lower() not in ("0", "false", "no", "off")


def _is_top_level(event: dict[str, Any]) -> bool:
    """True unless the event is a reply in a thread (our own review is threaded)."""
    thread_ts = event.get("thread_ts")
    return not thread_ts or thread_ts == event.get("ts")


def should_consider(event: dict[str, Any]) -> bool:
    """Cheap, synchronous gate: is this message even worth a background task?

    Rejects the overwhelming majority of channel chatter (wrong subtype, thread
    replies, no proposal link) before any task is spawned or API call is made.
    """
    return (
        _enabled()
        and event.get("subtype") in _ACTIONABLE_SUBTYPES
        and _is_top_level(event)
        and extract_proposal_number(message_searchable_text(event)) is not None
    )


async def _own_message(client: AsyncWebClient, event: dict[str, Any]) -> bool:
    """True if *event* was posted by this bot (prevents self-triggering loops)."""
    global _self_ids_resolved  # noqa: PLW0603
    if not _self_ids_resolved:
        _self_ids_resolved = True
        try:
            auth = await client.auth_test()
            _self_ids["user_id"] = auth.get("user_id", "")
            _self_ids["bot_id"] = auth.get("bot_id", "")
        except Exception:
            logger.exception("auth_test failed while resolving bot identity")
    # Only match on IDs we actually resolved — otherwise a None == None compare
    # would flag every (botless) human message as our own.
    uid, bid = _self_ids.get("user_id"), _self_ids.get("bot_id")
    return bool(uid and event.get("user") == uid) or bool(bid and event.get("bot_id") == bid)


async def handle_proposal_message(event: dict[str, Any], client: AsyncWebClient) -> None:
    """Inspect a channel message and, if it announces a new proposal, review it.

    Checks are ordered cheapest-first: synchronous `event`-only filters and the
    proposal-number parse run before any Slack/GitHub call, so a non-proposal
    message never triggers channel-list pagination or `auth_test`.
    """
    # Cheap synchronous filters first (also enforced by should_consider()).
    if not _enabled() or event.get("subtype") not in _ACTIONABLE_SUBTYPES or not _is_top_level(event):
        return

    number = extract_proposal_number(message_searchable_text(event))
    if number is None:
        return

    channel = event.get("channel", "")
    target = await resolve_channel_id(client, config.PROPOSALS_CHANNEL or "new-pipelines")
    if not target or channel != target:
        return

    if await _own_message(client, event):
        return

    # Claim the review atomically so duplicate events don't double-review.
    if not await claim_review(number):
        logger.info("Proposal #%d already claimed/reviewed — skipping", number)
        return

    ts = event.get("ts")
    try:
        issue = await get_issue_with_comments(number)
        if issue is None or NEW_PIPELINE_LABEL not in issue.labels:
            # Not a (fetchable) new-pipeline proposal — release so a later,
            # correctly-labelled trigger can still run.
            await release_claim(number)
            return
        mention = await core_team_mention(client)
        # Live status in-thread while the (minutes-long) review runs; removed once
        # the real review posts so the thread isn't cluttered.
        status = await client.chat_postMessage(
            channel=channel, thread_ts=ts, text=f":mag: Reviewing proposal #{number}… (this can take a minute)"
        )
        status_ts = status.get("ts")

        async def _update_status(text: str) -> None:
            if status_ts:
                await client.chat_update(channel=channel, ts=status_ts, text=text)

        reporter = make_progress_reporter(_update_status, max_posts=8)
        body = await generate_review_body(issue, on_progress=reporter)
        blocks, fallback = render_blocks(issue, body, mention)
        await post_review(client, channel, blocks, fallback, thread_ts=ts)
        if status_ts:
            try:
                await client.chat_delete(channel=channel, ts=status_ts)
            except Exception:
                logger.warning("Could not delete proposal-review status message", exc_info=True)
        await mark_reviewed(number, thread_ts=ts, channel=channel)
        logger.info("Posted automated review for proposal #%d", number)
    except Exception:
        logger.exception("Automated proposal review failed for #%d", number)
        await release_claim(number)
