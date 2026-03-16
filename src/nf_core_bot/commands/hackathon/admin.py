"""Admin-only hackathon commands (core-team only).

Subcommands:
    list, preview
    add-site, remove-site, list-sites
    add-organiser, remove-organiser
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Any

from nf_core_bot.db.sites import (
    add_organiser,
    add_site,
    list_organisers,
    list_sites,
    remove_organiser,
    remove_site,
)
from nf_core_bot.forms.loader import get_active_form, get_form_metadata, list_all_forms

if TYPE_CHECKING:
    from slack_bolt.context.ack.async_ack import AsyncAck as Ack
    from slack_bolt.context.respond.async_respond import AsyncRespond as Respond
    from slack_sdk.web.async_client import AsyncWebClient

logger = logging.getLogger(__name__)

# Regex to extract a Slack user ID from a mention like <@U01ABCDEF> or <@U01ABCDEF|name>
_MENTION_RE = re.compile(r"<@(U[A-Z0-9]+)(?:\|[^>]*)?>")

# Status emoji mapping for nicer Slack output
_STATUS_EMOJI: dict[str, str] = {
    "draft": ":pencil2:",
    "open": ":green_circle:",
    "closed": ":red_circle:",
    "archived": ":file_cabinet:",
}

_NO_ACTIVE_MSG = "No active hackathon. Please specify a hackathon ID."


def _resolve_hackathon_id(args: list[str]) -> tuple[str | None, list[str]]:
    """Resolve the hackathon ID from the first element of *args*.

    If the first token is a known hackathon (via :func:`get_form_metadata`),
    it is consumed and the remaining args are returned.  Otherwise, the
    active hackathon is used and *args* is returned unchanged.

    Returns ``(hackathon_id, remaining_args)``.  *hackathon_id* is ``None``
    when no ID could be resolved (caller should emit :data:`_NO_ACTIVE_MSG`).
    """
    if args and get_form_metadata(args[0]) is not None:
        # First token is a recognised hackathon ID — consume it.
        return args[0], args[1:]

    # First token is not a hackathon ID (or args is empty) — fall back.
    active = get_active_form()
    if active:
        return active["hackathon_id"], args
    return None, args


# ── Hackathon listing & preview ─────────────────────────────────────


async def handle_admin_list(ack: Ack, respond: Respond) -> None:
    """List all hackathons (from YAML form files).

    Usage: ``/nf-core-bot hackathon admin list``
    """
    await ack()

    hackathons = list_all_forms()
    if not hackathons:
        await respond(
            text="No hackathon forms found.",
            response_type="ephemeral",
        )
        return

    lines: list[str] = ["*Hackathons:*\n"]
    for h in hackathons:
        hid = h.get("hackathon_id", "?")
        title = h.get("title", "Untitled")
        status = h.get("status", "unknown")
        emoji = _STATUS_EMOJI.get(status, ":grey_question:")
        date_start = h.get("date_start", "?")
        date_end = h.get("date_end", "?")
        url = h.get("url", "")
        lines.append(f"{emoji} *{title}* (`{hid}`)")
        lines.append(f"{date_start} — {date_end}  ·  {status}  ·  {url}")

    await respond(text="\n".join(lines), response_type="ephemeral")


async def handle_admin_preview(
    ack: Ack, respond: Respond, client: AsyncWebClient, body: dict[str, str], args: list[str]
) -> None:
    """Preview the registration form for a hackathon.

    Usage: ``/nf-core-bot hackathon admin preview [hackathon-id]``

    Defaults to the active hackathon when *hackathon-id* is omitted.
    """
    await ack()

    hackathon_id, _ = _resolve_hackathon_id(args)
    if hackathon_id is None:
        await respond(
            text=f"Usage: `/nf-core-bot hackathon admin preview [hackathon-id]`\n{_NO_ACTIVE_MSG}",
            response_type="ephemeral",
        )
        return

    # Check form exists
    metadata = get_form_metadata(hackathon_id)
    if not metadata:
        await respond(
            text=f"No form YAML found for hackathon `{hackathon_id}`.",
            response_type="ephemeral",
        )
        return

    # Open registration modal in preview mode
    from nf_core_bot.forms.handler import open_registration_modal

    trigger_id = body.get("trigger_id", "")
    user_id = body.get("user_id", "")
    try:
        await open_registration_modal(client, trigger_id, hackathon_id, user_id, preview=True)
    except Exception:
        logger.exception("Failed to open preview modal")
        await respond(text="Failed to open preview modal.", response_type="ephemeral")


# ── Site management ──────────────────────────────────────────────────


async def handle_admin_add_site(
    ack: Ack, respond: Respond, client: AsyncWebClient, body: dict[str, str], args: list[str]
) -> None:
    """Open a modal form to add a site to a hackathon.

    Usage: ``/nf-core-bot hackathon admin add-site``

    The modal includes a hackathon dropdown so no arguments are needed.
    """
    await ack()

    all_forms = list_all_forms()
    if not all_forms:
        await respond(text="No hackathon forms found.", response_type="ephemeral")
        return

    trigger_id = body.get("trigger_id", "")
    active_form = get_active_form()
    active_id = active_form["hackathon_id"] if active_form else None
    view = _build_add_site_modal(all_forms, active_id)

    try:
        await client.views_open(trigger_id=trigger_id, view=view)
    except Exception:
        logger.exception("Failed to open add-site modal")
        await respond(text="Failed to open add-site modal.", response_type="ephemeral")


def _build_add_site_modal(forms: list[dict[str, Any]], active_hackathon_id: str | None = None) -> dict[str, Any]:
    """Build the Block Kit modal view for adding a site."""
    hackathon_options = [
        {
            "text": {"type": "plain_text", "text": f"{f['title']} ({f['hackathon_id']})"},
            "value": f["hackathon_id"],
        }
        for f in forms
    ]

    hackathon_block: dict[str, Any] = {
        "type": "input",
        "block_id": "hackathon",
        "label": {"type": "plain_text", "text": "Hackathon"},
        "element": {
            "type": "static_select",
            "action_id": "hackathon",
            "options": hackathon_options,
        },
    }
    # Pre-select the active hackathon if there is one.
    if active_hackathon_id:
        for opt in hackathon_options:
            if opt["value"] == active_hackathon_id:
                hackathon_block["element"]["initial_option"] = opt
                break

    return {
        "type": "modal",
        "callback_id": "admin_add_site",
        "title": {"type": "plain_text", "text": "Add Hackathon Site"},
        "submit": {"type": "plain_text", "text": "Add Site"},
        "close": {"type": "plain_text", "text": "Cancel"},
        "blocks": [
            hackathon_block,
            {
                "type": "input",
                "block_id": "site_id",
                "label": {"type": "plain_text", "text": "Site ID"},
                "hint": {
                    "type": "plain_text",
                    "text": "Short lowercase identifier, e.g. 'stockholm-uni'. No spaces.",
                },
                "element": {
                    "type": "plain_text_input",
                    "action_id": "site_id",
                    "placeholder": {"type": "plain_text", "text": "e.g. stockholm-uni"},
                },
            },
            {
                "type": "input",
                "block_id": "name",
                "label": {"type": "plain_text", "text": "Site Name"},
                "hint": {
                    "type": "plain_text",
                    "text": "Full display name shown in the registration form.",
                },
                "element": {
                    "type": "plain_text_input",
                    "action_id": "name",
                    "placeholder": {"type": "plain_text", "text": "e.g. Stockholm University"},
                },
            },
            {
                "type": "input",
                "block_id": "city",
                "label": {"type": "plain_text", "text": "City"},
                "element": {
                    "type": "plain_text_input",
                    "action_id": "city",
                    "placeholder": {"type": "plain_text", "text": "e.g. Stockholm"},
                },
            },
            {
                "type": "input",
                "block_id": "country",
                "label": {"type": "plain_text", "text": "Country"},
                "element": {
                    "type": "external_select",
                    "action_id": "country",
                    "placeholder": {"type": "plain_text", "text": "Start typing to search..."},
                    "min_query_length": 1,
                },
            },
        ],
    }


async def handle_admin_add_site_submission(ack: Any, body: dict[str, Any], client: AsyncWebClient) -> None:
    """Handle the add-site modal submission."""
    values = body["view"]["state"]["values"]
    user_id: str = body["user"]["id"]

    hackathon_opt = values["hackathon"]["hackathon"].get("selected_option")
    hackathon_id = hackathon_opt["value"] if hackathon_opt else ""
    site_id = values["site_id"]["site_id"]["value"].strip().lower()
    name = values["name"]["name"]["value"].strip()
    city = values["city"]["city"]["value"].strip()
    country_opt = values["country"]["country"].get("selected_option")
    country = country_opt["value"] if country_opt else ""

    # Validate site_id: lowercase alphanumeric + hyphens only.
    if not re.match(r"^[a-z0-9][a-z0-9-]*$", site_id):
        await ack(
            response_action="errors",
            errors={"site_id": "Site ID must be lowercase letters, numbers, and hyphens only."},
        )
        return

    await ack()

    try:
        await add_site(hackathon_id, site_id, name, city, country)
    except ValueError:
        await client.chat_postMessage(
            channel=user_id,
            text=f":warning: Site `{site_id}` already exists in hackathon `{hackathon_id}`.",
        )
        return

    logger.info("Admin added site '%s' to hackathon '%s' via modal.", site_id, hackathon_id)
    await client.chat_postMessage(
        channel=user_id,
        text=f":white_check_mark: Site `{site_id}` added to hackathon `{hackathon_id}`.\n"
        f"• *Name:* {name}\n"
        f"• *City:* {city}\n"
        f"• *Country:* {country}",
    )


async def handle_admin_remove_site(ack: Ack, respond: Respond, args: list[str]) -> None:
    """Remove a site from a hackathon.

    Usage: ``/nf-core-bot hackathon admin remove-site [hackathon-id] <site-id>``

    Defaults to the active hackathon when *hackathon-id* is omitted.
    """
    await ack()

    hackathon_id, remaining = _resolve_hackathon_id(args)
    if hackathon_id is None:
        await respond(
            text=f"Usage: `/nf-core-bot hackathon admin remove-site [hackathon-id] <site-id>`\n{_NO_ACTIVE_MSG}",
            response_type="ephemeral",
        )
        return

    if not remaining:
        await respond(
            text="Usage: `/nf-core-bot hackathon admin remove-site [hackathon-id] <site-id>`\n"
            "Defaults to the active hackathon if omitted.",
            response_type="ephemeral",
        )
        return

    site_id = remaining[0]

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

    Usage: ``/nf-core-bot hackathon admin list-sites [hackathon-id]``

    Defaults to the active hackathon when *hackathon-id* is omitted.
    """
    await ack()

    hackathon_id, _ = _resolve_hackathon_id(args)
    if hackathon_id is None:
        await respond(
            text=f"Usage: `/nf-core-bot hackathon admin list-sites [hackathon-id]`\n{_NO_ACTIVE_MSG}",
            response_type="ephemeral",
        )
        return

    # Verify the hackathon exists.
    hackathon = get_form_metadata(hackathon_id)
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

    Usage: ``/nf-core-bot hackathon admin add-organiser [hackathon-id] <site-id> <@user>``

    Defaults to the active hackathon when *hackathon-id* is omitted.
    """
    await ack()

    hackathon_id, remaining = _resolve_hackathon_id(args)
    if hackathon_id is None:
        await respond(
            text="Usage: `/nf-core-bot hackathon admin add-organiser [hackathon-id] <site-id> <@user>`\n"
            f"{_NO_ACTIVE_MSG}",
            response_type="ephemeral",
        )
        return

    if len(remaining) < 2:
        await respond(
            text="Usage: `/nf-core-bot hackathon admin add-organiser [hackathon-id] <site-id> <@user>`\n"
            "Defaults to the active hackathon if omitted.",
            response_type="ephemeral",
        )
        return

    site_id = remaining[0]
    user_id = _parse_user_mention(remaining[1])

    if user_id is None:
        await respond(
            text="Could not parse user mention. Please use a Slack @mention (e.g. `@username`).",
            response_type="ephemeral",
        )
        return

    # Verify the hackathon and site exist.
    hackathon = get_form_metadata(hackathon_id)
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

    Usage: ``/nf-core-bot hackathon admin remove-organiser [hackathon-id] <site-id> <@user>``

    Defaults to the active hackathon when *hackathon-id* is omitted.
    """
    await ack()

    hackathon_id, remaining = _resolve_hackathon_id(args)
    if hackathon_id is None:
        await respond(
            text="Usage: `/nf-core-bot hackathon admin remove-organiser [hackathon-id] <site-id> <@user>`\n"
            f"{_NO_ACTIVE_MSG}",
            response_type="ephemeral",
        )
        return

    if len(remaining) < 2:
        await respond(
            text="Usage: `/nf-core-bot hackathon admin remove-organiser [hackathon-id] <site-id> <@user>`\n"
            "Defaults to the active hackathon if omitted.",
            response_type="ephemeral",
        )
        return

    site_id = remaining[0]
    user_id = _parse_user_mention(remaining[1])

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
