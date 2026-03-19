"""Reusable test helpers for Slack client mocking."""

from __future__ import annotations

from unittest.mock import AsyncMock


def make_slack_client() -> AsyncMock:
    """Build an ``AsyncWebClient`` mock whose ``conversations_open`` returns a DM channel."""
    client = AsyncMock()
    client.conversations_open.return_value = {"channel": {"id": "D_DM"}}
    return client


def channel_messages(client: AsyncMock, channel: str = "C_CHAN") -> list[str]:
    """Return all ``chat_postMessage`` texts sent to *channel*."""
    texts: list[str] = []
    for call in client.chat_postMessage.call_args_list:
        ch = call.kwargs.get("channel", call.args[0] if call.args else "")
        if ch == channel:
            texts.append(call.kwargs.get("text", ""))
    return texts


def dm_messages(client: AsyncMock) -> list[str]:
    """Return all ``chat_postMessage`` texts sent to the DM channel."""
    return channel_messages(client, "D_DM")
