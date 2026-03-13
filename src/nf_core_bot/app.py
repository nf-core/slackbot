"""Bolt app entry-point — Socket Mode for local dev, HTTP for production.

Usage (local dev)::

    docker compose up -d dynamodb-local
    python -m nf_core_bot.app
"""

from __future__ import annotations

import logging

from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler
from slack_bolt.app.async_app import AsyncApp

from nf_core_bot import config
from nf_core_bot.commands.router import dispatch
from nf_core_bot.db import client as db_client

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(name)-30s  %(levelname)-8s  %(message)s",
)
logger = logging.getLogger(__name__)

# ── Bolt app ─────────────────────────────────────────────────────────

app = AsyncApp(
    token=config.SLACK_BOT_TOKEN,
    signing_secret=config.SLACK_SIGNING_SECRET,
)


# ── Slash command ────────────────────────────────────────────────────


@app.command("/nf-core-bot")
async def handle_nf_core_bot(ack, respond, client, command):  # type: ignore[no-untyped-def]
    """Single entry-point — delegates to the router."""
    await dispatch(ack, respond, client, command)


# ── Startup ──────────────────────────────────────────────────────────


async def _start() -> None:
    """Initialise DB and start the Socket-Mode handler."""
    assert config.DYNAMODB_TABLE is not None  # has default
    assert config.AWS_REGION is not None  # has default
    db_client.init(
        table_name=config.DYNAMODB_TABLE,
        endpoint_url=config.DYNAMODB_ENDPOINT,
        region=config.AWS_REGION,
    )
    logger.info("nf-core-bot starting (Socket Mode) …")

    handler = AsyncSocketModeHandler(app, config.SLACK_APP_TOKEN)
    await handler.start_async()  # type: ignore[no-untyped-call]


def main() -> None:
    """Synchronous wrapper so ``python -m nf_core_bot.app`` works."""
    import asyncio

    asyncio.run(_start())


if __name__ == "__main__":
    main()
