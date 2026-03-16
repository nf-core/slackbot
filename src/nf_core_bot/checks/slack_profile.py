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

if TYPE_CHECKING:
    from slack_sdk.web.async_client import AsyncWebClient

logger = logging.getLogger(__name__)

# ── GitHub profile field ID cache ────────────────────────────────────

_github_field_id: str | None = None
_github_field_resolved: bool = False
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


async def _resolve_github_field_id(client: AsyncWebClient) -> str | None:
    """Discover the custom profile field ID for the GitHub username.

    Calls ``team.profile.get`` once and caches the result.  Returns ``None``
    if no field with a GitHub-related label is found.

    An async lock ensures concurrent callers don't fire redundant API calls.
    """
    global _github_field_id, _github_field_resolved  # noqa: PLW0603

    if _github_field_resolved:
        return _github_field_id

    async with _get_github_field_lock():
        # Double-check after acquiring the lock — another coroutine may
        # have resolved it while we were waiting.
        if _github_field_resolved:
            return _github_field_id

        try:
            resp = await client.api_call("team.profile.get")
            profile_data: dict[str, Any] = resp.get("profile", {})
            fields: list[dict[str, Any]] = profile_data.get("fields", [])
            for field in fields:
                label = (field.get("label") or "").lower()
                if "github" in label:
                    _github_field_id = field["id"]
                    logger.info(
                        "Resolved GitHub profile field: id=%s label=%r",
                        _github_field_id,
                        field.get("label"),
                    )
                    break
            else:
                logger.warning("No GitHub custom profile field found in workspace.")
            # Only cache when the API call succeeded — a transient failure
            # should not permanently disable GitHub username resolution.
            _github_field_resolved = True
        except Exception:
            logger.exception("Failed to call team.profile.get — will retry on next call")

    return _github_field_id


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


def normalise_github_username(raw: str) -> str | None:
    """Extract a bare GitHub username from various input formats.

    Handles:
    - ``https://github.com/octocat``
    - ``github.com/octocat``
    - ``@octocat``
    - ``octocat``
    """
    raw = raw.strip()

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
