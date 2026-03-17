"""Shared GitHub invitation flow — org invite + team add + greeting."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from nf_core_bot.checks.github import add_to_team, invite_to_org

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

logger = logging.getLogger(__name__)


async def invite_and_greet(
    github_username: str,
    caller_user_id: str,
    reply: Callable[[str], Awaitable[None]],
    greeting_user_id: str | None = None,
) -> bool:
    """Invite *github_username* to the nf-core org and contributors team.

    *reply* is called with message text for errors and the final greeting.
    Returns ``True`` on success.
    """
    try:
        org_result = await invite_to_org(github_username)
    except Exception:
        logger.exception("Network error inviting %s to org", github_username)
        await reply(f"Failed to reach the GitHub API while inviting `{github_username}`. Please try again later.")
        return False

    if not org_result.ok:
        await reply(f"Failed to invite `{github_username}` to the nf-core GitHub org:\n>{org_result.message}")
        return False

    try:
        team_result = await add_to_team(github_username)
    except Exception:
        logger.exception("Network error adding %s to team", github_username)
        await reply(
            f"Invited `{github_username}` to the org, but failed to reach the GitHub API "
            "when adding to the contributors team. Please try again later."
        )
        return False

    if not team_result.ok:
        await reply(
            f"Invited `{github_username}` to the org, but failed to add to the "
            f"contributors team:\n>{team_result.message}"
        )
        return False

    greeting = f"Hi <@{greeting_user_id}>, " if greeting_user_id else f"Hi `{github_username}`, "
    await reply(
        f"{greeting}<@{caller_user_id}> has just added you to the nf-core GitHub organisation, "
        "welcome! :tada:\n\n"
        "You should have received an invite — you can either check your e-mail "
        "or click on this link to accept: https://github.com/orgs/nf-core/invitation"
    )
    return True
