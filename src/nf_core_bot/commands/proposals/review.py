"""`/nf-core proposals review <N> [preview]` — manual proposal review.

The review is posted **in the conversation where the command was invoked** (a
channel or DM), never cross-posted to the #new-pipelines thread. Running it in a
DM is a private test; the ``preview`` keyword keeps the result private by sending
it to the caller's DM with the bot.

Delivery uses ``chat.postMessage``, not the slash response URL: Block Kit
``markdown`` blocks (the ones that render nested bullets) post reliably through
``chat.postMessage`` but are silently dropped over the response URL. If the bot
can't post where the command was run (e.g. a personal self-DM it isn't a member
of), it falls back to DMing the caller. The response URL is used only for the
lightweight text ack and progress updates, which it handles fine.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from slack_sdk.errors import SlackApiError

from nf_core_bot.proposals import spawn
from nf_core_bot.proposals.review import build_review_message
from nf_core_bot.proposals.slack_utils import make_progress_reporter

if TYPE_CHECKING:
    from slack_bolt.context.respond.async_respond import AsyncRespond as Respond
    from slack_sdk.web.async_client import AsyncWebClient

logger = logging.getLogger(__name__)

_USAGE = "Usage: `/nf-core proposals review <issue-number> [preview]`"

# Posting where the command was run can fail when the bot isn't a member there
# (a personal self-DM, a channel it hasn't joined) — fall back to a DM instead.
_DM_FALLBACK_ERRORS = frozenset({"channel_not_found", "not_in_channel", "is_archived"})


def _parse_args(rest: list[str]) -> tuple[int | None, bool]:
    """Return ``(issue_number, preview)`` from the command tokens."""
    preview = any(tok.lower() == "preview" for tok in rest)
    for tok in rest:
        candidate = tok.lstrip("#")
        if candidate.isdigit():
            return int(candidate), preview
    return None, preview


async def handle_proposals_review(
    respond: Respond,
    client: AsyncWebClient,
    user_id: str,
    command: dict[str, str],
    rest: list[str],
) -> None:
    """Kick off a manual review (already acked + permission-checked by the router)."""
    number, preview = _parse_args(rest)
    if number is None:
        await respond(_USAGE, response_type="ephemeral")
        return

    await respond(
        f":hourglass_flowing_sand: Reviewing proposal #{number}… I'll post the result here shortly.",
        response_type="ephemeral",
    )
    spawn(_run_and_post(respond, client, command.get("channel_id", ""), user_id, number, preview=preview))


async def _run_and_post(
    respond: Respond,
    client: AsyncWebClient,
    channel_id: str,
    user_id: str,
    number: int,
    *,
    preview: bool,
) -> None:
    # Slash reviews never ping @core-team (mention left empty). Phase updates edit
    # the ephemeral ack in place via the response URL (text only — reliable); capped
    # to stay within the response URL's ~5-message budget.
    async def post_status(text: str) -> None:
        await respond(text=text, response_type="ephemeral", replace_original=True)

    reporter = make_progress_reporter(post_status, max_posts=2)
    issue, blocks, fallback = await build_review_message(number, core_team_mention="", on_progress=reporter)
    if issue is None or blocks is None:
        await respond(
            f"Couldn't fetch proposal #{number} from `nf-core/proposals` — is the issue number correct?",
            response_type="ephemeral",
            replace_original=True,
        )
        return

    await _deliver(client, respond, channel_id, user_id, blocks, fallback or "", preview=preview)


async def _deliver(
    client: AsyncWebClient,
    respond: Respond,
    channel_id: str,
    user_id: str,
    blocks: list[dict[str, Any]],
    text: str,
    *,
    preview: bool,
) -> None:
    """Post the review where the command was run; fall back to the caller's DM."""
    if not preview:
        try:
            await client.chat_postMessage(channel=channel_id, blocks=blocks, text=text)
            return
        except SlackApiError as e:
            if e.response.get("error") not in _DM_FALLBACK_ERRORS:
                raise

    # Preview, or we couldn't post where the command was run: deliver privately to
    # the caller's DM with the bot.
    try:
        dm = (await client.conversations_open(users=[user_id]))["channel"]["id"]
        await client.chat_postMessage(channel=dm, blocks=blocks, text=text)
        note = (
            ":inbox_tray: Posted a private preview to our DM. :point_up:"
            if preview
            else ":inbox_tray: Posted the review to our DM — I couldn't post where you ran the command. :point_up:"
        )
        await respond(text=note, response_type="ephemeral", replace_original=True)
    except SlackApiError:
        logger.exception("Failed to deliver slash review for caller %s", user_id)
        await respond(
            text="Sorry — I couldn't deliver the review. Try running the command in a channel I'm a member of.",
            response_type="ephemeral",
            replace_original=True,
        )
