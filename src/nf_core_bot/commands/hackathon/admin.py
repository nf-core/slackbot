"""Admin-only hackathon commands (core-team only).

Subcommands:
    create, open, close, archive, list
    add-site, remove-site, list-sites
    add-organiser, remove-organiser
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from slack_bolt.context.ack.async_ack import AsyncAck as Ack
    from slack_bolt.context.respond.async_respond import AsyncRespond as Respond

# ── Hackathon lifecycle ─────────────────────────────────────────────


async def handle_admin_create(ack: Ack, respond: Respond, args: list[str]) -> None:
    await ack()
    await respond("Creating hackathons is not yet implemented.", response_type="ephemeral")


async def handle_admin_open(ack: Ack, respond: Respond, args: list[str]) -> None:
    await ack()
    await respond("Opening hackathons is not yet implemented.", response_type="ephemeral")


async def handle_admin_close(ack: Ack, respond: Respond, args: list[str]) -> None:
    await ack()
    await respond("Closing hackathons is not yet implemented.", response_type="ephemeral")


async def handle_admin_archive(ack: Ack, respond: Respond, args: list[str]) -> None:
    await ack()
    await respond("Archiving hackathons is not yet implemented.", response_type="ephemeral")


async def handle_admin_list(ack: Ack, respond: Respond) -> None:
    await ack()
    await respond("Listing hackathons is not yet implemented.", response_type="ephemeral")


# ── Site management ──────────────────────────────────────────────────


async def handle_admin_add_site(ack: Ack, respond: Respond, args: list[str]) -> None:
    await ack()
    await respond("Adding sites is not yet implemented.", response_type="ephemeral")


async def handle_admin_remove_site(ack: Ack, respond: Respond, args: list[str]) -> None:
    await ack()
    await respond("Removing sites is not yet implemented.", response_type="ephemeral")


async def handle_admin_list_sites(ack: Ack, respond: Respond, args: list[str]) -> None:
    await ack()
    await respond("Listing sites is not yet implemented.", response_type="ephemeral")


# ── Organiser management ────────────────────────────────────────────


async def handle_admin_add_organiser(ack: Ack, respond: Respond, args: list[str]) -> None:
    await ack()
    await respond("Adding organisers is not yet implemented.", response_type="ephemeral")


async def handle_admin_remove_organiser(ack: Ack, respond: Respond, args: list[str]) -> None:
    await ack()
    await respond("Removing organisers is not yet implemented.", response_type="ephemeral")
