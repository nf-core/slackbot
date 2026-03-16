"""Handle modal submission callbacks and persist form data.

This module wires up the Slack ``view_submission`` callbacks for the
multi-step hackathon registration flow.  Each step's submission extracts
field values, merges them with answers accumulated from earlier steps
(carried in ``private_metadata``), determines the next applicable step,
and either advances the modal or finalises the registration.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import TYPE_CHECKING, Any

from nf_core_bot.checks.slack_profile import get_github_username
from nf_core_bot.db import registrations
from nf_core_bot.db import sites as sites_db
from nf_core_bot.forms.builder import build_modal_view
from nf_core_bot.forms.loader import COUNTRIES, get_applicable_steps, load_form_by_hackathon

if TYPE_CHECKING:
    from slack_sdk.web.async_client import AsyncWebClient

logger = logging.getLogger(__name__)


# ── Value extraction ────────────────────────────────────────────────


def _extract_values(state_values: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Extract user-submitted values from Slack's ``view.state.values``.

    Slack nests values as ``{block_id: {action_id: {type, value, ...}}}``.
    This function flattens that structure into ``{field_id: value}``.

    Handles:
    - ``plain_text_input`` → string value
    - ``static_select`` → selected option value string
    - ``checkboxes`` → list of selected option value strings
    """
    extracted: dict[str, Any] = {}

    for block_id, actions in state_values.items():
        for _action_id, payload in actions.items():
            action_type = payload.get("type")

            if action_type == "plain_text_input":
                extracted[block_id] = payload.get("value") or ""

            elif action_type in ("static_select", "external_select"):
                selected = payload.get("selected_option")
                extracted[block_id] = selected["value"] if selected else None

            elif action_type == "checkboxes":
                selected_options = payload.get("selected_options") or []
                extracted[block_id] = [opt["value"] for opt in selected_options]

            else:
                # Unknown element type — store raw value as fallback.
                logger.warning(
                    "Unknown action type '%s' for block '%s' — storing raw payload.",
                    action_type,
                    block_id,
                )
                extracted[block_id] = payload.get("value")

    return extracted


# ── External-select suggestions ─────────────────────────────────────


async def handle_country_suggestions(ack: Any, body: dict[str, Any]) -> None:
    """Respond to ``block_suggestion`` events for the country field.

    Filters the full COUNTRIES list based on the user's type-ahead query
    and returns up to 100 matching options.
    """
    query = (body.get("value") or "").lower()

    matches = [
        {"text": {"type": "plain_text", "text": c["label"]}, "value": c["value"]}
        for c in COUNTRIES
        if query in c["label"].lower()
    ]

    # Slack allows max 100 options in a suggestion response.
    await ack(options=matches[:100])


# ── Profile data helper ─────────────────────────────────────────────


async def _get_profile_data(client: AsyncWebClient, user_id: str) -> dict[str, str | None]:
    """Fetch auto-populated profile fields from the Slack API.

    Returns a dict with ``email``, ``slack_user_id``,
    ``slack_display_name``, and ``github_username``.
    """
    profile_data: dict[str, str | None] = {
        "slack_user_id": user_id,
        "email": None,
        "slack_display_name": None,
        "github_username": None,
    }

    try:
        # Fetch profile and GitHub username concurrently.
        profile_resp, github_username = await asyncio.gather(
            client.users_profile_get(user=user_id),
            get_github_username(client, user_id),
        )
        profile: dict[str, Any] = profile_resp.get("profile", {})
        profile_data["email"] = profile.get("email")
        profile_data["slack_display_name"] = profile.get("display_name") or profile.get("real_name")
        profile_data["github_username"] = github_username
    except Exception:
        logger.exception("Failed to fetch profile data for user %s — proceeding without it.", user_id)

    return profile_data


# ── Sites helper ────────────────────────────────────────────────────


async def _load_sites(hackathon_id: str) -> list[dict[str, str]]:
    """Load site records from DynamoDB for *hackathon_id*.

    Returns an empty list on failure so the modal can still be built.
    """
    try:
        return await sites_db.list_sites(hackathon_id)
    except Exception:
        logger.exception("Failed to load sites for hackathon '%s'.", hackathon_id)
        return []


# ── Channel join helper ─────────────────────────────────────────────


