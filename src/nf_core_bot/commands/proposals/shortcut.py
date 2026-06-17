"""Message shortcut — "Review pipeline proposal".

Right-click a message (e.g. the auto-announcement in #new-pipelines) → More
actions → "Review pipeline proposal". Unlike slash commands, shortcuts carry the
message + thread context, so the review is posted as a threaded reply under that
message, tagging @core-team.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from nf_core_bot.permissions.checks import is_core_team_or_maintainers
from nf_core_bot.proposals import spawn
from nf_core_bot.proposals.parsing import extract_proposal_number, message_searchable_text
from nf_core_bot.proposals.review import build_review_message
from nf_core_bot.proposals.slack_utils import core_team_mention, post_review

if TYPE_CHECKING:
    from slack_bolt.context.ack.async_ack import AsyncAck as Ack
    from slack_sdk.web.async_client import AsyncWebClient

logger = logging.getLogger(__name__)


async def handle_review_proposal_shortcut(
    ack: Ack,
    shortcut: dict,  # type: ignore[type-arg]
    client: AsyncWebClient,
) -> None:
    """Handle the 'Review pipeline proposal' message shortcut."""
    await ack()

    caller_id: str = shortcut["user"]["id"]
    channel_id: str = shortcut["channel"]["id"]
    message: dict = shortcut.get("message", {})  # type: ignore[type-arg]
    message_ts: str = message.get("ts", shortcut.get("message_ts", ""))
    thread_ts: str = message.get("thread_ts", message_ts)

    if not await is_core_team_or_maintainers(client, caller_id):
        await client.chat_postEphemeral(
            channel=channel_id,
            user=caller_id,
            text="Sorry, proposal reviews are restricted to `@core-team` and `@maintainers-team`.",
        )
        return

    number = extract_proposal_number(message_searchable_text(message))
    if number is None:
        await client.chat_postEphemeral(
            channel=channel_id,
            user=caller_id,
            text="Couldn't find an `nf-core/proposals` link in this message. Use `/nf-core proposals review <N>`.",
        )
        return

    await client.chat_postEphemeral(
        channel=channel_id,
        user=caller_id,
        text=f":hourglass_flowing_sand: Reviewing proposal #{number}… I'll post it in this thread shortly.",
    )
    spawn(_run_and_post(client, number, channel_id, thread_ts))


async def _run_and_post(client: AsyncWebClient, number: int, channel_id: str, thread_ts: str) -> None:
    mention = await core_team_mention(client)
    issue, blocks, fallback = await build_review_message(number, core_team_mention=mention)
    if issue is None or blocks is None:
        await client.chat_postMessage(
            channel=channel_id,
            thread_ts=thread_ts,
            text=f"Couldn't fetch proposal #{number} from `nf-core/proposals`.",
        )
        return
    await post_review(client, channel_id, blocks, fallback or "", thread_ts=thread_ts)
