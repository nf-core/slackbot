"""Attendee list commands — visible to organisers and core-team."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from nf_core_bot.db.hackathons import get_active_hackathon, get_hackathon
from nf_core_bot.db.registrations import list_registrations, list_registrations_by_site
from nf_core_bot.db.sites import list_sites
from nf_core_bot.permissions.checks import is_core_team, is_organiser_any_site, is_site_organiser

if TYPE_CHECKING:
    from slack_bolt.context.ack.async_ack import AsyncAck
    from slack_bolt.context.respond.async_respond import AsyncRespond
    from slack_sdk.web.async_client import AsyncWebClient

logger = logging.getLogger(__name__)


# ── Helpers ─────────────────────────────────────────────────────────


def _site_name(sites: list[dict[str, Any]], site_id: str) -> str:
    """Look up a site's display name from the sites list."""
    for site in sites:
        if site.get("site_id") == site_id:
            name: str = site.get("name", site_id)
            return name
    return site_id


def _format_registration_line(reg: dict[str, Any], sites: list[dict[str, Any]]) -> str:
    """Format a single registration as a Slack mrkdwn line."""
    profile = reg.get("profile_data", {})
    display_name = profile.get("slack_display_name") or reg.get("user_id", "Unknown")
    site_id = reg.get("site_id")
    location = _site_name(sites, site_id) if site_id else "Online"
    registered_at = reg.get("registered_at", "")
    # Show just the date portion if we have an ISO timestamp.
    date_str = registered_at[:10] if len(registered_at) >= 10 else registered_at
    return f"• *{display_name}* — {location} (registered {date_str})"


async def _get_organiser_site_ids(user_id: str, hackathon_id: str, sites: list[dict[str, Any]]) -> list[str]:
    """Return the site IDs that *user_id* is an organiser for."""
    organiser_sites: list[str] = []
    for site in sites:
        site_id = site["site_id"]
        if await is_site_organiser(user_id, hackathon_id, site_id):
            organiser_sites.append(site_id)
    return organiser_sites


# ── Main handler ────────────────────────────────────────────────────


async def handle_attendees(
    ack: AsyncAck,
    respond: AsyncRespond,
    client: AsyncWebClient,
    body: dict[str, Any],
    rest: list[str],
) -> None:
    """List attendees, optionally filtered by hackathon ID.

    Usage: ``/nf-core-bot hackathon attendees [hackathon-id]``
    """
    await ack()

    user_id: str = body["user_id"]

    # ── Resolve hackathon ───────────────────────────────────────────
    if rest:
        hackathon_id = rest[0]
        try:
            hackathon = await get_hackathon(hackathon_id)
        except Exception:
            logger.exception("Failed to look up hackathon '%s'.", hackathon_id)
            await respond(
                text="Something went wrong looking up that hackathon. Please try again later.",
                response_type="ephemeral",
            )
            return

        if hackathon is None:
            await respond(
                text=f"Hackathon `{hackathon_id}` not found.",
                response_type="ephemeral",
            )
            return
    else:
        try:
            hackathon = await get_active_hackathon()
        except Exception:
            logger.exception("Failed to look up active hackathon.")
            await respond(
                text="Something went wrong looking up the active hackathon. Please try again later.",
                response_type="ephemeral",
            )
            return

        if hackathon is None:
            await respond(
                text="No hackathon is currently open. Specify a hackathon ID: `/nf-core-bot hackathon attendees <id>`",
                response_type="ephemeral",
            )
            return

    hackathon_id = hackathon["hackathon_id"]
    hackathon_title = hackathon.get("title", hackathon_id)

    # ── Permission check ────────────────────────────────────────────
    try:
        user_is_core_team = await is_core_team(client, user_id)
        user_is_organiser = await is_organiser_any_site(user_id, hackathon_id) if not user_is_core_team else False
    except Exception:
        logger.exception("Failed to check permissions for user '%s'.", user_id)
        await respond(
            text="Something went wrong checking your permissions. Please try again later.",
            response_type="ephemeral",
        )
        return

    if not user_is_core_team and not user_is_organiser:
        await respond(
            text=(
                "You don't have permission to view attendees. "
                "This command is available to core-team members and site organisers."
            ),
            response_type="ephemeral",
        )
        return

    # ── Load sites ──────────────────────────────────────────────────
    try:
        sites = await list_sites(hackathon_id)
    except Exception:
        logger.exception("Failed to load sites for hackathon '%s'.", hackathon_id)
        await respond(
            text="Something went wrong loading site data. Please try again later.",
            response_type="ephemeral",
        )
        return

    # ── Load registrations (scoped by role) ─────────────────────────
    if user_is_core_team:
        # Core-team sees everything.
        try:
            all_registrations = await list_registrations(hackathon_id)
        except Exception:
            logger.exception("Failed to load registrations for hackathon '%s'.", hackathon_id)
            await respond(
                text="Something went wrong loading registrations. Please try again later.",
                response_type="ephemeral",
            )
            return

        blocks = _build_full_summary(hackathon_title, all_registrations, sites)
    else:
        # Site organiser — only show their site(s).
        try:
            organiser_site_ids = await _get_organiser_site_ids(user_id, hackathon_id, sites)
        except Exception:
            logger.exception("Failed to determine organiser sites for user '%s'.", user_id)
            await respond(
                text="Something went wrong determining your organiser sites. Please try again later.",
                response_type="ephemeral",
            )
            return

        scoped_registrations: list[dict[str, Any]] = []
        try:
            for site_id in organiser_site_ids:
                site_regs = await list_registrations_by_site(hackathon_id, site_id)
                scoped_registrations.extend(site_regs)
        except Exception:
            logger.exception("Failed to load registrations for organiser sites.")
            await respond(
                text="Something went wrong loading registrations. Please try again later.",
                response_type="ephemeral",
            )
            return

        organiser_site_names = [_site_name(sites, sid) for sid in organiser_site_ids]
        blocks = _build_organiser_summary(
            hackathon_title,
            scoped_registrations,
            sites,
            organiser_site_names,
        )

    await respond(blocks=blocks, response_type="ephemeral")


