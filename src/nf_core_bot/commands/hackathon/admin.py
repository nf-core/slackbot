"""Admin-only hackathon commands (core-team only).

Subcommands:
    list, preview
    add-site, edit-site

Also contains the ``sites`` and ``export`` handlers, which are
accessible to organisers / all users and routed directly by the
hackathon router (not via the admin dispatch).
"""

from __future__ import annotations

import contextlib
import csv
import io
import json as _json
import logging
import re
from typing import TYPE_CHECKING, Any

from nf_core_bot.db.registrations import (
    count_registrations,
    count_registrations_by_site,
    list_registrations,
)
from nf_core_bot.db.sites import (
    add_organiser,
    add_site,
    get_site,
    list_organisers,
    list_sites,
    remove_organiser,
    remove_site,
    update_site,
)
from nf_core_bot.forms.loader import get_active_form, get_form_metadata, list_all_forms
from nf_core_bot.permissions.checks import is_core_team, is_organiser_any_site

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

    Usage: ``/hackathon admin list``
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

    Usage: ``/hackathon admin preview [hackathon-id]``

    Defaults to the active hackathon when *hackathon-id* is omitted.
    """
    await ack()

    hackathon_id, _ = _resolve_hackathon_id(args)
    if hackathon_id is None:
        await respond(
            text=f"Usage: `/hackathon admin preview [hackathon-id]`\n{_NO_ACTIVE_MSG}",
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
    """Open a modal form to add a new site.

    Usage: ``/hackathon admin add-site``
    """
    await ack()

    all_forms = list_all_forms()
    if not all_forms:
        await respond(text="No hackathon forms found.", response_type="ephemeral")
        return

    trigger_id = body.get("trigger_id", "")
    active_form = get_active_form()
    active_id = active_form["hackathon_id"] if active_form else None
    view = _build_site_modal(all_forms, active_hackathon_id=active_id)

    try:
        await client.views_open(trigger_id=trigger_id, view=view)
    except Exception:
        logger.exception("Failed to open add-site modal")
        await respond(text="Failed to open add-site modal.", response_type="ephemeral")


async def handle_admin_edit_site(
    ack: Ack, respond: Respond, client: AsyncWebClient, body: dict[str, str], args: list[str]
) -> None:
    """Open a two-step modal to pick and edit a site.

    Step 1: pick hackathon + site from dropdowns.
    Step 2: edit site details, organisers, or delete.

    Usage: ``/hackathon admin edit-site``
    """
    await ack()

    all_forms = list_all_forms()
    if not all_forms:
        await respond(text="No hackathon forms found.", response_type="ephemeral")
        return

    active_form = get_active_form()
    active_id = active_form["hackathon_id"] if active_form else None

    # Pre-load sites for the active hackathon so the dropdown isn't empty.
    sites: list[dict[str, Any]] = []
    if active_id:
        sites = await list_sites(active_id)

    if not sites:
        await respond(
            text="No sites found. Use `/hackathon admin add-site` first.",
            response_type="ephemeral",
        )
        return

    trigger_id = body.get("trigger_id", "")
    view = _build_edit_site_picker(all_forms, sites, active_hackathon_id=active_id)

    try:
        await client.views_open(trigger_id=trigger_id, view=view)
    except Exception:
        logger.exception("Failed to open edit-site picker modal")
        await respond(text="Failed to open edit-site picker.", response_type="ephemeral")


def _build_edit_site_picker(
    forms: list[dict[str, Any]],
    sites: list[dict[str, Any]],
    active_hackathon_id: str | None = None,
) -> dict[str, Any]:
    """Build step-1 modal: pick a hackathon and site to edit."""
    # Hackathon dropdown.
    hackathon_options = [
        {
            "text": {"type": "plain_text", "text": f"{f['title']} ({f['hackathon_id']})"},
            "value": f["hackathon_id"],
        }
        for f in forms
    ]
    hackathon_element: dict[str, Any] = {
        "type": "static_select",
        "action_id": "hackathon",
        "options": hackathon_options,
    }
    if active_hackathon_id:
        for opt in hackathon_options:
            if opt["value"] == active_hackathon_id:
                hackathon_element["initial_option"] = opt
                break

    # Site dropdown.
    site_options = [
        {
            "text": {"type": "plain_text", "text": f"{s.get('name', s.get('site_id', '?'))} ({s.get('city', '')})"},
            "value": s.get("site_id", ""),
        }
        for s in sorted(sites, key=lambda s: s.get("name", ""))
    ]
    site_element: dict[str, Any] = {
        "type": "static_select",
        "action_id": "site",
        "options": site_options,
        "placeholder": {"type": "plain_text", "text": "Select a site to edit"},
    }

    return {
        "type": "modal",
        "callback_id": "admin_edit_site_picker",
        "title": {"type": "plain_text", "text": "Edit Site"},
        "submit": {"type": "plain_text", "text": "Next"},
        "close": {"type": "plain_text", "text": "Cancel"},
        "blocks": [
            {
                "type": "input",
                "block_id": "hackathon",
                "label": {"type": "plain_text", "text": "Hackathon"},
                "element": hackathon_element,
            },
            {
                "type": "input",
                "block_id": "site",
                "label": {"type": "plain_text", "text": "Site"},
                "element": site_element,
            },
        ],
    }


async def handle_admin_edit_site_picker(ack: Any, body: dict[str, Any], client: AsyncWebClient) -> None:
    """Handle step-1 submission: load site data and show the edit form."""
    values = body["view"]["state"]["values"]
    hackathon_opt = values["hackathon"]["hackathon"].get("selected_option")
    hackathon_id = hackathon_opt["value"] if hackathon_opt else ""
    site_opt = values["site"]["site"].get("selected_option")
    site_id = site_opt["value"] if site_opt else ""

    site = await get_site(hackathon_id, site_id)
    if site is None:
        await ack(
            response_action="errors",
            errors={"site": f"Site '{site_id}' not found."},
        )
        return

    all_forms = list_all_forms()
    organisers = await list_organisers(hackathon_id, site_id)
    organiser_ids = [o.get("user_id", "") for o in organisers]

    view = _build_site_modal(
        all_forms,
        active_hackathon_id=hackathon_id,
        existing_site=site,
        organiser_ids=organiser_ids,
    )

    await ack(response_action="update", view=view)


def _build_site_modal(
    forms: list[dict[str, Any]],
    active_hackathon_id: str | None = None,
    existing_site: dict[str, Any] | None = None,
    organiser_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Build the Block Kit modal view for adding or editing a site."""
    editing = existing_site is not None
    site = existing_site or {}  # Narrowed copy for safe attribute access.

    # ── Private metadata to carry edit context through submission ────
    meta = {}
    if editing:
        meta["edit_site_id"] = site["site_id"]
        meta["hackathon_id"] = active_hackathon_id or ""

    # ── Hackathon dropdown ──────────────────────────────────────────
    hackathon_options = [
        {
            "text": {"type": "plain_text", "text": f"{f['title']} ({f['hackathon_id']})"},
            "value": f["hackathon_id"],
        }
        for f in forms
    ]
    hackathon_element: dict[str, Any] = {
        "type": "static_select",
        "action_id": "hackathon",
        "options": hackathon_options,
    }
    if active_hackathon_id:
        for opt in hackathon_options:
            if opt["value"] == active_hackathon_id:
                hackathon_element["initial_option"] = opt
                break

    hackathon_block: dict[str, Any] = {
        "type": "input",
        "block_id": "hackathon",
        "label": {"type": "plain_text", "text": "Hackathon"},
        "element": hackathon_element,
    }

    # ── Site ID ─────────────────────────────────────────────────────
    site_id_element: dict[str, Any] = {
        "type": "plain_text_input",
        "action_id": "site_id",
        "placeholder": {"type": "plain_text", "text": "e.g. stockholm-uni"},
    }
    if editing:
        site_id_element["initial_value"] = site["site_id"]

    site_id_block: dict[str, Any] = {
        "type": "input",
        "block_id": "site_id",
        "label": {"type": "plain_text", "text": "Site ID"},
        "hint": {
            "type": "plain_text",
            "text": "Short lowercase identifier, e.g. 'stockholm-uni'. No spaces.",
        },
        "element": site_id_element,
    }

    # ── Name ────────────────────────────────────────────────────────
    name_element: dict[str, Any] = {
        "type": "plain_text_input",
        "action_id": "name",
        "placeholder": {"type": "plain_text", "text": "e.g. Stockholm University"},
    }
    if editing:
        name_element["initial_value"] = site.get("name", "")

    name_block: dict[str, Any] = {
        "type": "input",
        "block_id": "name",
        "label": {"type": "plain_text", "text": "Site Name"},
        "hint": {
            "type": "plain_text",
            "text": "Full display name shown in the registration form.",
        },
        "element": name_element,
    }

    # ── City ────────────────────────────────────────────────────────
    city_element: dict[str, Any] = {
        "type": "plain_text_input",
        "action_id": "city",
        "placeholder": {"type": "plain_text", "text": "e.g. Stockholm"},
    }
    if editing:
        city_element["initial_value"] = site.get("city", "")

    city_block: dict[str, Any] = {
        "type": "input",
        "block_id": "city",
        "label": {"type": "plain_text", "text": "City"},
        "element": city_element,
    }

    # ── Country (type-ahead) ────────────────────────────────────────
    country_element: dict[str, Any] = {
        "type": "external_select",
        "action_id": "country",
        "placeholder": {"type": "plain_text", "text": "Start typing to search..."},
        "min_query_length": 1,
    }
    if editing and site.get("country"):
        from nf_core_bot.forms.loader import COUNTRIES

        country_val = site["country"]
        country_label = country_val
        for c in COUNTRIES:
            if c["value"] == country_val:
                country_label = c["label"]
                break
        country_element["initial_option"] = {
            "text": {"type": "plain_text", "text": country_label},
            "value": country_val,
        }

    country_block: dict[str, Any] = {
        "type": "input",
        "block_id": "country",
        "label": {"type": "plain_text", "text": "Country"},
        "element": country_element,
    }

    # ── Organisers (multi-user select) ──────────────────────────────
    organisers_element: dict[str, Any] = {
        "type": "multi_users_select",
        "action_id": "organisers",
        "placeholder": {"type": "plain_text", "text": "Select site organisers"},
    }
    if organiser_ids:
        organisers_element["initial_users"] = organiser_ids

    organisers_block: dict[str, Any] = {
        "type": "input",
        "block_id": "organisers",
        "label": {"type": "plain_text", "text": "Organisers"},
        "element": organisers_element,
        "optional": True,
    }

    # ── Assemble blocks ─────────────────────────────────────────────
    blocks: list[dict[str, Any]] = [
        hackathon_block,
        site_id_block,
        name_block,
        city_block,
        country_block,
        organisers_block,
    ]

    # In edit mode, add a delete button at the bottom.
    if editing:
        blocks.append({"type": "divider"})
        blocks.append(
            {
                "type": "actions",
                "block_id": "delete_site_actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Delete this site"},
                        "style": "danger",
                        "action_id": "admin_delete_site",
                        "confirm": {
                            "title": {"type": "plain_text", "text": "Delete site?"},
                            "text": {
                                "type": "mrkdwn",
                                "text": f"Are you sure you want to delete site"
                                f" `{site['site_id']}`? This cannot be undone.",
                            },
                            "confirm": {"type": "plain_text", "text": "Delete"},
                            "deny": {"type": "plain_text", "text": "Cancel"},
                            "style": "danger",
                        },
                    },
                ],
            }
        )

    return {
        "type": "modal",
        "callback_id": "admin_site",
        "private_metadata": _json.dumps(meta),
        "title": {"type": "plain_text", "text": "Edit Site" if editing else "Add Site"},
        "submit": {"type": "plain_text", "text": "Save"},
        "close": {"type": "plain_text", "text": "Cancel"},
        "blocks": blocks,
    }


