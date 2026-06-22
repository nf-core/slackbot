"""Read Slack profile fields (email, display name, GitHub username).

The GitHub username is stored in a custom Slack profile field. The field ID
varies per workspace, so we discover it at startup by calling
``team.profile.get`` and searching for a field labelled "GitHub".

The discovered field ID is cached for the process lifetime.
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import TYPE_CHECKING, Any

from slack_sdk.web.async_client import AsyncWebClient

from nf_core_bot import config

if TYPE_CHECKING:
    from collections.abc import Callable

logger = logging.getLogger(__name__)

# ── GitHub profile field IDs ─────────────────────────────────────────
# The workspace has two GitHub custom fields:
#   "GitHub"        — member-editable; the bot READS it to look up handles.
#   "GitHub (auto)" — API data source (members can't edit it); the bot WRITES
#                     invited handles here, as a link, for display. Writes only
#                     work because this field's Data source is set to "API" in
#                     the Slack "Configure profiles" admin tool.

_github_field_id: str | None = None
_github_field_resolved: bool = False
_github_auto_field_id: str | None = None
_github_auto_field_resolved: bool = False
_github_field_lock: asyncio.Lock | None = None


def _get_github_field_lock() -> asyncio.Lock:
    """Return (and lazily create) the async lock for field-ID resolution.

    The lock is created on first use rather than at import time because
    ``asyncio.Lock`` must be created inside a running event loop.
    """
    global _github_field_lock  # noqa: PLW0603
    if _github_field_lock is None:
        _github_field_lock = asyncio.Lock()
    return _github_field_lock


async def _fetch_field_id(client: AsyncWebClient, match: Callable[[str], bool]) -> str | None:
    """Return the ID of the first custom profile field whose label matches.

    *match* receives the lower-cased field label.
    """
    resp = await client.api_call("team.profile.get")
    profile_data: dict[str, Any] = resp.get("profile", {})
    fields: list[dict[str, Any]] = profile_data.get("fields", [])
    for field in fields:
        if match((field.get("label") or "").lower()):
            return str(field["id"])
    return None


async def _resolve_github_field_id(client: AsyncWebClient) -> str | None:
    """Discover the ID of the member-editable "GitHub" field (for reads).

    Matches a GitHub-labelled field but excludes the "(auto)" write field.
    Calls ``team.profile.get`` once and caches the result.

    An async lock ensures concurrent callers don't fire redundant API calls.
    """
    global _github_field_id, _github_field_resolved  # noqa: PLW0603

    if _github_field_resolved:
        return _github_field_id

    async with _get_github_field_lock():
        if _github_field_resolved:  # double-check after acquiring the lock
            return _github_field_id
        try:
            _github_field_id = await _fetch_field_id(client, lambda lbl: "github" in lbl and "auto" not in lbl)
            if _github_field_id is None:
                logger.warning("No member GitHub custom profile field found in workspace.")
            else:
                logger.info("Resolved member GitHub profile field: id=%s", _github_field_id)
            # Only cache when the API call succeeded — a transient failure
            # should not permanently disable resolution.
            _github_field_resolved = True
        except Exception:
            logger.exception("Failed to call team.profile.get — will retry on next call")

    return _github_field_id


async def _resolve_github_auto_field_id(client: AsyncWebClient) -> str | None:
    """Discover the ID of the API-managed "GitHub (auto)" field (for writes).

    Returns ``None`` if no such field exists — in which case the write-back is
    disabled (the field must be created with Data source = API in Slack admin).
    """
    global _github_auto_field_id, _github_auto_field_resolved  # noqa: PLW0603

    if _github_auto_field_resolved:
        return _github_auto_field_id

    async with _get_github_field_lock():
        if _github_auto_field_resolved:  # double-check after acquiring the lock
            return _github_auto_field_id
        try:
            _github_auto_field_id = await _fetch_field_id(client, lambda lbl: "github" in lbl and "auto" in lbl)
            if _github_auto_field_id is None:
                logger.warning("No 'GitHub (auto)' profile field found — profile write-back disabled.")
            else:
                logger.info("Resolved GitHub (auto) profile field: id=%s", _github_auto_field_id)
            _github_auto_field_resolved = True
        except Exception:
            logger.exception("Failed to call team.profile.get — will retry on next call")

    return _github_auto_field_id


async def _read_field_value(client: AsyncWebClient, user_id: str, field_id: str) -> str:
    """Return the raw value of *field_id* in *user_id*'s profile (``""`` if unset)."""
    try:
        resp = await client.users_profile_get(user=user_id)
        profile: dict[str, Any] = resp.get("profile", {})
        fields: dict[str, Any] = profile.get("fields", {}) or {}
        field_data = fields.get(field_id, {})
        return (field_data.get("value") or "").strip()
    except Exception:
        logger.exception("Failed to read profile field for user %s", user_id)
        return ""


