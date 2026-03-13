"""Attendee list commands — visible to organisers and core-team."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from slack_bolt.context.ack.async_ack import AsyncAck as Ack
    from slack_bolt.context.respond.async_respond import AsyncRespond as Respond


async def handle_attendees(ack: Ack, respond: Respond, args: list[str]) -> None:
    """List attendees, optionally filtered by site.

    Usage: /nf-core-bot hackathon attendees [site]
    """
    await ack()
    await respond("Listing attendees is not yet implemented.", response_type="ephemeral")
