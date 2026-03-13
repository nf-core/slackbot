"""Permission checks — @core-team user-group membership (cached) and site organiser role.

The ``@core-team`` Slack user-group membership list is fetched via the Slack
API and cached for ``CACHE_TTL`` seconds to avoid hitting rate limits.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING, Any

from nf_core_bot.db.client import get_table

if TYPE_CHECKING:
    from slack_sdk.web.async_client import AsyncWebClient

logger = logging.getLogger(__name__)

# ── Core-team cache ──────────────────────────────────────────────────

CACHE_TTL: int = 300  # 5 minutes

_core_team_ids: set[str] = set()
_core_team_fetched_at: float = 0.0
_core_team_lock: asyncio.Lock | None = None


def _get_core_team_lock() -> asyncio.Lock:
    """Return (and lazily create) the async lock for core-team refresh.

    Created lazily because ``asyncio.Lock`` must be instantiated inside a
    running event loop.
    """
    global _core_team_lock  # noqa: PLW0603
    if _core_team_lock is None:
        _core_team_lock = asyncio.Lock()
    return _core_team_lock


async def refresh_core_team(client: AsyncWebClient, usergroup_handle: str) -> set[str]:
    """Fetch members of the ``@core-team`` user-group from Slack.

    Caches the result for ``CACHE_TTL`` seconds.  An async lock prevents
    concurrent requests from firing redundant API calls.
    """
    global _core_team_ids, _core_team_fetched_at  # noqa: PLW0603

    now = time.monotonic()
    if _core_team_ids and (now - _core_team_fetched_at) < CACHE_TTL:
        return _core_team_ids

    async with _get_core_team_lock():
        # Double-check after acquiring the lock.
        now = time.monotonic()
        if _core_team_ids and (now - _core_team_fetched_at) < CACHE_TTL:
            return _core_team_ids

        logger.info("Refreshing @%s user-group membership …", usergroup_handle)
        try:
            # First, resolve the handle to a usergroup ID.
            groups_resp = await client.usergroups_list(include_users=False)
            groups: list[dict[str, Any]] = groups_resp.get("usergroups", [])
            group_id: str | None = None
            for group in groups:
                if group.get("handle") == usergroup_handle:
                    group_id = group["id"]
                    break

            if group_id is None:
                logger.warning("User-group @%s not found.", usergroup_handle)
                _core_team_ids = set()
                _core_team_fetched_at = now
                return _core_team_ids

            # Fetch the members of that group.
            members_resp = await client.usergroups_users_list(usergroup=group_id)
            _core_team_ids = set(members_resp.get("users", []))
            _core_team_fetched_at = now
            logger.info("Cached %d @%s members.", len(_core_team_ids), usergroup_handle)
        except Exception:
            logger.exception("Failed to refresh @%s membership.", usergroup_handle)

    return _core_team_ids


async def is_core_team(client: AsyncWebClient, user_id: str, usergroup_handle: str | None = None) -> bool:
    """Return True if *user_id* is in the @core-team user-group.

    If *usergroup_handle* is not provided, it is read from config.
    """
    if usergroup_handle is None:
        from nf_core_bot import config

        usergroup_handle = config.CORE_TEAM_USERGROUP_HANDLE or "core-team"
    members = await refresh_core_team(client, usergroup_handle)
    return user_id in members


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
