"""Hackathon registration: register, edit, and cancel commands."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from nf_core_bot.db.registrations import delete_registration, get_registration
from nf_core_bot.forms.handler import open_registration_modal
from nf_core_bot.forms.loader import get_active_form

if TYPE_CHECKING:
    from slack_bolt.context.ack.async_ack import AsyncAck
    from slack_bolt.context.respond.async_respond import AsyncRespond
    from slack_sdk.web.async_client import AsyncWebClient

logger = logging.getLogger(__name__)


async def handle_register(
    ack: AsyncAck,
    respond: AsyncRespond,
    client: AsyncWebClient,
    body: dict[str, Any],
) -> None:
    """Open the registration modal for the active hackathon."""
    await ack()

    user_id: str = body["user_id"]
    trigger_id: str = body["trigger_id"]

    try:
        hackathon = get_active_form()
    except Exception:
        logger.exception("Failed to look up active hackathon.")
        await respond(
            text="Something went wrong looking up the active hackathon. Please try again later.",
            response_type="ephemeral",
        )
        return

    if hackathon is None:
        await respond(
            text="No hackathon is currently open for registration.",
            response_type="ephemeral",
        )
        return

    hackathon_id: str = hackathon["hackathon_id"]

    try:
        existing = await get_registration(hackathon_id, user_id)
    except Exception:
        logger.exception("Failed to check existing registration for user '%s'.", user_id)
        await respond(
            text="Something went wrong checking your registration status. Please try again later.",
            response_type="ephemeral",
        )
        return

    if existing is not None:
        await respond(
            text="You're already registered! Use `/nf-core-bot hackathon edit` to update.",
            response_type="ephemeral",
        )
        return

    await open_registration_modal(client, trigger_id, hackathon_id, user_id)


async def handle_edit(
    ack: AsyncAck,
    respond: AsyncRespond,
    client: AsyncWebClient,
    body: dict[str, Any],
) -> None:
    """Re-open the registration modal pre-filled with the user's existing data."""
    await ack()

    user_id: str = body["user_id"]
    trigger_id: str = body["trigger_id"]

    try:
        hackathon = get_active_form()
    except Exception:
        logger.exception("Failed to look up active hackathon.")
        await respond(
            text="Something went wrong looking up the active hackathon. Please try again later.",
            response_type="ephemeral",
        )
        return

    if hackathon is None:
        await respond(
            text="No hackathon is currently open for registration.",
            response_type="ephemeral",
        )
        return

    hackathon_id: str = hackathon["hackathon_id"]

    try:
        existing = await get_registration(hackathon_id, user_id)
    except Exception:
        logger.exception("Failed to fetch registration for user '%s'.", user_id)
        await respond(
            text="Something went wrong looking up your registration. Please try again later.",
            response_type="ephemeral",
        )
        return

    if existing is None:
        await respond(
            text="You're not registered yet. Use `/nf-core-bot hackathon register` to sign up first.",
            response_type="ephemeral",
        )
        return

    # Reconstruct the full form answers: merge form_data with site selection.
    existing_data: dict[str, Any] = dict(existing.get("form_data", {}))
    site_id = existing.get("site_id")
    if site_id is not None:
        existing_data["local_site"] = site_id

    await open_registration_modal(
        client,
        trigger_id,
        hackathon_id,
        user_id,
        existing_data=existing_data,
    )


async def handle_cancel(
    ack: AsyncAck,
    respond: AsyncRespond,
    client: AsyncWebClient,
    body: dict[str, Any],
) -> None:
    """Cancel the calling user's registration."""
    await ack()

    user_id: str = body["user_id"]

    try:
        hackathon = get_active_form()
    except Exception:
        logger.exception("Failed to look up active hackathon.")
        await respond(
            text="Something went wrong looking up the active hackathon. Please try again later.",
            response_type="ephemeral",
        )
        return

    if hackathon is None:
        await respond(
            text="No hackathon is currently open for registration.",
            response_type="ephemeral",
        )
        return

    hackathon_id: str = hackathon["hackathon_id"]

    try:
        existing = await get_registration(hackathon_id, user_id)
    except Exception:
        logger.exception("Failed to check registration for user '%s'.", user_id)
        await respond(
            text="Something went wrong looking up your registration. Please try again later.",
            response_type="ephemeral",
        )
        return

    if existing is None:
        await respond(
            text="You don't have an active registration to cancel.",
            response_type="ephemeral",
        )
        return

    try:
        await delete_registration(hackathon_id, user_id)
    except Exception:
        logger.exception("Failed to delete registration for user '%s'.", user_id)
        await respond(
            text="Something went wrong cancelling your registration. Please try again later.",
            response_type="ephemeral",
        )
        return

    hackathon_title = hackathon.get("title", hackathon_id)
    await respond(
        text=f"Your registration for *{hackathon_title}* has been cancelled.",
        response_type="ephemeral",
    )
    logger.info("User '%s' cancelled registration for hackathon '%s'.", user_id, hackathon_id)
