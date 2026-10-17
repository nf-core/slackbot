"""``/nf-core seqera add|remove|list`` — manage Seqera Platform access by group.

Usage::

    /nf-core seqera add @user <group> [--email foo@bar.com]
    /nf-core seqera remove @user <group>
    /nf-core seqera list [@user]

Groups are defined in code (``checks/seqera.py``). The router acks and checks
``@core-team`` membership before dispatching, so these handlers don't.
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

from nf_core_bot.checks.seqera import (
    SeqeraStatus,
    add_to_group,
    groups_for_user,
    remove_from_group,
    seqera_groups,
)
from nf_core_bot.checks.slack_profile import get_github_username
from nf_core_bot.db.seqera import list_members

if TYPE_CHECKING:
    from slack_bolt.context.respond.async_respond import AsyncRespond as Respond
    from slack_sdk.web.async_client import AsyncWebClient

logger = logging.getLogger(__name__)

# Matches a Slack user mention like <@U01234ABC> or <@U01234ABC|username>
_SLACK_MENTION_RE = re.compile(r"^<@(U[A-Z0-9]+)(?:\|[^>]*)?>$")

# Slack may send emails as "<mailto:me@x.org|me@x.org>"; this finds the address either way.
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")

ADD_USAGE = "Usage: `/nf-core seqera add @user <group> [--email foo@bar.com]`"
REMOVE_USAGE = "Usage: `/nf-core seqera remove @user <group>`"


def _mention(token: str) -> str | None:
    match = _SLACK_MENTION_RE.match(token)
    return match.group(1) if match else None


def _parse_email(args: list[str]) -> tuple[list[str], str | None, bool]:
    """Pull ``--email <addr>`` / ``--email=<addr>`` out of *args*.

    Returns ``(remaining args, email, ok)``; ``ok`` is ``False`` when
    ``--email`` was given without a valid address.
    """
    remaining: list[str] = []
    email: str | None = None
    i = 0
    while i < len(args):
        token = args[i]
        if token == "--email" or token.startswith("--email="):
            value = token.partition("=")[2]
            if not value and i + 1 < len(args):
                i += 1
                value = args[i]
            match = _EMAIL_RE.search(value)
            if match is None:
                return remaining, None, False
            email = match.group(0)
        else:
            remaining.append(token)
        i += 1
    return remaining, email, True


def _group_list() -> str:
    return ", ".join(f"`{name}`" for name in seqera_groups())


async def handle_seqera_add(respond: Respond, client: AsyncWebClient, user_id: str, args: list[str]) -> None:
    """Add a Slack user to a Seqera group."""
    args, email, ok = _parse_email(args)
    if not ok:
        await respond(f"`--email` needs a valid email address. {ADD_USAGE}", response_type="ephemeral")
        return
    target = _mention(args[0]) if len(args) == 2 else None
    if target is None:
        await respond(ADD_USAGE, response_type="ephemeral")
        return
    group_name = args[1].lower()
    if group_name not in seqera_groups():
        await respond(f"Unknown Seqera group `{group_name}`. Groups: {_group_list()}.", response_type="ephemeral")
        return

    # The removal job checks the GitHub username against the org, so it's required.
    github_username = await get_github_username(client, target)
    if github_username is None:
        await respond(
            f"<@{target}> has no GitHub username on their Slack profile. Add one first, so the weekly "
            "removal sync can check they're still in the nf-core GitHub org.",
            response_type="ephemeral",
        )
        return

    result = await add_to_group(client, target, github_username, group_name, email)
    logger.info("%s ran seqera add %s %s: %s", user_id, target, group_name, result.status.value)
    if result.status is SeqeraStatus.ADDED:
        text = f":white_check_mark: Added <@{target}> to `{group_name}` as `{result.email}`."
    elif result.status is SeqeraStatus.ALREADY_PARTICIPANT:
        text = f"<@{target}> is already in `{group_name}` (`{result.email}`) — nothing to do."
    else:
        text = f":x: Couldn't add <@{target}> to `{group_name}`: {result.message}."
        if result.status is SeqeraStatus.NO_ACCOUNT:
            text += " Use `--email` if their Seqera Platform email differs from their Slack email."
    await respond(text, response_type="ephemeral")


async def handle_seqera_remove(respond: Respond, client: AsyncWebClient, user_id: str, args: list[str]) -> None:
    """Remove a Slack user from a Seqera group the bot added them to."""
    target = _mention(args[0]) if len(args) == 2 else None
    if target is None:
        await respond(REMOVE_USAGE, response_type="ephemeral")
        return
    group_name = args[1].lower()

    result = await remove_from_group(target, group_name)
    logger.info("%s ran seqera remove %s %s: %s", user_id, target, group_name, result.status.value)
    if result.status is SeqeraStatus.REMOVED:
        text = f":white_check_mark: Removed <@{target}> from `{group_name}`."
    elif result.status is SeqeraStatus.UNKNOWN_GROUP:
        text = f"Unknown Seqera group `{group_name}`. Groups: {_group_list()}."
    else:
        text = f":x: Couldn't remove <@{target}> from `{group_name}`: {result.message}."
    await respond(text, response_type="ephemeral")


async def handle_seqera_list(respond: Respond, client: AsyncWebClient, user_id: str, args: list[str]) -> None:
    """List the groups, or the groups the bot added one user to."""
    if args:
        target = _mention(args[0]) if len(args) == 1 else None
        if target is None:
            await respond("Usage: `/nf-core seqera list [@user]`", response_type="ephemeral")
            return
        found = await groups_for_user(target)
        if not found:
            await respond(
                f"The bot hasn't added <@{target}> to any Seqera group. "
                "Access granted in Seqera Platform directly isn't tracked here.",
                response_type="ephemeral",
            )
            return
        lines = [f"*Seqera groups the bot added <@{target}> to*"]
        lines += [f"`{name}` — as `{member.email}`, added {member.added_at[:10]}" for name, member in found]
        await respond("\n".join(lines), response_type="ephemeral")
        return

    lines = ["*Seqera groups*"]
    for name, group in seqera_groups().items():
        if group.target_key is None:
            lines.append(f"`{name}` — {group.description} _(not configured)_")
            continue
        count = len(await list_members(group.target_key))
        lines.append(f"`{name}` — {group.description}: {count} member{'s' if count != 1 else ''} added by the bot")
    await respond("\n".join(lines), response_type="ephemeral")
