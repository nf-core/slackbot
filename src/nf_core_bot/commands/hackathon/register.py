"""Hackathon registration: register, edit, and cancel commands."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from slack_bolt.context.ack.async_ack import AsyncAck as Ack
    from slack_bolt.context.respond.async_respond import AsyncRespond as Respond


async def handle_register(ack: Ack, respond: Respond) -> None:
    """Open the registration modal for the active hackathon."""
    await ack()
    await respond("Hackathon registration is not yet implemented.", response_type="ephemeral")


async def handle_edit(ack: Ack, respond: Respond) -> None:
    """Re-open the registration modal pre-filled with the user's existing data."""
    await ack()
    await respond("Editing registrations is not yet implemented.", response_type="ephemeral")


async def handle_cancel(ack: Ack, respond: Respond) -> None:
    """Cancel the calling user's registration."""
    await ack()
    await respond("Cancelling registrations is not yet implemented.", response_type="ephemeral")
