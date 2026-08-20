"""``/nf-core security summary`` — summarise open GitHub security advisories.

Restricted to ``@core-team`` (checked by the router). Posts **publicly** in
the conversation where the command was run — a channel or DM — so the whole
team can see the result, not just the caller, mirroring
``commands/proposals/review.py``'s delivery pattern.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from slack_sdk.errors import SlackApiError

from nf_core_bot.checks.github import list_all_org_advisories
from nf_core_bot.security.advisories import format_advisories_summary

if TYPE_CHECKING:
    from slack_bolt.context.respond.async_respond import AsyncRespond as Respond
    from slack_sdk.web.async_client import AsyncWebClient

logger = logging.getLogger(__name__)

# Posting where the command was run can fail when the bot isn't a member there
# (a personal self-DM, a channel it hasn't joined) — fall back to a DM instead.
_DM_FALLBACK_ERRORS = frozenset({"channel_not_found", "not_in_channel", "is_archived"})


async def handle_security_summary(
    respond: Respond,
    client: AsyncWebClient,
    user_id: str,
    command: dict[str, str],
) -> None:
    """Fetch live advisory data from GitHub and post a public summary."""
    try:
        advisories = await list_all_org_advisories()
    except Exception:
        logger.exception("Failed to fetch org security advisories for /nf-core security summary")
        await respond(
            "Could not fetch security advisories from GitHub — check the bot's token/permissions.",
            response_type="ephemeral",
        )
        return

    text = format_advisories_summary(advisories)
    channel_id = command.get("channel_id", "")

    try:
        await client.chat_postMessage(channel=channel_id, text=text)
    except SlackApiError as e:
        if e.response.get("error") not in _DM_FALLBACK_ERRORS:
            raise
        try:
            dm = (await client.conversations_open(users=[user_id]))["channel"]["id"]
            await client.chat_postMessage(channel=dm, text=text)
            await respond(
                ":inbox_tray: Posted the summary to our DM — I couldn't post where you ran the command.",
                response_type="ephemeral",
            )
        except SlackApiError:
            logger.exception("Failed to deliver security summary for caller %s", user_id)
            await respond(
                "Sorry — I couldn't deliver the summary. Try running the command in a channel I'm a member of.",
                response_type="ephemeral",
            )
