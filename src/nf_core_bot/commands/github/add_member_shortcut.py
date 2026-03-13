"""Message shortcut — "Add to GitHub org".

Triggered via right-click on a message > More actions > "Add to GitHub org".

For regular user messages, reads the author's GitHub username from their Slack
profile.  For workflow/bot messages (e.g. the "GitHub Invitation Request"
workflow), parses the message text to extract the GitHub handle.

This works in threads (unlike slash commands), making it the preferred way to
invite someone based on a message they posted.
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

from nf_core_bot.checks.github import add_to_team, invite_to_org
from nf_core_bot.checks.slack_profile import get_github_username, normalise_github_username
from nf_core_bot.permissions.checks import is_core_team

if TYPE_CHECKING:
    from slack_bolt.context.ack.async_ack import AsyncAck as Ack
    from slack_sdk.web.async_client import AsyncWebClient

logger = logging.getLogger(__name__)

# Pattern to extract the GitHub handle from workflow messages.
# Matches lines like:
#   *Which is your GitHub handle?*\nMuteebaAzhar
#   Which is your GitHub handle?\nMuteebaAzhar
_GITHUB_HANDLE_RE = re.compile(
    r"(?:\*)?(?:Which is your GitHub handle\??|GitHub handle\??)(?:\*)?[\n\r]+\s*(\S+)",
    re.IGNORECASE,
)

# Pattern to extract the Slack user mention from workflow messages.
# Matches "By <@U01234ABC>" in the "By @Name at ..." line.
_WORKFLOW_REQUESTER_RE = re.compile(r"By\s+<@(U[A-Z0-9]+)(?:\|[^>]*)?>", re.IGNORECASE)


def _extract_github_handle_from_text(text: str) -> str | None:
    """Try to extract and validate a GitHub handle from workflow message text."""
    match = _GITHUB_HANDLE_RE.search(text)
    if match:
        return normalise_github_username(match.group(1))
    return None


def _extract_requester_from_text(text: str) -> str | None:
    """Try to extract the Slack user ID of the person who submitted the workflow."""
    match = _WORKFLOW_REQUESTER_RE.search(text)
    if match:
        return match.group(1)
    return None


async def handle_add_member_shortcut(
    ack: Ack,
    shortcut: dict,  # type: ignore[type-arg]
    client: AsyncWebClient,
) -> None:
    """Handle the 'Add to GitHub org' message shortcut."""
    await ack()

    caller_id: str = shortcut["user"]["id"]
    channel_id: str = shortcut["channel"]["id"]
    message: dict = shortcut.get("message", {})  # type: ignore[type-arg]
    message_ts: str = message.get("ts", shortcut.get("message_ts", ""))
    message_text: str = message.get("text", "")

    # If the message is in a thread, reply in that thread; otherwise reply to the message itself
    thread_ts: str = message.get("thread_ts", message_ts)

    # ── 1. Permission check ──────────────────────────────────────────
    if not await is_core_team(client, caller_id):
        await client.chat_postEphemeral(
            channel=channel_id,
            user=caller_id,
            text="Sorry, this action is restricted to `@core-team` members.",
        )
        return

    # ── 2. Resolve GitHub username ───────────────────────────────────
    # Regular user message → look up their Slack profile
    # Workflow/bot message → parse the message text for a GitHub handle
    target_user_id: str | None = message.get("user")
    github_username: str | None = None

    # Who to address in the success message — the message author or the
    # workflow requester (the person who filled in the form).
    greeting_user_id: str | None = None

    if target_user_id is not None:
        # Regular user message — resolve from Slack profile
        greeting_user_id = target_user_id
        github_username = await get_github_username(client, target_user_id)
        if github_username is None:
            text = (
                f"<@{target_user_id}> — please add your GitHub username to your Slack profile!\n"
                "Go to your profile → *Edit profile* → fill in the *GitHub* field.\n"
                "<https://slack.com/help/articles/204092246-Edit-your-profile|How to edit your Slack profile>\n\n"
                "Once done, a core-team member can try this action again, or use: "
                "`/nf-core-bot github add-member <github-username>`"
            )
            await client.chat_postMessage(channel=channel_id, thread_ts=thread_ts, text=text)
            return
    else:
        # Workflow/bot message — try to extract GitHub handle from the text
        github_username = _extract_github_handle_from_text(message_text)
        greeting_user_id = _extract_requester_from_text(message_text)
        if github_username is None:
            await client.chat_postEphemeral(
                channel=channel_id,
                user=caller_id,
                text=(
                    "Couldn't find a GitHub username in this message.\n"
                    "Use `/nf-core-bot github add-member <github-username>` instead."
                ),
            )
            return

    # ── 3. Invite to org + add to contributors team ──────────────────
    await client.chat_postEphemeral(
        channel=channel_id,
        user=caller_id,
        text=f"Looking up `{github_username}` on GitHub…",
    )

    try:
        org_result = await invite_to_org(github_username)
    except Exception:
        logger.exception("Network error inviting %s to org", github_username)
        await client.chat_postMessage(
            channel=channel_id,
            thread_ts=thread_ts,
            text=f"Failed to reach the GitHub API while inviting `{github_username}`. Please try again later.",
        )
        return

    if not org_result.ok:
        await client.chat_postMessage(
            channel=channel_id,
            thread_ts=thread_ts,
            text=f"Failed to invite `{github_username}` to the nf-core GitHub org:\n>{org_result.message}",
        )
        return

    try:
        team_result = await add_to_team(github_username)
    except Exception:
        logger.exception("Network error adding %s to team", github_username)
        await client.chat_postMessage(
            channel=channel_id,
            thread_ts=thread_ts,
            text=(
                f"Invited `{github_username}` to the org, but failed to reach the GitHub API "
                "when adding to the contributors team. Please try again later."
            ),
        )
        return

    if not team_result.ok:
        await client.chat_postMessage(
            channel=channel_id,
            thread_ts=thread_ts,
            text=(
                f"Invited `{github_username}` to the org, but failed to add to the "
                f"contributors team:\n>{team_result.message}"
            ),
        )
        return

    # Build a friendly welcome message
    greeting = f"Hi <@{greeting_user_id}>, " if greeting_user_id else f"Hi `{github_username}`, "
    await client.chat_postMessage(
        channel=channel_id,
        thread_ts=thread_ts,
        text=(
            f"{greeting}<@{caller_id}> has just added you to the nf-core GitHub organisation, "
            "welcome! :tada:\n\n"
            "You should have received an invite — you can either check your e-mail "
            "or click on this link to accept: https://github.com/orgs/nf-core/invitation"
        ),
    )