async def _join_hackathon_channel(
    client: AsyncWebClient,
    hackathon_id: str,
    user_id: str,
) -> None:
    """Invite the user to the hackathon Slack channel.

    Loads the ``channel_id`` from the form YAML definition.  Silently
    succeeds if the user is already in the channel.
    """
    try:
        form = load_form_by_hackathon(hackathon_id)
        channel_id = form.channel_id

        await client.conversations_invite(channel=channel_id, users=[user_id])
        logger.info("Invited user %s to channel %s for hackathon '%s'.", user_id, channel_id, hackathon_id)
    except Exception as exc:
        # Slack returns "already_in_channel" error which we can safely ignore.
        error = getattr(exc, "response", {})
        if isinstance(error, dict) and error.get("error") == "already_in_channel":
            return
        logger.warning(
            "Could not invite user %s to hackathon channel: %s",
            user_id,
            exc,
        )


# ── Step submission handler ─────────────────────────────────────────


async def handle_registration_step(
    ack: Any,
    body: dict[str, Any],
    client: AsyncWebClient,
    view: dict[str, Any],
) -> None:
    """Handle ``view_submission`` for a registration modal step.

    Workflow:
    1. Extract submitted values from ``view['state']['values']``.
    2. Merge with existing answers from ``private_metadata``.
    3. Determine the next applicable step.
    4. If more steps remain: ``ack`` with ``response_action: "update"``
       and the next modal view.
    5. If this is the final step: persist the registration and ``ack``
       with ``response_action: "clear"``.
    """
    # ── Parse metadata ──────────────────────────────────────────────
    metadata = json.loads(view.get("private_metadata", "{}"))
    hackathon_id: str = metadata.get("hackathon_id", "")
    current_step_index: int = metadata.get("step_index", 0)
    answers: dict[str, Any] = metadata.get("answers", {})
    preview: bool = metadata.get("preview", False)

    # ── Extract & merge new values ──────────────────────────────────
    state_values = view.get("state", {}).get("values", {})
    new_values = _extract_values(state_values)
    answers.update(new_values)

    user_id: str = body["user"]["id"]

    # ── Determine next step ─────────────────────────────────────────
    try:
        form = load_form_by_hackathon(hackathon_id)
    except FileNotFoundError:
        logger.error("Form definition not found for hackathon '%s'.", hackathon_id)
        await ack(response_action="errors", errors={"_": "Registration form not found."})
        return

    applicable_steps = get_applicable_steps(form, answers)
    next_step_index = current_step_index + 1

    # ── Advance or finalise ─────────────────────────────────────────
    if next_step_index < len(applicable_steps):
        # More steps — update the modal with the next step.
        sites = await _load_sites(hackathon_id)
        next_view = await build_modal_view(
            step=applicable_steps[next_step_index],
            step_index=next_step_index,
            total_steps=len(applicable_steps),
            hackathon_id=hackathon_id,
            answers=answers,
            sites=sites,
            preview=preview,
        )
        await ack(response_action="update", view=next_view)
    else:
        # Final step — close the modal.
        await ack(response_action="clear")
        if preview:
            # Preview mode — no persistence, show collected answers
            # including auto-populated profile fields, in form order.
            try:
                profile_data = await _get_profile_data(client, user_id)
                lines = [":eyes: *Preview complete* — no registration was saved.\n"]

                # Auto-populated profile fields first.
                lines.append("*Auto-populated from Slack profile:*")
                for key in ("email", "slack_display_name", "github_username"):
                    display = str(profile_data.get(key, "")) or "_(empty)_"
                    lines.append(f"• `{key}`: {display}")

                # Walk steps/fields in the order they were shown.
                lines.append("\n*Submitted answers:*")
                shown_ids: set[str] = set()
                for step in applicable_steps:
                    for field in step.fields:
                        shown_ids.add(field.id)
                        value = answers.get(field.id)
                        if isinstance(value, list):
                            display = ", ".join(str(v) for v in value)
                        else:
                            display = str(value) if value else "_(empty)_"
                        lines.append(f"• `{field.id}` {field.label}\n   {display}")

                # Any leftover answers not tied to a known field (shouldn't
                # happen, but defensive).
                for key, value in answers.items():
                    if key not in shown_ids:
                        if isinstance(value, list):
                            display = ", ".join(str(v) for v in value)
                        else:
                            display = str(value) if value else "_(empty)_"
                        lines.append(f"• `{key}`: {display}")

                await client.chat_postMessage(
                    channel=user_id,
                    text="\n".join(lines),
                )
            except Exception:
                logger.exception("Failed to send preview confirmation to user %s.", user_id)
        else:
            await _finalise_registration(client, hackathon_id, user_id, answers)


# ── Final persistence ───────────────────────────────────────────────


