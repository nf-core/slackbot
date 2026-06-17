"""Slack helpers for proposal reviews: channel resolution, mentions, posting."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from nf_core_bot import config
from nf_core_bot.permissions.checks import get_usergroup_id

if TYPE_CHECKING:
    from slack_sdk.web.async_client import AsyncWebClient

logger = logging.getLogger(__name__)

# Keep each posted chunk well under Slack's per-message limits.
_CHUNK_CHARS = 3500

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


async def core_team_mention(client: AsyncWebClient) -> str:
    """Return a ``<!subteam^ID>`` mention for @core-team (falls back to text)."""
    handle = config.CORE_TEAM_USERGROUP_HANDLE or "core-team"
    group_id = await get_usergroup_id(client, handle)
    return f"<!subteam^{group_id}>" if group_id else "`@core-team`"


def chunk_message(text: str) -> list[str]:
    """Split *text* into Slack-sized chunks on paragraph boundaries."""
    if len(text) <= _CHUNK_CHARS:
        return [text]
    chunks: list[str] = []
    current = ""
    for para in text.split("\n\n"):
        candidate = f"{current}\n\n{para}" if current else para
        if len(candidate) > _CHUNK_CHARS and current:
            chunks.append(current)
            current = para
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks


async def post_review(
    client: AsyncWebClient,
    channel: str,
    text: str,
    *,
    thread_ts: str | None = None,
    ephemeral_user: str | None = None,
) -> str | None:
    """Post *text* to *channel*, splitting into multiple messages if long.

    When *ephemeral_user* is set the message is posted ephemerally to that user
    (used for ``preview`` runs). Returns the ``ts`` of the first posted message
    (None for ephemeral posts).
    """
    chunks = chunk_message(text)
    first_ts: str | None = None
    for i, chunk in enumerate(chunks):
        if ephemeral_user:
            await client.chat_postEphemeral(channel=channel, user=ephemeral_user, text=chunk)
            continue
        kwargs: dict[str, Any] = {"channel": channel, "text": chunk}
        # Keep multi-chunk posts together in a thread under the first chunk.
        ts = thread_ts or first_ts
        if ts:
            kwargs["thread_ts"] = ts
        resp = await client.chat_postMessage(**kwargs)
        if i == 0:
            first_ts = resp.get("ts")
    return first_ts
