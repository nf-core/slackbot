"""Admin-only hackathon commands (core-team only).

Subcommands:
    create, open, close, archive, list
    add-site, remove-site, list-sites
    add-organiser, remove-organiser
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

from nf_core_bot.db.hackathons import (
    create_hackathon,
    get_hackathon,
    list_hackathons,
    update_hackathon_status,
)
from nf_core_bot.db.sites import (
    add_organiser,
    add_site,
    list_organisers,
    list_sites,
    remove_organiser,
    remove_site,
)
from nf_core_bot.forms.loader import load_form_by_hackathon

if TYPE_CHECKING:
    from slack_bolt.context.ack.async_ack import AsyncAck as Ack
    from slack_bolt.context.respond.async_respond import AsyncRespond as Respond

logger = logging.getLogger(__name__)

# Regex to extract a Slack user ID from a mention like <@U01ABCDEF> or <@U01ABCDEF|name>
_MENTION_RE = re.compile(r"<@(U[A-Z0-9]+)(?:\|[^>]*)?>")

# Status emoji mapping for nicer Slack output
_STATUS_EMOJI: dict[str, str] = {
    "draft": ":pencil2:",
    "open": ":large_green_circle:",
    "closed": ":no_entry_sign:",
    "archived": ":file_cabinet:",
}


# ── Hackathon lifecycle ─────────────────────────────────────────────


async def handle_admin_create(ack: Ack, respond: Respond, args: list[str]) -> None:
    """Create a new hackathon.

    Usage: ``/nf-core-bot hackathon admin create <hackathon-id> <title…>``
    """
    await ack()

    if len(args) < 2:
        await respond(
            text="Usage: `/nf-core-bot hackathon admin create <hackathon-id> <title>`",
            response_type="ephemeral",
        )
        return

    hackathon_id = args[0]
    title = " ".join(args[1:])

    # Verify a matching form YAML exists before creating the DB record.
    try:
        form = load_form_by_hackathon(hackathon_id)
    except FileNotFoundError:
        await respond(
            text=f"No form YAML found for hackathon `{hackathon_id}`. "
            "Please add a YAML file to the `forms/` directory first.",
            response_type="ephemeral",
        )
        return

    yaml_filename = f"{hackathon_id}.yaml"

    try:
        await create_hackathon(hackathon_id, title, yaml_filename)
    except ValueError as exc:
        await respond(text=f"Error: {exc}", response_type="ephemeral")
        return

    logger.info("Admin created hackathon '%s' ('%s').", hackathon_id, title)
    await respond(
        text=f"Hackathon `{hackathon_id}` created with status *draft*.\n"
        f"• *Title:* {title}\n"
        f"• *Form:* `{yaml_filename}` ({len(form.steps)} steps)",
        response_type="ephemeral",
    )


async def handle_admin_open(ack: Ack, respond: Respond, args: list[str]) -> None:
    """Open a hackathon for registration.

    Usage: ``/nf-core-bot hackathon admin open <hackathon-id>``
    """
    await ack()

    if not args:
        await respond(
            text="Usage: `/nf-core-bot hackathon admin open <hackathon-id>`",
            response_type="ephemeral",
        )
        return

    hackathon_id = args[0]

    # Fetch current state so we can report the transition.
    hackathon = await get_hackathon(hackathon_id)
    if hackathon is None:
        await respond(
            text=f"Hackathon `{hackathon_id}` not found.",
            response_type="ephemeral",
        )
        return

    current_status = hackathon.get("status", "unknown")
    if current_status not in ("draft", "closed"):
        await respond(
            text=f"Cannot open hackathon `{hackathon_id}` — current status is *{current_status}*. "
            "Only `draft` or `closed` hackathons can be opened.",
            response_type="ephemeral",
        )
        return

    try:
        await update_hackathon_status(hackathon_id, "open")
    except ValueError as exc:
        await respond(text=f"Error: {exc}", response_type="ephemeral")
        return

    logger.info("Admin opened hackathon '%s' (was '%s').", hackathon_id, current_status)
    await respond(
        text=f"Hackathon `{hackathon_id}` is now *open* for registration (was *{current_status}*).",
        response_type="ephemeral",
    )


async def handle_admin_close(ack: Ack, respond: Respond, args: list[str]) -> None:
    """Close registration for a hackathon.

    Usage: ``/nf-core-bot hackathon admin close <hackathon-id>``
    """
    await ack()

    if not args:
        await respond(
            text="Usage: `/nf-core-bot hackathon admin close <hackathon-id>`",
            response_type="ephemeral",
        )
        return

    hackathon_id = args[0]

    hackathon = await get_hackathon(hackathon_id)
    if hackathon is None:
        await respond(
            text=f"Hackathon `{hackathon_id}` not found.",
            response_type="ephemeral",
        )
        return

    current_status = hackathon.get("status", "unknown")
    if current_status != "open":
        await respond(
            text=f"Cannot close hackathon `{hackathon_id}` — current status is *{current_status}*. "
            "Only `open` hackathons can be closed.",
            response_type="ephemeral",
        )
        return

    try:
        await update_hackathon_status(hackathon_id, "closed")
    except ValueError as exc:
        await respond(text=f"Error: {exc}", response_type="ephemeral")
        return

    logger.info("Admin closed hackathon '%s'.", hackathon_id)
    await respond(
        text=f"Hackathon `{hackathon_id}` is now *closed* (was *{current_status}*).",
        response_type="ephemeral",
    )


async def handle_admin_archive(ack: Ack, respond: Respond, args: list[str]) -> None:
    """Archive a hackathon.

    Usage: ``/nf-core-bot hackathon admin archive <hackathon-id>``
    """
    await ack()

    if not args:
        await respond(
            text="Usage: `/nf-core-bot hackathon admin archive <hackathon-id>`",
            response_type="ephemeral",
        )
        return

    hackathon_id = args[0]

    hackathon = await get_hackathon(hackathon_id)
    if hackathon is None:
        await respond(
            text=f"Hackathon `{hackathon_id}` not found.",
            response_type="ephemeral",
        )
        return

    try:
        await update_hackathon_status(hackathon_id, "archived")
    except ValueError as exc:
        await respond(text=f"Error: {exc}", response_type="ephemeral")
        return

    current_status = hackathon.get("status", "unknown")
    logger.info("Admin archived hackathon '%s' (was '%s').", hackathon_id, current_status)
    await respond(
        text=f"Hackathon `{hackathon_id}` is now *archived* (was *{current_status}*).",
        response_type="ephemeral",
    )


async def handle_admin_list(ack: Ack, respond: Respond) -> None:
    """List all hackathons.

    Usage: ``/nf-core-bot hackathon admin list``
    """
    await ack()

    hackathons = await list_hackathons()
    if not hackathons:
        await respond(
            text="No hackathons found. Create one with `/nf-core-bot hackathon admin create`.",
            response_type="ephemeral",
        )
        return

    # Sort by created_at descending (most recent first).
    hackathons.sort(key=lambda h: h.get("created_at", ""), reverse=True)

    lines: list[str] = ["*Hackathons:*\n"]
    for h in hackathons:
        hid = h.get("hackathon_id", "?")
        title = h.get("title", "Untitled")
        status = h.get("status", "unknown")
        emoji = _STATUS_EMOJI.get(status, ":grey_question:")
        lines.append(f"• {emoji} `{hid}` — {title} ({status})")

    await respond(text="\n".join(lines), response_type="ephemeral")


# ── Site management ──────────────────────────────────────────────────


async def handle_admin_add_site(ack: Ack, respond: Respond, args: list[str]) -> None:
    """Add a site to a hackathon.

    Usage: ``/nf-core-bot hackathon admin add-site <hackathon-id> <site-id> <name> | <city> | <country>``

    The first two tokens are the hackathon ID and site ID.  The remainder
    is pipe-delimited: ``name | city | country``.
    """
    await ack()

    if len(args) < 3:
        await respond(
            text="Usage: `/nf-core-bot hackathon admin add-site <hackathon-id> <site-id> <name> | <city> | <country>`",
            response_type="ephemeral",
        )
        return

    hackathon_id = args[0]
    site_id = args[1]

    # Rejoin remaining tokens and split on pipe to get name, city, country.
    remainder = " ".join(args[2:])
    parts = [p.strip() for p in remainder.split("|")]
    if len(parts) != 3 or not all(parts):
        await respond(
            text="Invalid site details. Expected pipe-delimited format: `<name> | <city> | <country>`\n"
            "Example: `/nf-core-bot hackathon admin add-site 2026-march stockholm-uni "
            "Stockholm University | Stockholm | Sweden`",
            response_type="ephemeral",
        )
        return

    name, city, country = parts

    # Verify the hackathon exists.
    hackathon = await get_hackathon(hackathon_id)
    if hackathon is None:
        await respond(
            text=f"Hackathon `{hackathon_id}` not found.",
            response_type="ephemeral",
        )
        return

    try:
        await add_site(hackathon_id, site_id, name, city, country)
    except ValueError as exc:
        await respond(text=f"Error: {exc}", response_type="ephemeral")
        return

    logger.info("Admin added site '%s' to hackathon '%s'.", site_id, hackathon_id)
    await respond(
        text=f"Site `{site_id}` added to hackathon `{hackathon_id}`.\n"
        f"• *Name:* {name}\n"
        f"• *City:* {city}\n"
        f"• *Country:* {country}",
        response_type="ephemeral",
    )


async def handle_admin_remove_site(ack: Ack, respond: Respond, args: list[str]) -> None:
    """Remove a site from a hackathon.

    Usage: ``/nf-core-bot hackathon admin remove-site <hackathon-id> <site-id>``
    """
    await ack()

    if len(args) < 2:
        await respond(
            text="Usage: `/nf-core-bot hackathon admin remove-site <hackathon-id> <site-id>`",
            response_type="ephemeral",
        )
        return

    hackathon_id = args[0]
    site_id = args[1]

    try:
        await remove_site(hackathon_id, site_id)
    except ValueError as exc:
        await respond(text=f"Error: {exc}", response_type="ephemeral")
        return

    logger.info("Admin removed site '%s' from hackathon '%s'.", site_id, hackathon_id)
    await respond(
        text=f"Site `{site_id}` removed from hackathon `{hackathon_id}`.",
        response_type="ephemeral",
    )


async def handle_admin_list_sites(ack: Ack, respond: Respond, args: list[str]) -> None:
    """List all sites for a hackathon.

    Usage: ``/nf-core-bot hackathon admin list-sites <hackathon-id>``
    """
    await ack()

    if not args:
        await respond(
            text="Usage: `/nf-core-bot hackathon admin list-sites <hackathon-id>`",
            response_type="ephemeral",
        )
        return

    hackathon_id = args[0]

    # Verify the hackathon exists.
    hackathon = await get_hackathon(hackathon_id)
    if hackathon is None:
        await respond(
            text=f"Hackathon `{hackathon_id}` not found.",
            response_type="ephemeral",
        )
        return

    sites = await list_sites(hackathon_id)
    if not sites:
        await respond(
            text=f"No sites found for hackathon `{hackathon_id}`.",
            response_type="ephemeral",
        )
        return

    lines: list[str] = [f"*Sites for `{hackathon_id}`:*\n"]
    for site in sorted(sites, key=lambda s: s.get("name", "")):
        sid = site.get("site_id", "?")
        name = site.get("name", "Unnamed")
        city = site.get("city", "")
        country = site.get("country", "")

        # Fetch organiser count for each site.
        organisers = await list_organisers(hackathon_id, sid)
        org_count = len(organisers)
        org_label = f"{org_count} organiser{'s' if org_count != 1 else ''}"

        lines.append(f"• `{sid}` — *{name}* ({city}, {country}) — {org_label}")

    await respond(text="\n".join(lines), response_type="ephemeral")


# ── Organiser management ────────────────────────────────────────────


def _parse_user_mention(text: str) -> str | None:
    """Extract a Slack user ID from a mention string like ``<@U01ABCDEF>``."""
    match = _MENTION_RE.search(text)
    return match.group(1) if match else None


async def handle_admin_add_organiser(ack: Ack, respond: Respond, args: list[str]) -> None:
    """Add an organiser to a site.

    Usage: ``/nf-core-bot hackathon admin add-organiser <hackathon-id> <site-id> <@user>``
    """
    await ack()

    if len(args) < 3:
        await respond(
            text="Usage: `/nf-core-bot hackathon admin add-organiser <hackathon-id> <site-id> <@user>`",
            response_type="ephemeral",
        )
        return

    hackathon_id = args[0]
    site_id = args[1]
    user_id = _parse_user_mention(args[2])

    if user_id is None:
        await respond(
            text="Could not parse user mention. Please use a Slack @mention (e.g. `@username`).",
            response_type="ephemeral",
        )
        return

    # Verify the hackathon and site exist.
    hackathon = await get_hackathon(hackathon_id)
    if hackathon is None:
        await respond(
            text=f"Hackathon `{hackathon_id}` not found.",
            response_type="ephemeral",
        )
        return

    from nf_core_bot.db.sites import get_site

    site = await get_site(hackathon_id, site_id)
    if site is None:
        await respond(
            text=f"Site `{site_id}` not found in hackathon `{hackathon_id}`.",
            response_type="ephemeral",
        )
        return

    try:
        await add_organiser(hackathon_id, site_id, user_id)
    except ValueError as exc:
        await respond(text=f"Error: {exc}", response_type="ephemeral")
        return

    logger.info(
        "Admin added organiser '%s' to site '%s' (hackathon '%s').",
        user_id,
        site_id,
        hackathon_id,
    )
    await respond(
        text=f"<@{user_id}> added as organiser for site `{site_id}` in hackathon `{hackathon_id}`.",
        response_type="ephemeral",
    )


async def handle_admin_remove_organiser(ack: Ack, respond: Respond, args: list[str]) -> None:
    """Remove an organiser from a site.

    Usage: ``/nf-core-bot hackathon admin remove-organiser <hackathon-id> <site-id> <@user>``
    """
    await ack()

    if len(args) < 3:
        await respond(
            text="Usage: `/nf-core-bot hackathon admin remove-organiser <hackathon-id> <site-id> <@user>`",
            response_type="ephemeral",
        )
        return

    hackathon_id = args[0]
    site_id = args[1]
    user_id = _parse_user_mention(args[2])

    if user_id is None:
        await respond(
            text="Could not parse user mention. Please use a Slack @mention (e.g. `@username`).",
            response_type="ephemeral",
        )
        return

    try:
        await remove_organiser(hackathon_id, site_id, user_id)
    except ValueError as exc:
        await respond(text=f"Error: {exc}", response_type="ephemeral")
        return

    logger.info(
        "Admin removed organiser '%s' from site '%s' (hackathon '%s').",
        user_id,
        site_id,
        hackathon_id,
    )
    await respond(
        text=f"<@{user_id}> removed as organiser for site `{site_id}` in hackathon `{hackathon_id}`.",
        response_type="ephemeral",
    )