# ── Formatting helpers ──────────────────────────────────────────────


def _build_full_summary(
    hackathon_title: str,
    all_registrations: list[dict[str, Any]],
    sites: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Build Slack Block Kit blocks for the full attendee summary (core-team view)."""
    total = len(all_registrations)

    # Count per site.
    site_counts: dict[str, int] = {}
    online_count = 0
    for reg in all_registrations:
        site_id = reg.get("site_id")
        if site_id:
            site_counts[site_id] = site_counts.get(site_id, 0) + 1
        else:
            online_count += 1

    # Header.
    blocks: list[dict[str, Any]] = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": f"Attendees — {hackathon_title}"},
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*Total registrations:* {total}"},
        },
    ]

    # Per-site breakdown.
    site_lines: list[str] = []
    for site in sites:
        sid = site["site_id"]
        name = site.get("name", sid)
        count = site_counts.get(sid, 0)
        site_lines.append(f"• *{name}*: {count}")
    site_lines.append(f"• *Online*: {online_count}")

    blocks.append(
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": "*Breakdown by site:*\n" + "\n".join(site_lines)},
        }
    )

    blocks.append({"type": "divider"})

    # Individual registrants.
    if all_registrations:
        reg_lines = [_format_registration_line(reg, sites) for reg in all_registrations]
        # Slack sections have a 3000-char limit — chunk if needed.
        _append_text_blocks(blocks, "*All registrants:*\n" + "\n".join(reg_lines))
    else:
        blocks.append(
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": "_No registrations yet._"},
            }
        )

    return blocks


def _build_organiser_summary(
    hackathon_title: str,
    registrations: list[dict[str, Any]],
    sites: list[dict[str, Any]],
    organiser_site_names: list[str],
) -> list[dict[str, Any]]:
    """Build Slack Block Kit blocks for a site-organiser-scoped attendee view."""
    total = len(registrations)
    site_label = ", ".join(organiser_site_names) if organiser_site_names else "your sites"

    blocks: list[dict[str, Any]] = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": f"Attendees — {hackathon_title}"},
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"Showing registrations for *{site_label}* ({total} total).",
            },
        },
        {"type": "divider"},
    ]

    if registrations:
        reg_lines = [_format_registration_line(reg, sites) for reg in registrations]
        _append_text_blocks(blocks, "\n".join(reg_lines))
    else:
        blocks.append(
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": "_No registrations for your site(s) yet._"},
            }
        )

    return blocks


def _append_text_blocks(blocks: list[dict[str, Any]], text: str, *, char_limit: int = 2900) -> None:
    """Append mrkdwn section blocks, splitting text if it exceeds *char_limit*."""
    while text:
        chunk = text[:char_limit]
        text = text[char_limit:]

        # Try to break at a newline to avoid cutting mid-line.
        if text and "\n" in chunk:
            last_nl = chunk.rfind("\n")
            text = chunk[last_nl + 1 :] + text
            chunk = chunk[: last_nl + 1]

        blocks.append(
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": chunk},
            }
        )
