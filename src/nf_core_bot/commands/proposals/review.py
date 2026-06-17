"""`/nf-core proposals review <N> [preview]` — manual proposal review.

The review is posted **in the conversation where the command was invoked** (a
channel or DM), never cross-posted to the #new-pipelines thread. Running it in a
DM is a private test; the ``preview`` keyword forces an ephemeral reply.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from nf_core_bot.proposals import spawn
from nf_core_bot.proposals.review import build_review_message
from nf_core_bot.proposals.slack_utils import post_review

if TYPE_CHECKING:
    from slack_bolt.context.respond.async_respond import AsyncRespond as Respond
    from slack_sdk.web.async_client import AsyncWebClient

logger = logging.getLogger(__name__)

_USAGE = "Usage: `/nf-core proposals review <issue-number> [preview]`"


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

    channel_id = command.get("channel_id", "")
    await respond(
        f":hourglass_flowing_sand: Reviewing proposal #{number}… I'll post the result here shortly.",
        response_type="ephemeral",
    )
    spawn(_run_and_post(client, number, channel_id, user_id, preview=preview))


async def _run_and_post(
    client: AsyncWebClient,
    number: int,
    channel_id: str,
    user_id: str,
    *,
    preview: bool,
) -> None:
    # Slash-command reviews never ping @core-team (mention left empty).
    issue, text = await build_review_message(number, core_team_mention="")
    if issue is None or text is None:
        await client.chat_postEphemeral(
            channel=channel_id,
            user=user_id,
            text=f"Couldn't fetch proposal #{number} from `nf-core/proposals` — is the issue number correct?",
        )
        return
    if preview:
        await post_review(client, channel_id, text, ephemeral_user=user_id)
    else:
        await post_review(client, channel_id, text)