async def _finalise_registration(
    client: AsyncWebClient,
    hackathon_id: str,
    user_id: str,
    answers: dict[str, Any],
) -> None:
    """Persist the completed registration and perform post-registration tasks.

    Steps:
    1. Fetch auto-populated profile data (email, display name, GitHub).
    2. Extract the ``local_site`` answer as the site ID (``None`` for online).
    3. Write (create or update) the registration in DynamoDB.
    4. Invite the user to the hackathon channel.
    5. Send an ephemeral confirmation message.
    """
    # ── Profile data ────────────────────────────────────────────────
    profile_data = await _get_profile_data(client, user_id)

    # The site ID comes from the ``local_site`` form field (if attending
    # in person).  All other answers are stored as ``form_data``.
    site_id: str | None = answers.get("local_site")
    form_data = {k: v for k, v in answers.items() if k != "local_site"}

    # ── Persist ─────────────────────────────────────────────────────
    try:
        existing = await registrations.get_registration(hackathon_id, user_id)
        if existing:
            await registrations.update_registration(hackathon_id, user_id, site_id, form_data)
            logger.info("Updated registration for user %s in hackathon '%s'.", user_id, hackathon_id)
        else:
            await registrations.create_registration(hackathon_id, user_id, site_id, form_data, profile_data)
            logger.info("Created registration for user %s in hackathon '%s'.", user_id, hackathon_id)
    except Exception:
        logger.exception("Failed to persist registration for user %s in hackathon '%s'.", user_id, hackathon_id)
        # Notify the user of the failure.
        try:
            await client.chat_postEphemeral(
                channel=user_id,
                user=user_id,
                text=(
                    f":x: Sorry, something went wrong saving your registration for *{hackathon_id}*. "
                    "Please try again or contact an organiser."
                ),
            )
        except Exception:
            logger.exception("Failed to send error notification to user %s.", user_id)
        return

    # ── Post-registration tasks ─────────────────────────────────────
    await _join_hackathon_channel(client, hackathon_id, user_id)

    # ── Confirmation message ────────────────────────────────────────
    try:
        form = load_form_by_hackathon(hackathon_id)
        await client.chat_postMessage(
            channel=user_id,
            text=(
                f":tada: You're registered for *{form.title}*!\n"
                f"You've been added to <#{form.channel_id}>.\n"
                f"<{form.url}|Find out more about this event>"
            ),
        )
    except Exception:
        logger.exception("Failed to send confirmation to user %s.", user_id)


# ── Modal opener ────────────────────────────────────────────────────


async def open_registration_modal(
    client: AsyncWebClient,
    trigger_id: str,
    hackathon_id: str,
    user_id: str,
    existing_data: dict[str, Any] | None = None,
    preview: bool = False,
) -> None:
    """Open the first step of the registration modal for *user_id*.

    Parameters
    ----------
    client:
        Slack ``AsyncWebClient`` for API calls.
    trigger_id:
        Slack trigger ID from the slash command or interaction (required
        to open a modal within the 3-second window).
    hackathon_id:
        The hackathon to register for.
    user_id:
        Slack user ID of the registrant.
    existing_data:
        Pre-existing registration data for edit flows.  When provided,
        fields are pre-populated with these values.
    preview:
        When ``True``, no registration is saved and no channel join
        happens — the modal is opened for admin preview only.
    """
    answers: dict[str, Any] = existing_data or {}

    # ── Load form definition ────────────────────────────────────────
    try:
        form = load_form_by_hackathon(hackathon_id)
    except FileNotFoundError:
        logger.error("No form YAML found for hackathon '%s'.", hackathon_id)
        await client.chat_postEphemeral(
            channel=user_id,
            user=user_id,
            text=f":x: No registration form found for hackathon *{hackathon_id}*.",
        )
        return

    # ── Determine applicable steps ──────────────────────────────────
    applicable_steps = get_applicable_steps(form, answers)
    if not applicable_steps:
        logger.error("No applicable steps for hackathon '%s' (form may be empty).", hackathon_id)
        await client.chat_postEphemeral(
            channel=user_id,
            user=user_id,
            text=f":x: The registration form for *{hackathon_id}* has no steps.",
        )
        return

    # ── Load sites for options_from: sites ──────────────────────────
    sites = await _load_sites(hackathon_id)

    # ── Build and open the first step ───────────────────────────────
    first_view = await build_modal_view(
        step=applicable_steps[0],
        step_index=0,
        total_steps=len(applicable_steps),
        hackathon_id=hackathon_id,
        answers=answers,
        sites=sites,
        preview=preview,
    )

    try:
        await client.views_open(trigger_id=trigger_id, view=first_view)
        logger.info(
            "Opened registration modal for user %s, hackathon '%s' (%d steps).",
            user_id,
            hackathon_id,
            len(applicable_steps),
        )
    except Exception:
        logger.exception("Failed to open registration modal for user %s.", user_id)
