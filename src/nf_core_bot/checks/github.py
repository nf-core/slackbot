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

_GITHUB_HEADERS = {
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}

# ── Shared HTTP client ───────────────────────────────────────────────
# A module-level client is reused across requests to benefit from
# connection pooling and avoid repeated TCP/TLS handshakes.

_http_client: httpx.AsyncClient | None = None


def _get_client() -> httpx.AsyncClient:
    """Return a long-lived :class:`httpx.AsyncClient` for GitHub API calls.

    The client is created lazily on first use.  In production the Bolt
    process is long-running so the pooled connections are reused for the
    lifetime of the process.
    """
    global _http_client  # noqa: PLW0603
    if _http_client is None or _http_client.is_closed:
        token = config.GITHUB_TOKEN
        _http_client = httpx.AsyncClient(
            base_url="https://api.github.com",
            headers={"Authorization": f"Bearer {token}", **_GITHUB_HEADERS},
            timeout=httpx.Timeout(10.0, connect=5.0),
        )
    return _http_client


async def close_client() -> None:
    """Close the shared HTTP client (for graceful shutdown / tests)."""
    global _http_client  # noqa: PLW0603
    if _http_client is not None and not _http_client.is_closed:
        await _http_client.aclose()
    _http_client = None


# ── Low-level helpers ────────────────────────────────────────────────


async def _github_get(path: str) -> httpx.Response:
    """GET from the GitHub API using the shared client."""
    return await _get_client().get(path)


async def _github_put(path: str, *, json: dict[str, str]) -> httpx.Response:
    """PUT to the GitHub API using the shared client."""
    return await _get_client().put(path, json=json)


# ── Result type ──────────────────────────────────────────────────────


@dataclass
class GitHubResult:
    """Outcome of a GitHub API call."""

    ok: bool
    message: str


# ── Public API ───────────────────────────────────────────────────────


async def check_org_membership(username: str) -> GitHubResult:
    """Check whether *username* is a member of the nf-core organisation.

    ``GET /orgs/{org}/members/{username}``

    Returns 204 if the user is a member, 404 if not (or if the user does
    not exist).
    """
    org = config.GITHUB_ORG
    resp = await _github_get(f"/orgs/{org}/members/{username}")

    if resp.status_code == 204:
        return GitHubResult(ok=True, message=f"`{username}` is already a member of `{org}`.")

    if resp.status_code == 404:
        return GitHubResult(ok=False, message=f"`{username}` is not a member of `{org}`.")

    return GitHubResult(
        ok=False,
        message=f"Could not verify membership for `{username}`: {resp.status_code} — {resp.text}",
    )


async def check_user_exists(username: str) -> GitHubResult:
    """Verify that a GitHub user account exists.

    ``GET /users/{username}``
    """
    resp = await _github_get(f"/users/{username}")

    if resp.status_code == 200:
        return GitHubResult(ok=True, message=f"GitHub user `{username}` exists.")

    if resp.status_code == 404:
        return GitHubResult(ok=False, message=f"GitHub user `{username}` does not exist.")

    return GitHubResult(
        ok=False,
        message=f"Could not check user `{username}`: {resp.status_code} — {resp.text}",
    )


async def invite_to_org(username: str) -> GitHubResult:
    """Invite *username* to the nf-core GitHub organisation.

    ``PUT /orgs/{org}/memberships/{username}``

    This is idempotent — if the user is already a member the API returns 200.
    """
    org = config.GITHUB_ORG
    resp = await _github_put(f"/orgs/{org}/memberships/{username}", json={"role": "member"})

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
    resp = await _github_put(f"/orgs/{org}/teams/{team_slug}/memberships/{username}", json={"role": "member"})

    if resp.status_code in (200, 201):
        state = resp.json().get("state", "unknown")
        return GitHubResult(ok=True, message=f"Team membership state: {state}")

    return GitHubResult(
        ok=False,
        message=f"Failed to add `{username}` to team `{team_slug}`: {resp.status_code} — {resp.text}",
    )
