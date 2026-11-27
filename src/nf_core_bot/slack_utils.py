"""Shared Slack helpers."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from slack_sdk.web.async_client import AsyncWebClient

logger = logging.getLogger(__name__)

_channel_cache: dict[str, str] = {}


async def resolve_channel_id(client: AsyncWebClient, name: str) -> str | None:
    """Resolve a channel *name* to its ID, cached for the process lifetime."""
    if name in _channel_cache:
        return _channel_cache[name]

    cursor: str | None = None
    while True:
        kwargs: dict[str, Any] = {
            "types": "public_channel,private_channel",
            "exclude_archived": True,
            "limit": 200,
        }
        if cursor:
            kwargs["cursor"] = cursor
        try:
            resp = await client.conversations_list(**kwargs)
        except Exception:
            logger.exception("Failed to list conversations while resolving #%s", name)
            return None
        channels: list[dict[str, Any]] = resp.get("channels", [])
        for ch in channels:
            if ch.get("name") == name:
                cid = str(ch["id"])
                _channel_cache[name] = cid
                return cid
        cursor = (resp.get("response_metadata") or {}).get("next_cursor")
        if not cursor:
            break
    logger.warning("Could not find channel #%s — is the bot a member?", name)
    return None
