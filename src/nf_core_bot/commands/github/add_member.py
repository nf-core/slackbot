"""``/nf-core github add`` — invite a user to the nf-core GitHub org.

Usage (explicit Slack mention):
    ``/nf-core github add @slack-user``

Usage (explicit GitHub username):
    ``/nf-core github add octocat``

To invite the author of a specific message, use the "Add to GitHub org"
message shortcut (right-click a message → More actions) instead.
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

from nf_core_bot.checks.slack_profile import get_github_username, normalise_github_username
from nf_core_bot.commands.github.invite_flow import invite_and_greet
from nf_core_bot.permissions.checks import is_core_team

if TYPE_CHECKING:
    from slack_bolt.context.ack.async_ack import AsyncAck as Ack
    from slack_bolt.context.respond.async_respond import AsyncRespond as Respond
    from slack_sdk.web.async_client import AsyncWebClient

logger = logging.getLogger(__name__)

# Matches a Slack user mention like <@U01234ABC> or <@U01234ABC|username>
_SLACK_MENTION_RE = re.compile(r"^<@(U[A-Z0-9]+)(?:\|[^>]*)?>$")


async def handle_add_member(
    ack: Ack,
    respond: Respond,
    client: AsyncWebClient,
    user_id: str,
    command: dict[str, str],
    args: list[str],
) -> None:
    """Handle ``/nf-core github add [target]``."""
    await ack()

    # ── 1. Permission check ──────────────────────────────────────────
    if not await is_core_team(client, user_id):
        await respond(
            "Sorry, this command is restricted to `@core-team` members.",
            response_type="ephemeral",
        )
        return

    channel_id: str = command.get("channel_id", "")
    thread_ts: str = command.get("thread_ts", "")

    # ── 2. Determine target ──────────────────────────────────────────
    target_user_id: str | None = None  # Slack user ID, if known

    if args:
        # Explicit argument — could be a Slack mention or a GitHub username
        target = args[0]
        mention_match = _SLACK_MENTION_RE.match(target)

        if mention_match:
            # It's a Slack @-mention — resolve GitHub username from profile
            target_user_id = mention_match.group(1)
            github_username = await get_github_username(client, target_user_id)
            if github_username is None:
                await _warn_missing_github(client, channel_id, thread_ts, target_user_id, respond)
                return
        else:
            # Treat it as a plain GitHub username — validate first
            github_username = normalise_github_username(target)
            if github_username is None:
                await respond(
                    f"That doesn't look like a valid GitHub username: `{target}`\n"
                    "GitHub usernames are 1-39 characters, alphanumeric and hyphens only.",
                    response_type="ephemeral",
                )
                return
    else:
        # No argument provided
        await respond(
            "Usage: `/nf-core github add [@user | github-username]`\n\n"
            "You can also right-click a message and use *More actions → Add to GitHub org* "
            "to invite the message author.",
            response_type="ephemeral",
        )
        return

    # ── 3. Invite to org + add to contributors team ──────────────────

    await respond(f"Looking up `{github_username}` on GitHub…", response_type="ephemeral")

    async def _reply(text: str) -> None:
        await _thread_reply(client, channel_id, thread_ts, text)

    await invite_and_greet(github_username, user_id, _reply, greeting_user_id=target_user_id, client=client)


# ── Helpers ──────────────────────────────────────────────────────────


async def _warn_missing_github(
    client: AsyncWebClient,
    channel_id: str,
    thread_ts: str,
    target_user_id: str,
    respond: Respond | None = None,
) -> None:
    """Post a visible thread reply telling the user to add their GitHub username.

    Falls back to an ephemeral *respond()* if the channel reply fails.
    """
    text = (
        f"<@{target_user_id}> — please add your GitHub username to your Slack profile!\n"
        "Go to your profile → *Edit profile* → fill in the *GitHub* field.\n"
        "<https://slack.com/help/articles/204092246-Edit-your-profile|How to edit your Slack profile>\n\n"
        "Once done, a core-team member can re-run: "
        "`/nf-core github add <github-username>`"
    )
    try:
        await _thread_reply(client, channel_id, thread_ts, text)
    except Exception:
        logger.exception("Channel reply failed in _warn_missing_github")
        if respond:
            await respond(text, response_type="ephemeral")


async def _thread_reply(
    client: AsyncWebClient,
    channel_id: str,
    thread_ts: str,
    text: str,
) -> None:
    """Post a visible reply — in a thread if *thread_ts* is set, otherwise to the channel."""
    kwargs: dict[str, str] = {"channel": channel_id, "text": text}
    if thread_ts:
        kwargs["thread_ts"] = thread_ts
    await client.chat_postMessage(**kwargs)  # type: ignore[arg-type]
