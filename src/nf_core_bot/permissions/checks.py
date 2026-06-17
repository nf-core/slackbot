"""Permission checks — @core-team user-group membership (cached) and site organiser role.

The ``@core-team`` Slack user-group membership list is fetched via the Slack
API and cached for ``CACHE_TTL`` seconds to avoid hitting rate limits.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from nf_core_bot.db.client import get_table

if TYPE_CHECKING:
    from slack_sdk.web.async_client import AsyncWebClient

logger = logging.getLogger(__name__)

# ── User-group cache ─────────────────────────────────────────────────
# Membership of Slack user-groups (``@core-team``, ``@maintainers-team``) is
# fetched from the Slack API and cached for ``CACHE_TTL`` seconds, keyed by
# handle.  An async lock prevents concurrent requests firing redundant calls.

CACHE_TTL: int = 300  # 5 minutes


@dataclass
class _UsergroupCacheEntry:
    """A cached snapshot of one Slack user-group."""

    group_id: str | None  # the ``S…`` subteam ID, or None if the handle is unknown
    member_ids: set[str]
    fetched_at: float


# handle → cached snapshot
_usergroup_cache: dict[str, _UsergroupCacheEntry] = {}
_usergroup_lock: asyncio.Lock | None = None


def _get_usergroup_lock() -> asyncio.Lock:
    """Return (and lazily create) the async lock for user-group refreshes.

    Created lazily because ``asyncio.Lock`` must be instantiated inside a
    running event loop.
    """
    global _usergroup_lock  # noqa: PLW0603
    if _usergroup_lock is None:
        _usergroup_lock = asyncio.Lock()
    return _usergroup_lock


async def refresh_usergroup(client: AsyncWebClient, handle: str) -> tuple[str | None, set[str]]:
    """Resolve a user-group *handle* to ``(subteam_id, member_ids)``, cached.

    On API failure the previous (stale) cache entry is returned if present,
    otherwise ``(None, set())``.
    """
    now = time.monotonic()
    entry = _usergroup_cache.get(handle)
    if entry is not None and (now - entry.fetched_at) < CACHE_TTL:
        return entry.group_id, entry.member_ids

    async with _get_usergroup_lock():
        # Double-check after acquiring the lock.
        now = time.monotonic()
        entry = _usergroup_cache.get(handle)
        if entry is not None and (now - entry.fetched_at) < CACHE_TTL:
            return entry.group_id, entry.member_ids

        logger.info("Refreshing @%s user-group membership …", handle)
        try:
            # First, resolve the handle to a usergroup ID.
            groups_resp = await client.usergroups_list(include_users=False)
            groups: list[dict[str, Any]] = groups_resp.get("usergroups", [])
            group_id: str | None = next((g["id"] for g in groups if g.get("handle") == handle), None)

            if group_id is None:
                logger.warning("User-group @%s not found.", handle)
                new_entry = _UsergroupCacheEntry(group_id=None, member_ids=set(), fetched_at=now)
                _usergroup_cache[handle] = new_entry
                return None, new_entry.member_ids

            members_resp = await client.usergroups_users_list(usergroup=group_id)
            new_entry = _UsergroupCacheEntry(
                group_id=group_id,
                member_ids=set(members_resp.get("users", [])),
                fetched_at=now,
            )
            _usergroup_cache[handle] = new_entry
            logger.info("Cached %d @%s members.", len(new_entry.member_ids), handle)
            return new_entry.group_id, new_entry.member_ids
        except Exception:
            logger.exception("Failed to refresh @%s membership.", handle)
            # Return stale data if we have any; the caller can proceed best-effort.
            stale = _usergroup_cache.get(handle)
            if stale is not None:
                return stale.group_id, stale.member_ids
            return None, set()


async def refresh_core_team(client: AsyncWebClient, usergroup_handle: str) -> set[str]:
    """Fetch members of the ``@core-team`` user-group (member IDs only)."""
    _, members = await refresh_usergroup(client, usergroup_handle)
    return members


async def get_usergroup_id(client: AsyncWebClient, handle: str) -> str | None:
    """Return the ``S…`` subteam ID for *handle*, for ``<!subteam^ID>`` mentions."""
    group_id, _ = await refresh_usergroup(client, handle)
    return group_id


async def is_core_team(client: AsyncWebClient, user_id: str, usergroup_handle: str | None = None) -> bool:
    """Return True if *user_id* is in the @core-team user-group.

    If *usergroup_handle* is not provided, it is read from config.
    """
    if usergroup_handle is None:
        from nf_core_bot import config

        usergroup_handle = config.CORE_TEAM_USERGROUP_HANDLE or "core-team"
    _, members = await refresh_usergroup(client, usergroup_handle)
    return user_id in members


async def is_maintainer(client: AsyncWebClient, user_id: str) -> bool:
    """Return True if *user_id* is in the @maintainers-team user-group."""
    from nf_core_bot import config

    handle = config.MAINTAINERS_USERGROUP_HANDLE or "maintainers-team"
    _, members = await refresh_usergroup(client, handle)
    return user_id in members


async def is_core_team_or_maintainers(client: AsyncWebClient, user_id: str) -> bool:
    """Return True if *user_id* is in either @core-team or @maintainers-team."""
    return await is_core_team(client, user_id) or await is_maintainer(client, user_id)


async def is_site_organiser(user_id: str, hackathon_id: str, site_id: str) -> bool:
    """Return True if *user_id* is an organiser for *site_id* in *hackathon_id*.

    Checks for a DynamoDB item with:
        PK = HACKATHON#<hackathon_id>
        SK = SITE#<site_id>#ORG#<user_id>
    """
    table = get_table()
    key = {
        "PK": f"HACKATHON#{hackathon_id}",
        "SK": f"SITE#{site_id}#ORG#{user_id}",
    }
    resp = await asyncio.to_thread(table.get_item, Key=key)
    return "Item" in resp


async def is_organiser_any_site(user_id: str, hackathon_id: str) -> bool:
    """Return True if *user_id* is an organiser for *any* site in the hackathon.

    Uses a begins_with query on the sort key to find any organiser record.
    """
    table = get_table()
    from boto3.dynamodb.conditions import Key

    resp = await asyncio.to_thread(
        table.query,
        KeyConditionExpression=Key("PK").eq(f"HACKATHON#{hackathon_id}") & Key("SK").begins_with("SITE#"),
        FilterExpression="contains(SK, :org_suffix)",
        ExpressionAttributeValues={":org_suffix": f"#ORG#{user_id}"},
    )
    return len(resp.get("Items", [])) > 0
