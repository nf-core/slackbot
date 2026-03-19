"""Shared GitHub invitation flow — org invite + team add + greeting."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from nf_core_bot.checks.github import add_to_team, invite_to_org

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from slack_sdk.web.async_client import AsyncWebClient

logger = logging.getLogger(__name__)


async def _safe_reply(reply: Callable[[str], Awaitable[None]], text: str) -> bool:
    """Call *reply* and return ``True``.  If *reply* raises, log and return ``False``."""
    try:
        await reply(text)
        return True
    except Exception:
        logger.exception("Channel reply failed")
        return False


async def _dm_caller(client: AsyncWebClient, caller_user_id: str, text: str) -> None:
    """Send a DM to the person who triggered the command (best-effort)."""
    try:
        resp = await client.conversations_open(users=[caller_user_id])
        dm_channel = resp["channel"]["id"]
        await client.chat_postMessage(channel=dm_channel, text=text)
    except Exception:
        logger.exception("Failed to DM caller %s", caller_user_id)


async def _reply_or_dm(
    reply: Callable[[str], Awaitable[None]],
    client: AsyncWebClient,
    caller_user_id: str,
    text: str,
) -> None:
    """Try the channel *reply*; fall back to a DM if it fails."""
    if not await _safe_reply(reply, text):
        await _dm_caller(client, caller_user_id, text)


async def invite_and_greet(
    github_username: str,
    caller_user_id: str,
    reply: Callable[[str], Awaitable[None]],
    greeting_user_id: str | None = None,
    *,
    client: AsyncWebClient,
) -> bool:
    """Invite *github_username* to the nf-core org and contributors team.

    *reply* is called with message text for errors and the final greeting.
    If *reply* raises (e.g. ``channel_not_found``), the error is logged and
    the caller is notified via DM as a fallback.

    Returns ``True`` on success.
    """
    # ── 1. Org invite ────────────────────────────────────────────────
    try:
        org_result = await invite_to_org(github_username)
    except Exception:
        logger.exception("Network error inviting %s to org", github_username)
        msg = f"Failed to reach the GitHub API while inviting `{github_username}`. Please try again later."
        await _reply_or_dm(reply, client, caller_user_id, msg)
        return False

    if not org_result.ok:
        msg = f"Failed to invite `{github_username}` to the nf-core GitHub org:\n>{org_result.message}"
        await _reply_or_dm(reply, client, caller_user_id, msg)
        return False

    # ── 2. Team add ──────────────────────────────────────────────────
    try:
        team_result = await add_to_team(github_username)
    except Exception:
        logger.exception("Network error adding %s to team", github_username)
        msg = (
            f"Invited `{github_username}` to the org, but failed to reach the GitHub API "
            "when adding to the contributors team. Please try again later."
        )
        await _reply_or_dm(reply, client, caller_user_id, msg)
        return False

    if not team_result.ok:
        msg = (
            f"Invited `{github_username}` to the org, but failed to add to the "
            f"contributors team:\n>{team_result.message}"
        )
        await _reply_or_dm(reply, client, caller_user_id, msg)
        return False

    # ── 3. Success greeting ──────────────────────────────────────────
    greeting = f"Hi <@{greeting_user_id}>, " if greeting_user_id else f"Hi `{github_username}`, "
    msg = (
        f"{greeting}<@{caller_user_id}> has just added you to the nf-core GitHub organisation, "
        "welcome! :tada:\n\n"
        "You should have received an invite — you can either check your e-mail "
        "or click on this link to accept: https://github.com/orgs/nf-core/invitation"
    )
    await _safe_reply(reply, msg)

    # Always DM the caller as a failsafe confirmation
    dm_text = (
        f"Done! `{github_username}` has been invited to the nf-core GitHub org and added to the contributors team."
    )
    await _dm_caller(client, caller_user_id, dm_text)

    return True