async def handle_admin_site_submission(ack: Any, body: dict[str, Any], client: AsyncWebClient) -> None:
    """Handle the site modal submission (both add and edit)."""
    values = body["view"]["state"]["values"]
    user_id: str = body["user"]["id"]
    meta = _json.loads(body["view"].get("private_metadata") or "{}")
    editing = "edit_site_id" in meta

    hackathon_opt = values["hackathon"]["hackathon"].get("selected_option")
    hackathon_id = hackathon_opt["value"] if hackathon_opt else ""
    site_id = values["site_id"]["site_id"]["value"].strip().lower()
    name = values["name"]["name"]["value"].strip()
    city = values["city"]["city"]["value"].strip()
    country_opt = values["country"]["country"].get("selected_option")
    country = country_opt["value"] if country_opt else ""
    new_organiser_ids: list[str] = values["organisers"]["organisers"].get("selected_users") or []

    # Validate site_id.
    if not re.match(r"^[a-z0-9][a-z0-9-]*$", site_id):
        await ack(
            response_action="errors",
            errors={"site_id": "Site ID must be lowercase letters, numbers, and hyphens only."},
        )
        return

    await ack()

    # ── Create or update the site ───────────────────────────────────
    if editing:
        try:
            await update_site(hackathon_id, site_id, name, city, country)
        except ValueError:
            await client.chat_postMessage(
                channel=user_id,
                text=f":warning: Site `{site_id}` not found in hackathon `{hackathon_id}`.",
            )
            return
    else:
        try:
            await add_site(hackathon_id, site_id, name, city, country)
        except ValueError:
            await client.chat_postMessage(
                channel=user_id,
                text=f":warning: Site `{site_id}` already exists in hackathon `{hackathon_id}`.",
            )
            return

    # ── Sync organisers (add new, remove old) ───────────────────────
    existing_organisers = await list_organisers(hackathon_id, site_id)
    existing_ids = {o.get("user_id", "") for o in existing_organisers}
    new_ids = set(new_organiser_ids)

    for uid in new_ids - existing_ids:
        with contextlib.suppress(ValueError):
            await add_organiser(hackathon_id, site_id, uid)

    for uid in existing_ids - new_ids:
        with contextlib.suppress(ValueError):
            await remove_organiser(hackathon_id, site_id, uid)

    # ── Confirmation DM ─────────────────────────────────────────────
    action = "updated" if editing else "added"
    org_mentions = ", ".join(f"<@{uid}>" for uid in new_organiser_ids) if new_organiser_ids else "_(none)_"
    logger.info("Admin %s site '%s' in hackathon '%s' via modal.", action, site_id, hackathon_id)
    await client.chat_postMessage(
        channel=user_id,
        text=f":white_check_mark: Site `{site_id}` {action} in hackathon `{hackathon_id}`.\n"
        f"• *Name:* {name}\n"
        f"• *City:* {city}\n"
        f"• *Country:* {country}\n"
        f"• *Organisers:* {org_mentions}",
    )


