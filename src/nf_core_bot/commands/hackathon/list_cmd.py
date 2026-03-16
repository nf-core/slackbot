"""List hackathons — a user-facing command showing all non-archived hackathons.

Usage: ``/nf-core-bot hackathon list``
"""

from __future__ import annotations

import datetime
import logging
from typing import TYPE_CHECKING, Any

from nf_core_bot.db.registrations import count_registrations, get_registration
from nf_core_bot.forms.loader import list_all_forms

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


def _format_date_range(start_iso: str, end_iso: str) -> str:
    """Format an ISO date range as a compact human-readable string.

    Examples: "11–13 Mar 2026", "28 Feb – 2 Mar 2026", "15 Dec 2025 – 3 Jan 2026".
    Returns an empty string if both dates are missing.
    """
    if not start_iso and not end_iso:
        return ""

    try:
        start = datetime.date.fromisoformat(start_iso) if start_iso else None
        end = datetime.date.fromisoformat(end_iso) if end_iso else None
    except ValueError:
        return start_iso if start_iso else end_iso

    if start and end:
        if start.year == end.year and start.month == end.month:
            # Same month: "11–13 Mar 2026"
            return f"{start.day}–{end.day} {end.strftime('%b %Y')}"
        if start.year == end.year:
            # Same year, different months: "28 Feb – 2 Mar 2026"
            return f"{start.day} {start.strftime('%b')} – {end.day} {end.strftime('%b %Y')}"
        # Different years: "15 Dec 2025 – 3 Jan 2026"
        return f"{start.day} {start.strftime('%b %Y')} – {end.day} {end.strftime('%b %Y')}"

    if start:
        return f"{start.day} {start.strftime('%b %Y')}"
    assert end is not None
    return f"{end.day} {end.strftime('%b %Y')}"


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
        hackathons = list_all_forms()
    except Exception:
        logger.exception("Failed to list hackathons.")
        await respond(
            text="Something went wrong loading hackathons. Please try again later.",
            response_type="ephemeral",
        )
        return

    # Filter out draft and archived hackathons — regular users see only open/closed.
    visible = [h for h in hackathons if h.get("status") not in ("draft", "archived")]

    if not visible:
        await respond(
            text="There are no hackathons to show right now.",
            response_type="ephemeral",
        )
        return

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

        # Build a human-readable date range.
        date_line = _format_date_range(hackathon.get("date_start", ""), hackathon.get("date_end", ""))

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
        lines = [f"*{title}*"]
        if date_line:
            lines.append(date_line)
        lines.append(status_line)
        lines.append(f"{total} registered")
        if reg_line:
            lines.append(reg_line)

        url = hackathon.get("url")
        if url:
            lines.append(f"<{url}|More info>")

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
