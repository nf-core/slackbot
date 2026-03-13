"""``/nf-core-bot github add-member`` — invite a user to the nf-core GitHub org.

Usage (explicit Slack mention):
    ``/nf-core-bot github add-member @slack-user``

Usage (explicit GitHub username):
    ``/nf-core-bot github add-member octocat``

To invite the author of a specific message, use the "Add to GitHub org"
message shortcut (right-click a message → More actions) instead.
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
            "Usage: `/nf-core-bot github add-member [@user | github-username]`\n\n"
            "You can also right-click a message and use *More actions → Add to GitHub org* "
            "to invite the message author.",
            response_type="ephemeral",
        )
        return

    # ── 3. Invite to org + add to contributors team ──────────────────

    await respond(f"Looking up `{github_username}` on GitHub…", response_type="ephemeral")

    try:
        org_result = await invite_to_org(github_username)
    except Exception:
        logger.exception("Network error inviting %s to org", github_username)
        await _thread_reply(
            client,
            channel_id,
            thread_ts,
            f"Failed to reach the GitHub API while inviting `{github_username}`. Please try again later.",
        )
        return

    if not org_result.ok:
        await _thread_reply(
            client,
            channel_id,
            thread_ts,
            f"Failed to invite `{github_username}` to the nf-core GitHub org:\n>{org_result.message}",
        )
        return

    try:
        team_result = await add_to_team(github_username)
    except Exception:
        logger.exception("Network error adding %s to team", github_username)
        await _thread_reply(
            client,
            channel_id,
            thread_ts,
            f"Invited `{github_username}` to the org, but failed to reach the GitHub API "
            "when adding to the contributors team. Please try again later.",
        )
        return

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
        f"Sent `{github_username}` an invite to the nf-core GitHub organisation and *contributors* team.\n"
        "They can accept at: https://github.com/orgs/nf-core/invitation",
    )


# ── Helpers ──────────────────────────────────────────────────────────


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