async def handle_admin_delete_site(ack: Any, body: dict[str, Any], client: AsyncWebClient) -> None:
    """Handle the delete-site button click inside the edit-site modal."""
    await ack()

    meta = _json.loads(body.get("view", {}).get("private_metadata") or "{}")
    site_id = meta.get("edit_site_id", "")
    hackathon_id = meta.get("hackathon_id", "")
    user_id: str = body["user"]["id"]

    if not site_id or not hackathon_id:
        await client.chat_postMessage(
            channel=user_id,
            text=":warning: Could not determine which site to delete.",
        )
        return

    try:
        await remove_site(hackathon_id, site_id)
    except ValueError as exc:
        await client.chat_postMessage(channel=user_id, text=f":warning: {exc}")
        return

    logger.info("Admin deleted site '%s' from hackathon '%s'.", site_id, hackathon_id)

    # Close the modal by updating the view.
    try:
        await client.views_update(
            view_id=body["view"]["id"],
            view={
                "type": "modal",
                "title": {"type": "plain_text", "text": "Site Deleted"},
                "close": {"type": "plain_text", "text": "Close"},
                "blocks": [
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": f":wastebasket: Site `{site_id}` has been deleted from hackathon `{hackathon_id}`.",
                        },
                    },
                ],
            },
        )
    except Exception:
        logger.exception("Failed to update view after site deletion")

    await client.chat_postMessage(
        channel=user_id,
        text=f":wastebasket: Site `{site_id}` deleted from hackathon `{hackathon_id}`.",
    )


