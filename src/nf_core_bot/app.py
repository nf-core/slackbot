"""Bolt app entry-point — Socket Mode for local dev, HTTP for production.

Usage (local dev)::

    docker compose up -d dynamodb-local
    python -m nf_core_bot.app
"""

from __future__ import annotations

import logging
import re

from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler
from slack_bolt.app.async_app import AsyncApp

from nf_core_bot import config
from nf_core_bot.commands.github.add_member_shortcut import handle_add_member_shortcut
from nf_core_bot.commands.hackathon.admin import (
    handle_admin_delete_site,
    handle_admin_edit_site_picker,
    handle_admin_site_submission,
)
from nf_core_bot.commands.router import dispatch
from nf_core_bot.db import client as db_client
from nf_core_bot.forms.handler import (
    handle_country_suggestions,
    handle_registration_step,
)

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


@app.command("/nf-core")
async def handle_nf_core_bot(ack, respond, client, command):  # type: ignore[no-untyped-def]
    """Single entry-point — delegates to the router."""
    await dispatch(ack, respond, client, command)


# ── Modal callbacks ──────────────────────────────────────────────────

# Registration form steps use callback_id = "hackathon_reg_step_{n}".
# We register a regex listener so every step is handled by the same function.


@app.view(re.compile(r"^hackathon_reg_step_\d+$"))
async def on_registration_step(ack, body, client, view):  # type: ignore[no-untyped-def]
    """Handle every step of the multi-step registration modal."""
    await handle_registration_step(ack, body, client, view)


# ── Admin modal callbacks ────────────────────────────────────────────


@app.view("admin_edit_site_picker")
async def on_admin_edit_site_picker(ack, body, client):  # type: ignore[no-untyped-def]
    """Handle step-1 of edit-site: pick hackathon + site, then show edit form."""
    await handle_admin_edit_site_picker(ack, body, client)


@app.view("admin_site")
async def on_admin_site(ack, body, client):  # type: ignore[no-untyped-def]
    """Handle the site modal submission (add or edit)."""
    await handle_admin_site_submission(ack, body, client)


@app.action("admin_delete_site")
async def on_admin_delete_site(ack, body, client):  # type: ignore[no-untyped-def]
    """Handle the delete-site button in the edit-site modal."""
    await handle_admin_delete_site(ack, body, client)


# ── External-select option providers ─────────────────────────────────

# The ``country`` field uses ``external_select`` so all 197 countries are
# searchable via type-ahead rather than being truncated at 100.


@app.options("country")
async def on_country_suggestions(ack, body):  # type: ignore[no-untyped-def]
    """Provide type-ahead search results for the country field."""
    await handle_country_suggestions(ack, body)


# ── Message shortcut ────────────────────────────────────────────────


@app.shortcut("add_to_github_org")
async def shortcut_add_to_github_org(ack, shortcut, client):  # type: ignore[no-untyped-def]
    """Message shortcut — right-click a message → Add to GitHub org."""
    await handle_add_member_shortcut(ack, shortcut, client)


# ── Startup ──────────────────────────────────────────────────────────


async def _start() -> None:
    """Initialise DB and start the Socket-Mode handler."""
    assert config.DYNAMODB_TABLE is not None  # has default
    assert config.AWS_REGION is not None  # has default
    try:
        db_client.init(
            table_name=config.DYNAMODB_TABLE,
            endpoint_url=config.DYNAMODB_ENDPOINT,
            region=config.AWS_REGION,
        )
    except Exception:
        logger.warning(
            "DynamoDB unavailable — hackathon commands will not work, but GitHub commands are fully functional.",
            exc_info=True,
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
