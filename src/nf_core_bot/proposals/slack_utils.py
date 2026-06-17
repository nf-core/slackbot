"""Slack helpers for proposal reviews: channel resolution, mentions, posting."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from nf_core_bot import config
from nf_core_bot.permissions.checks import get_usergroup_id

if TYPE_CHECKING:
    from slack_sdk.web.async_client import AsyncWebClient

logger = logging.getLogger(__name__)

# Slack `markdown` blocks cap at 12,000 chars cumulatively; stay safely under.
_MD_BLOCK_LIMIT = 11000

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


def chunk_message(text: str, limit: int = _MD_BLOCK_LIMIT) -> list[str]:
    """Split *text* into chunks no larger than *limit*, on paragraph boundaries."""
    if len(text) <= limit:
        return [text]
    chunks: list[str] = []
    current = ""
    for para in text.split("\n\n"):
        candidate = f"{current}\n\n{para}" if current else para
        if len(candidate) > limit and current:
            chunks.append(current)
            current = para
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks


def build_review_blocks(header: str, body: str, footer: str) -> list[dict[str, Any]]:
    """Assemble the review into Block Kit blocks for a single Slack message.

    * *header* → a ``section`` (mrkdwn) so the ``<!subteam^…>`` mention notifies
      and the ``<url|title>`` link renders;
    * *body* → one or more ``markdown`` blocks so standard Markdown (nested
      bullets, bold, code blocks) renders natively rather than as literal text;
    * *footer* → a small ``context`` block.
    """
    blocks: list[dict[str, Any]] = [{"type": "section", "text": {"type": "mrkdwn", "text": header}}]
    blocks += [{"type": "markdown", "text": chunk} for chunk in chunk_message(body)]
    if footer:
        blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": footer}]})
    return blocks


async def post_review(
    client: AsyncWebClient,
    channel: str,
    blocks: list[dict[str, Any]],
    text: str,
    *,
    thread_ts: str | None = None,
) -> str | None:
    """Post the review as a single Block Kit message; return its ``ts``.

    *text* is the short plain-text fallback (notifications / accessibility).
    """
    kwargs: dict[str, Any] = {"channel": channel, "blocks": blocks, "text": text}
    if thread_ts:
        kwargs["thread_ts"] = thread_ts
    resp = await client.chat_postMessage(**kwargs)
    return resp.get("ts")