async def handle_list_sites(ack: Ack, respond: Respond, args: list[str]) -> None:
    """List all sites for a hackathon with organisers and registration counts.

    Usage: ``/hackathon sites [hackathon-id]``
    """
    await ack()

    hackathon_id, _ = _resolve_hackathon_id(args)
    if hackathon_id is None:
        await respond(
            text=f"Usage: `/hackathon sites [hackathon-id]`\n{_NO_ACTIVE_MSG}",
            response_type="ephemeral",
        )
        return

    hackathon = get_form_metadata(hackathon_id)
    if hackathon is None:
        await respond(text=f"Hackathon `{hackathon_id}` not found.", response_type="ephemeral")
        return

    sites = await list_sites(hackathon_id)
    if not sites:
        await respond(
            text=f"No sites found for hackathon `{hackathon_id}`.",
            response_type="ephemeral",
        )
        return

    total_regs = await count_registrations(hackathon_id)
    lines: list[str] = [f"*Sites for {hackathon['title']}* ({total_regs} total registrations)\n"]

    for site in sorted(sites, key=lambda s: s.get("name", "")):
        sid = site.get("site_id", "?")
        name = site.get("name", "Unnamed")
        city = site.get("city", "")
        country = site.get("country", "")
        location = f"{city}, {country}" if city and country else city or country

        organisers = await list_organisers(hackathon_id, sid)
        org_mentions = ", ".join(f"<@{o.get('user_id', '')}>" for o in organisers)

        reg_count = await count_registrations_by_site(hackathon_id, sid)

        lines.append(f"*{name}* — {location}")
        lines.append(f"  {reg_count} registered • Organisers: {org_mentions or '_(none)_'}")

    await respond(text="\n".join(lines), response_type="ephemeral")


