"""``/nf-core-bot github add-member`` — invite a user to the nf-core GitHub org.

Usage (in a thread, no argument):
    Resolves the thread-starter's GitHub username from their Slack profile.

Usage (explicit Slack mention):
    ``/nf-core-bot github add-member @slack-user``

Usage (explicit GitHub username):
    ``/nf-core-bot github add-member octocat``
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Any

from nf_core_bot.checks.github import add_to_team, invite_to_org
from nf_core_bot.checks.slack_profile import get_github_username
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
    """Handle ``/nf-core-bot github add-member [target]``."""
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
    if args:
        # Explicit argument — could be a Slack mention or a GitHub username
        target = args[0]
        mention_match = _SLACK_MENTION_RE.match(target)

        if mention_match:
            # It's a Slack @-mention — resolve GitHub username from profile
            target_user_id = mention_match.group(1)
            github_username = await get_github_username(client, target_user_id)
            if github_username is None:
                await _warn_missing_github(client, channel_id, thread_ts, target_user_id)
                return
        else:
            # Treat it as a plain GitHub username
            github_username = target
    else:
        # No argument — must be in a thread; resolve from thread starter
        if not thread_ts:
            await respond(
                "Usage: `/nf-core-bot github add-member [@user | github-username]`\n"
                "Or use this command in a thread (without arguments) to invite the thread starter.",
                response_type="ephemeral",
            )
            return

        target_user_id = await _get_thread_starter(client, channel_id, thread_ts)
        if target_user_id is None:
            await _thread_reply(
                client,
                channel_id,
                thread_ts,
                "Could not determine the thread starter. Please specify a user explicitly: "
                "`/nf-core-bot github add-member @user`",
            )
            return

        github_username = await get_github_username(client, target_user_id)
        if github_username is None:
            await _warn_missing_github(client, channel_id, thread_ts, target_user_id)
            return

    # ── 3. Invite to org + add to contributors team ──────────────────

    org_result = await invite_to_org(github_username)
    if not org_result.ok:
        await _thread_reply(
            client,
            channel_id,
            thread_ts,
            f"Failed to invite `{github_username}` to the nf-core GitHub org:\n>{org_result.message}",
        )
        return

    team_result = await add_to_team(github_username)
    if not team_result.ok:
        msg = (
            f"Invited `{github_username}` to the org, but failed to add to the "
            f"contributors team:\n>{team_result.message}"
        )
        await _thread_reply(client, channel_id, thread_ts, msg)
        return

    await _thread_reply(
        client,
        channel_id,
        thread_ts,
        f"Invited `{github_username}` to the nf-core GitHub org and added to the *contributors* team.",
    )


# ── Helpers ──────────────────────────────────────────────────────────


async def _get_thread_starter(
    client: AsyncWebClient,
    channel_id: str,
    thread_ts: str,
) -> str | None:
    """Return the user ID of the thread's parent message author."""
    try:
        resp = await client.conversations_history(
            channel=channel_id,
            latest=thread_ts,
            inclusive=True,
            limit=1,
        )
        messages: list[dict[str, Any]] = resp.get("messages", [])
        if messages:
            user: str | None = messages[0].get("user")
            return user
    except Exception:
        logger.exception("Failed to read thread parent in channel=%s ts=%s", channel_id, thread_ts)
    return None


async def _warn_missing_github(
    client: AsyncWebClient,
    channel_id: str,
    thread_ts: str,
    target_user_id: str,
) -> None:
    """Post a visible thread reply telling the user to add their GitHub username."""
    text = (
        f"<@{target_user_id}> — please add your GitHub username to your Slack profile!\n"
        "Go to your profile → *Edit profile* → fill in the *GitHub* field.\n"
        "<https://slack.com/help/articles/204092246-Edit-your-profile|How to edit your Slack profile>\n\n"
        "Once done, a core-team member can re-run: "
        "`/nf-core-bot github add-member <github-username>`"
    )
    await _thread_reply(client, channel_id, thread_ts, text)


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
