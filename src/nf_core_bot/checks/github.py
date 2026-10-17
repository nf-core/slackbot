"""GitHub API checks — verify organisation membership, invite users.

Uses the ``GITHUB_TOKEN`` env var, which must have ``admin:org`` scope
for invitation/team-management operations. Listing org-wide security
advisories (``list_all_org_advisories``) additionally requires the
account behind the token to be an org owner or security manager, plus
the ``repository_advisories:write`` scope (or, for a fine-grained PAT,
the "Repository security advisories" permission set to Write).
"""

from __future__ import annotations

import logging
import re
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


async def get_org_membership_state(username: str) -> str | None:
    """Return *username*'s org membership state: ``"active"``, ``"pending"`` or ``None``.

    ``GET /orgs/{org}/memberships/{username}``

    Unlike :func:`check_org_membership`, this sees pending invitations, so a
    freshly invited user who hasn't accepted yet isn't mistaken for a leaver.
    ``None`` means GitHub returned 404 (not a member and no pending invite).
    Raises ``RuntimeError`` on any other status so callers never treat an API
    failure as "not a member".
    """
    org = config.GITHUB_ORG
    resp = await _github_get(f"/orgs/{org}/memberships/{username}")

    if resp.status_code == 200:
        state: str = resp.json().get("state", "unknown")
        return state

    if resp.status_code == 404:
        return None

    raise RuntimeError(f"Could not check membership for `{username}`: {resp.status_code} — {resp.text}")


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


# ── Proposals digest ─────────────────────────────────────────────────
# Powers the weekly on-call announcement thread (see scheduler.oncall_jobs).

PROPOSALS_REPO = "proposals"

_PIPELINE_LABEL = "new-pipeline"
_RFC_LABEL = "new-rfc"
_ACCEPTED_LABEL = "accepted"
# Decision labels that mean a proposal is closed-out and the open issue
# should be tidied away by the on-call person.
_REJECTED_LABELS = {"withdrawn", "turned-down", "timed-out", "merge-with-existing"}

# Proposal sections, ordered for display. Accepted/rejected pipelines need
# direct action (set up / close), so they sit above the under-discussion lists.
PROPOSAL_SECTIONS = ("accepted", "rejected", "pipeline", "rfc")


@dataclass
class Proposal:
    """A single open proposal issue, categorised for the on-call digest."""

    title: str  # human-friendly, prefixes/backticks stripped
    url: str
    section: str  # one of PROPOSAL_SECTIONS


def _clean_proposal_title(title: str, kind: str) -> str:
    """Strip the standard ``New pipeline:``/``New RFC:`` prefixes and noise.

    *kind* is ``"pipeline"`` or ``"rfc"`` and selects which prefix to strip.
    Also drops a leading ``nf-core/`` org prefix and any backticks so the
    text reads cleanly inside a Slack link.
    """
    title = title.strip()
    if kind == "pipeline":
        title = re.sub(r"^new pipeline:\s*", "", title, flags=re.IGNORECASE)
        title = re.sub(r"^nf-core/", "", title, flags=re.IGNORECASE)
    else:
        title = re.sub(r"^new rfc:\s*", "", title, flags=re.IGNORECASE)
    return title.replace("`", "").strip()


async def list_open_proposals() -> list[Proposal]:
    """Return open proposals from ``{org}/proposals``, categorised for on-call.

    ``GET /repos/{org}/proposals/issues?state=open&sort=updated``

    Pull requests and issues without a relevant label are skipped. Results
    keep GitHub's most-recently-updated-first ordering. Categorisation is
    purely by label:

    * ``new-pipeline`` + ``accepted`` → ``accepted`` (needs set up)
    * ``new-pipeline`` + a rejection label → ``rejected`` (needs closing)
    * ``new-pipeline`` (otherwise) → ``pipeline``
    * ``new-rfc`` (not accepted/rejected) → ``rfc``

    Accepted/rejected RFCs and label-less issues carry no on-call action and
    are dropped. Returns an empty list on any API error (best-effort).
    """
    org = config.GITHUB_ORG
    resp = await _github_get(
        f"/repos/{org}/{PROPOSALS_REPO}/issues?state=open&sort=updated&direction=desc&per_page=100"
    )
    if resp.status_code != 200:
        logger.error("Failed to list proposals: %s — %s", resp.status_code, resp.text)
        return []

    proposals: list[Proposal] = []
    for issue in resp.json():
        if "pull_request" in issue:  # the issues endpoint also returns PRs
            continue
        labels = {lbl.get("name", "") for lbl in issue.get("labels", [])}
        is_accepted = _ACCEPTED_LABEL in labels
        is_rejected = bool(labels & _REJECTED_LABELS)

        if _PIPELINE_LABEL in labels:
            kind = "pipeline"
            if is_accepted:
                section = "accepted"
            elif is_rejected:
                section = "rejected"
            else:
                section = "pipeline"
        elif _RFC_LABEL in labels and not is_accepted and not is_rejected:
            kind = "rfc"
            section = "rfc"
        else:
            continue

        proposals.append(
            Proposal(
                title=_clean_proposal_title(issue.get("title", ""), kind),
                url=issue.get("html_url", ""),
                section=section,
            )
        )
    return proposals