# ── Registration export ─────────────────────────────────────────────


async def handle_export(
    ack: Ack, respond: Respond, client: AsyncWebClient, body: dict[str, str], args: list[str]
) -> None:
    """Export all registrations as a CSV file sent via DM.

    Core-team members get all registrations. Site organisers get
    registrations scoped to their site(s) only.

    Usage: ``/hackathon export [hackathon-id]``
    """
    await ack()

    user_id = body["user_id"]
    hackathon_id, _ = _resolve_hackathon_id(args)
    if hackathon_id is None:
        await respond(
            text=f"Usage: `/hackathon export [hackathon-id]`\n{_NO_ACTIVE_MSG}",
            response_type="ephemeral",
        )
        return

    hackathon = get_form_metadata(hackathon_id)
    if hackathon is None:
        await respond(text=f"Hackathon `{hackathon_id}` not found.", response_type="ephemeral")
        return

    # ── Permission check (core-team or any site organiser) ─────────
    core = await is_core_team(client, user_id)
    if not core:
        is_org = await is_organiser_any_site(user_id, hackathon_id)
        if not is_org:
            await respond(
                text="You don't have permission to export registrations.",
                response_type="ephemeral",
            )
            return

    # ── Fetch registrations ─────────────────────────────────────────
    registrations = await list_registrations(hackathon_id)

    if not registrations:
        await respond(
            text=f"No registrations found for hackathon `{hackathon_id}`.",
            response_type="ephemeral",
        )
        return

    # ── Build CSV ───────────────────────────────────────────────────
    # Collect all unique form_data keys across registrations.
    all_form_keys: list[str] = []
    seen_keys: set[str] = set()
    for reg in registrations:
        for key in reg.get("form_data", {}):
            if key not in seen_keys:
                all_form_keys.append(key)
                seen_keys.add(key)

    profile_cols = ["email", "slack_display_name", "github_username"]
    meta_cols = ["site_id", "registered_at"]
    header = profile_cols + all_form_keys + meta_cols

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(header)

    for reg in sorted(registrations, key=lambda r: r.get("registered_at", "")):
        profile = reg.get("profile_data", {})
        form = reg.get("form_data", {})
        row = (
            [profile.get(c, "") for c in profile_cols]
            + [_csv_value(form.get(k, "")) for k in all_form_keys]
            + [reg.get("site_id", ""), reg.get("registered_at", "")]
        )
        writer.writerow(row)

    csv_content = buf.getvalue()

    # ── Upload CSV as file via DM ───────────────────────────────────
    try:
        await client.files_upload_v2(
            channel=user_id,
            content=csv_content,
            filename=f"{hackathon_id}-registrations.csv",
            title=f"Registrations for {hackathon['title']}",
            initial_comment=f"Export of {len(registrations)} registration(s).",
        )
    except Exception:
        logger.exception("Failed to upload CSV export for user %s.", user_id)
        await respond(text="Failed to upload CSV. Please try again.", response_type="ephemeral")
        return

    await respond(
        text=f"Exported {len(registrations)} registration(s) — check your DMs.",
        response_type="ephemeral",
    )


def _csv_value(value: Any) -> str:
    """Convert a form value to a CSV-friendly string."""
    if isinstance(value, list):
        return ", ".join(str(v) for v in value)
    return str(value) if value else ""