async def get_github_username(client: AsyncWebClient, user_id: str) -> str | None:
    """Return the GitHub username from a Slack user's profile, or ``None``.

    Handles common variations: full URLs (``https://github.com/octocat``),
    ``@``-prefixed handles, or bare usernames.
    """
    field_id = await _resolve_github_field_id(client)
    if field_id is None:
        return None

    try:
        resp = await client.users_profile_get(user=user_id)
        profile: dict[str, Any] = resp.get("profile", {})
        fields: dict[str, Any] = profile.get("fields", {}) or {}

        field_data = fields.get(field_id, {})
        raw_value: str = (field_data.get("value") or "").strip()

        if not raw_value:
            return None

        return normalise_github_username(raw_value)
    except Exception:
        logger.exception("Failed to read profile for user %s", user_id)
        return None


# ── Admin user-token client (for writing other users' profiles) ──────
#
# Writing a *different* member's profile requires a user token (xoxp-)
# generated by a Workspace Admin/Owner — a bot token cannot do it. The token
# is optional: when unset, set_github_username() silently no-ops so the bot
# runs unchanged in workspaces (and local dev) without it.

_admin_client: AsyncWebClient | None = None
_admin_client_resolved: bool = False


def _get_admin_client() -> AsyncWebClient | None:
    """Return (and lazily build) the admin user-token client, or ``None``.

    ``None`` is returned when ``SLACK_ADMIN_USER_TOKEN`` is not configured.
    """
    global _admin_client, _admin_client_resolved  # noqa: PLW0603
    if not _admin_client_resolved:
        token = config.SLACK_ADMIN_USER_TOKEN
        _admin_client = AsyncWebClient(token=token) if token else None
        _admin_client_resolved = True
    return _admin_client


async def set_github_username(client: AsyncWebClient, user_id: str, handle: str) -> bool:
    """Write *handle* into *user_id*'s "GitHub (auto)" profile field. Best-effort.

    *client* is the bot client, used to resolve field IDs and read current
    values (needs ``users.profile:read``). The write itself goes through the
    admin user-token client (``users.profile:write``); the target field must
    have its Data source set to "API" or Slack silently no-ops the write.

    The field is a *link* type, so we store the GitHub URL as the value and the
    ``@``-prefixed handle as the display text.

    Skips — returning ``False`` — when: the admin token is unconfigured, the
    "(auto)" field doesn't exist, or the auto field is already set (idempotent
    re-runs). Never raises: any failure is logged and returns ``False``.
    """
    admin = _get_admin_client()
    if admin is None:
        return False

    auto_field_id = await _resolve_github_auto_field_id(client)
    if auto_field_id is None:
        return False

    # Idempotent: skip if the auto field is already populated.
    if await _read_field_value(client, user_id, auto_field_id):
        return False

    url = f"https://github.com/{handle}"
    try:
        await admin.users_profile_set(
            user=user_id,
            profile={"fields": {auto_field_id: {"value": url, "alt": f"@{handle}"}}},
        )
        logger.info("Wrote GitHub handle %r to auto profile field of user %s", handle, user_id)
        return True
    except Exception:
        logger.exception("Failed to write GitHub handle to profile of user %s", user_id)
        return False


def normalise_github_username(raw: str) -> str | None:
    """Extract a bare GitHub username from various input formats.

    Handles:
    - ``https://github.com/octocat``
    - ``github.com/octocat``
    - ``@octocat``
    - ``octocat``
    - Slack auto-linked URLs: ``<https://github.com/octocat>`` and
      ``<https://github.com/octocat|github.com/octocat>``
    """
    raw = raw.strip()

    # Slack wraps auto-linked URLs in angle brackets (``<url>`` or
    # ``<url|display>``). Workflow form submissions go through this path, so
    # strip the wrapper before URL extraction.
    slack_link = re.match(r"<([^|>]+)(?:\|[^>]*)?>$", raw)
    if slack_link:
        raw = slack_link.group(1)

    # URL form — extract the first path segment before any other cleanup.
    url_match = re.match(r"(?:https?://)?github\.com/([A-Za-z0-9_.-]+)", raw)
    if url_match:
        raw = url_match.group(1)

    # Strip leading/trailing non-alphanumeric noise (handles @, /, \, ., etc.)
    raw = re.sub(r"^[^A-Za-z0-9]+", "", raw)
    raw = re.sub(r"[^A-Za-z0-9]+$", "", raw)

    # Validate: GitHub usernames are alphanumeric + hyphens, 1-39 chars.
    if raw and re.fullmatch(r"[A-Za-z0-9]([A-Za-z0-9-]*[A-Za-z0-9])?", raw) and len(raw) <= 39:
        return raw

    return None