# ── Full issue + comments (for automated review) ─────────────────────

NEW_PIPELINE_LABEL = _PIPELINE_LABEL  # "new-pipeline"


@dataclass
class IssueComment:
    """A single comment on a proposal issue."""

    author: str
    created_at: str
    body: str


@dataclass
class IssueWithComments:
    """A proposal issue plus all of its comments, for review."""

    number: int
    title: str
    url: str
    author: str
    state: str
    labels: list[str]
    body: str
    comments: list[IssueComment]


async def get_issue_with_comments(number: int, repo: str = PROPOSALS_REPO) -> IssueWithComments | None:
    """Fetch a single issue and all its comments from ``{org}/{repo}``.

    Returns ``None`` if the issue cannot be fetched (or is a pull request).
    Comments are paginated through in full.
    """
    org = config.GITHUB_ORG
    resp = await _github_get(f"/repos/{org}/{repo}/issues/{number}")
    if resp.status_code != 200:
        logger.error("Failed to fetch issue %s/%s#%d: %s", org, repo, number, resp.status_code)
        return None
    issue = resp.json()
    if "pull_request" in issue:
        return None

    comments: list[IssueComment] = []
    page = 1
    while True:
        c_resp = await _github_get(f"/repos/{org}/{repo}/issues/{number}/comments?per_page=100&page={page}")
        if c_resp.status_code != 200:
            logger.warning("Failed to fetch comments for %s#%d (page %d): %s", repo, number, page, c_resp.status_code)
            break
        batch = c_resp.json()
        if not batch:
            break
        for c in batch:
            comments.append(
                IssueComment(
                    author=(c.get("user") or {}).get("login", ""),
                    created_at=c.get("created_at", ""),
                    body=c.get("body", "") or "",
                )
            )
        if len(batch) < 100:
            break
        page += 1

    return IssueWithComments(
        number=number,
        title=issue.get("title", ""),
        url=issue.get("html_url", ""),
        author=(issue.get("user") or {}).get("login", ""),
        state=issue.get("state", ""),
        labels=[lbl.get("name", "") for lbl in issue.get("labels", [])],
        body=issue.get("body", "") or "",
        comments=comments,
    )


# ── Security advisories (for security.advisories) ─────────────────────


@dataclass
class SecurityAdvisory:
    """A single repository security advisory, including Triage/draft state."""

    repo: str
    ghsa_id: str
    summary: str
    state: str  # triage, draft, published, closed
    severity: str | None
    updated_at: str
    url: str


# The org-wide advisories endpoint doesn't include a dedicated repository
# field, but each advisory's API `url` is `.../repos/{org}/{repo}/security-advisories/{id}`.
_ADVISORY_URL_REPO_RE = re.compile(r"/repos/[^/]+/([^/]+)/security-advisories/")


def _repo_from_advisory_url(api_url: str) -> str:
    match = _ADVISORY_URL_REPO_RE.search(api_url)
    return match.group(1) if match else "unknown"


async def list_all_org_advisories() -> list[SecurityAdvisory]:
    """Return every security advisory across every repo in the org, including Triage/draft.

    ``GET /orgs/{org}/security-advisories`` — a single org-wide call instead of
    iterating every repo. Requires the account behind ``GITHUB_TOKEN`` to be an
    org owner or security manager, plus either the ``repository_advisories:write``
    scope (classic PAT) or the "Repository security advisories" permission set to
    Write (fine-grained PAT).

    Raises ``RuntimeError`` on a non-200 response so callers can distinguish "no
    advisories" from "couldn't check" (e.g. missing security-manager role).
    """
    org = config.GITHUB_ORG
    advisories: list[SecurityAdvisory] = []
    path: str | None = f"/orgs/{org}/security-advisories?per_page=100"
    while path:
        resp = await _github_get(path)
        if resp.status_code != 200:
            raise RuntimeError(f"Failed to list security advisories for org {org}: {resp.status_code} — {resp.text}")
        for adv in resp.json():
            advisories.append(
                SecurityAdvisory(
                    repo=_repo_from_advisory_url(adv.get("url", "")),
                    ghsa_id=adv.get("ghsa_id", ""),
                    summary=adv.get("summary", "") or adv.get("ghsa_id", ""),
                    state=adv.get("state", ""),
                    severity=adv.get("severity"),
                    updated_at=adv.get("updated_at", ""),
                    url=adv.get("html_url", ""),
                )
            )
        path = resp.links.get("next", {}).get("url")
    return advisories
