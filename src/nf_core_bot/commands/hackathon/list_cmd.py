"""List hackathons — a user-facing command showing all non-archived hackathons.

Usage: ``/nf-core-bot hackathon list``
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from nf_core_bot.db.hackathons import list_hackathons
from nf_core_bot.db.registrations import count_registrations, get_registration

if TYPE_CHECKING:
    from slack_bolt.context.ack.async_ack import AsyncAck
    from slack_bolt.context.respond.async_respond import AsyncRespond
    from slack_sdk.web.async_client import AsyncWebClient

logger = logging.getLogger(__name__)

# Human-friendly labels for hackathon statuses.
_STATUS_LABELS: dict[str, str] = {
    "draft": "Draft",
    "open": "Open",
    "closed": "Closed",
}


async def handle_list(
    ack: AsyncAck,
    respond: AsyncRespond,
    client: AsyncWebClient,
    body: dict[str, Any],
) -> None:
    """List all non-archived hackathons with the caller's registration status."""
    await ack()

    user_id: str = body["user_id"]

    try:
        hackathons = await list_hackathons()
    except Exception:
        logger.exception("Failed to list hackathons.")
        await respond(
            text="Something went wrong loading hackathons. Please try again later.",
            response_type="ephemeral",
        )
        return

    # Filter out archived hackathons.
    visible = [h for h in hackathons if h.get("status") != "archived"]

    if not visible:
        await respond(
            text="There are no hackathons to show right now.",
            response_type="ephemeral",
        )
        return

    # Sort by created_at descending (newest first).
    visible.sort(key=lambda h: h.get("created_at", ""), reverse=True)

    blocks: list[dict[str, Any]] = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": "Hackathons"},
        },
    ]

    for hackathon in visible:
        hackathon_id: str = hackathon["hackathon_id"]
        title: str = hackathon.get("title", hackathon_id)
        status: str = hackathon.get("status", "draft")
        status_label = _STATUS_LABELS.get(status, status.capitalize())

        # Build the status line.
        if status == "open":
            status_line = f":large_green_circle: *{status_label}* — Registrations open!"
        elif status == "closed":
            status_line = f":red_circle: *{status_label}*"
        else:
            status_line = f":white_circle: *{status_label}*"

        # Check user registration and total count.
        try:
            registration = await get_registration(hackathon_id, user_id)
            total = await count_registrations(hackathon_id)
        except Exception:
            logger.exception("Failed to fetch registration data for hackathon '%s'.", hackathon_id)
            registration = None
            total = 0

        # Registration status for this user.
        if registration is not None:
            site_id = registration.get("site_id")
            location = f"site: {site_id}" if site_id else "online"
            reg_line = f":white_check_mark: You're registered ({location})"
        elif status == "open":
            reg_line = "Not registered — use `/nf-core-bot hackathon register` to sign up!"
        else:
            reg_line = ""

        # Assemble the section text.
        lines = [f"*{title}*", status_line, f"{total} registered"]
        if reg_line:
            lines.append(reg_line)

        blocks.append(
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": "\n".join(lines)},
            }
        )
        blocks.append({"type": "divider"})

    # Remove trailing divider.
    if blocks and blocks[-1].get("type") == "divider":
        blocks.pop()

    await respond(blocks=blocks, response_type="ephemeral")
