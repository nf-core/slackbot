"""GitHub API checks — verify organisation membership, invite users.

Uses the ``GITHUB_TOKEN`` env var, which must have ``admin:org`` scope
for invitation/team-management operations.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx

from nf_core_bot import config

logger = logging.getLogger(__name__)


@dataclass
class GitHubResult:
    """Outcome of a GitHub API call."""

    ok: bool
    message: str


async def invite_to_org(username: str) -> GitHubResult:
    """Invite *username* to the nf-core GitHub organisation.

    ``PUT /orgs/{org}/memberships/{username}``

    This is idempotent — if the user is already a member the API returns 200.
    """
    org = config.GITHUB_ORG
    token = config.GITHUB_TOKEN
    url = f"https://api.github.com/orgs/{org}/memberships/{username}"

    async with httpx.AsyncClient() as http:
        resp = await http.put(
            url,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            json={"role": "member"},
        )

    if resp.status_code in (200, 201):
        state = resp.json().get("state", "unknown")
        return GitHubResult(ok=True, message=f"Org membership state: {state}")

    return GitHubResult(
        ok=False,
        message=f"Failed to invite `{username}` to org `{org}`: {resp.status_code} — {resp.text}",
    )


async def add_to_team(username: str, team_slug: str = "contributors") -> GitHubResult:
    """Add *username* to a team within the nf-core organisation.

    ``PUT /orgs/{org}/teams/{team_slug}/memberships/{username}``
    """
    org = config.GITHUB_ORG
    token = config.GITHUB_TOKEN
    url = f"https://api.github.com/orgs/{org}/teams/{team_slug}/memberships/{username}"

    async with httpx.AsyncClient() as http:
        resp = await http.put(
            url,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            json={"role": "member"},
        )

    if resp.status_code in (200, 201):
        state = resp.json().get("state", "unknown")
        return GitHubResult(ok=True, message=f"Team membership state: {state}")

    return GitHubResult(
        ok=False,
        message=f"Failed to add `{username}` to team `{team_slug}`: {resp.status_code} — {resp.text}",
    )
