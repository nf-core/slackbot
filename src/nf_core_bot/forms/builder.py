"""Convert parsed form definitions into Slack Block Kit modal views.

Each :class:`~nf_core_bot.forms.loader.FormStep` is rendered as a single
Slack modal view.  Statement steps show informational text; form steps
contain input blocks for each field.

The multi-step flow relies on Slack's ``view_submission`` with
``response_action: "update"`` to advance through steps without closing
the modal.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from nf_core_bot.forms.loader import COUNTRIES, FormField, FormStep

logger = logging.getLogger(__name__)

# Slack limits: modal title 24 chars, label 2000 chars, options 100 per element.
_MAX_TITLE_LENGTH = 24
_MAX_OPTIONS_PER_ELEMENT = 100


# ── Option helpers ──────────────────────────────────────────────────


def _build_option(label: str, value: str, description: str | None = None) -> dict[str, Any]:
    """Build a single Slack Block Kit option object."""
    opt: dict[str, Any] = {
        "text": {"type": "plain_text", "text": label[:75]},  # Slack limit: 75 chars
        "value": value,
    }
    if description:
        opt["description"] = {"type": "plain_text", "text": description[:75]}
    return opt


def _resolve_options(
    field: FormField,
    sites: list[dict[str, str]] | None = None,
) -> list[dict[str, Any]]:
    """Resolve the option list for a field.

    - ``options_from: countries`` → built-in :data:`COUNTRIES` list
    - ``options_from: sites`` → dynamically populated from DynamoDB sites
    - ``options`` → inline options from the YAML definition
    """
    if field.options_from == "countries":
        return [_build_option(c["label"], c["value"]) for c in COUNTRIES[:_MAX_OPTIONS_PER_ELEMENT]]

    if field.options_from == "sites":
        if not sites:
            logger.warning("No sites provided for options_from='sites' on field '%s'.", field.id)
            return [_build_option("(No sites available)", "none")]
        return [
            _build_option(site.get("name", site.get("site_id", "Unknown")), site.get("site_id", "unknown"))
            for site in sites[:_MAX_OPTIONS_PER_ELEMENT]
        ]

    if field.options:
        return [
            _build_option(opt["label"], opt["value"], opt.get("description"))
            for opt in field.options[:_MAX_OPTIONS_PER_ELEMENT]
        ]

    return []


# ── Block Kit element builders ──────────────────────────────────────


def _build_text_element(field: FormField, initial_value: str | None = None) -> dict[str, Any]:
    """Build a ``plain_text_input`` element."""
    element: dict[str, Any] = {
        "type": "plain_text_input",
        "action_id": field.id,
        "multiline": field.multiline,
    }
    if initial_value:
        element["initial_value"] = initial_value
    return element


def _build_static_select_element(
    field: FormField,
    sites: list[dict[str, str]] | None = None,
    initial_value: str | None = None,
) -> dict[str, Any]:
    """Build a ``static_select`` element."""
    options = _resolve_options(field, sites)
    element: dict[str, Any] = {
        "type": "static_select",
        "action_id": field.id,
        "placeholder": {"type": "plain_text", "text": "Select an option"},
        "options": options,
    }
    if initial_value:
        # Find the matching option to set as initial_option.
        for opt in options:
            if opt["value"] == initial_value:
                element["initial_option"] = opt
                break
    return element


def _build_external_select_element(
    field: FormField,
    initial_value: str | None = None,
) -> dict[str, Any]:
    """Build an ``external_select`` element (type-ahead search).

    Options are loaded dynamically via a ``block_suggestion`` handler
    registered in ``app.py``.  The ``action_id`` is used to identify
    which option source to query.
    """
    element: dict[str, Any] = {
        "type": "external_select",
        "action_id": field.id,
        "placeholder": {"type": "plain_text", "text": "Start typing to search…"},
        "min_query_length": 1,
    }
    if initial_value:
        # Reconstruct the initial_option from the value.
        # For countries, the label is the titlecased value.
        from nf_core_bot.forms.loader import COUNTRIES

        label = initial_value
        for c in COUNTRIES:
            if c["value"] == initial_value:
                label = c["label"]
                break
        element["initial_option"] = _build_option(label, initial_value)
    return element


def _build_checkboxes_element(
    field: FormField,
    initial_values: list[str] | None = None,
) -> dict[str, Any]:
    """Build a ``checkboxes`` element."""
    options = _resolve_options(field)
    element: dict[str, Any] = {
        "type": "checkboxes",
        "action_id": field.id,
        "options": options,
    }
    if initial_values:
        element["initial_options"] = [opt for opt in options if opt["value"] in initial_values]
    return element


# ── Input block builder ─────────────────────────────────────────────


def _build_input_block(
    field: FormField,
    sites: list[dict[str, str]] | None = None,
    answers: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a Slack ``input`` block for a single :class:`FormField`.

    Uses *answers* to pre-populate the field when editing a registration.
    """
    existing = (answers or {}).get(field.id)

    if field.type == "text":
        element = _build_text_element(field, initial_value=existing if isinstance(existing, str) else None)
    elif field.type == "static_select":
        element = _build_static_select_element(
            field,
            sites=sites,
            initial_value=existing if isinstance(existing, str) else None,
        )
    elif field.type == "external_select":
        element = _build_external_select_element(
            field,
            initial_value=existing if isinstance(existing, str) else None,
        )
    elif field.type == "checkboxes":
        initial_vals = existing if isinstance(existing, list) else None
        element = _build_checkboxes_element(field, initial_values=initial_vals)
    else:
        logger.warning("Unknown field type '%s' for field '%s' — falling back to text.", field.type, field.id)
        element = _build_text_element(field)

    block: dict[str, Any] = {
        "type": "input",
        "block_id": field.id,
        "label": {"type": "plain_text", "text": field.label[:2000]},
        "element": element,
        "optional": not field.required,
    }
    return block


# ── Statement view blocks ──────────────────────────────────────────


def _build_statement_blocks(step: FormStep) -> list[dict[str, Any]]:
    """Build Block Kit blocks for a statement step (informational text)."""
    blocks: list[dict[str, Any]] = []
    if step.text:
        blocks.append(
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": step.text},
            }
        )
    return blocks


# ── Modal view builder ──────────────────────────────────────────────


def _truncate_title(title: str) -> str:
    """Truncate a title to fit Slack's 24-character modal title limit."""
    if len(title) <= _MAX_TITLE_LENGTH:
        return title
    return title[: _MAX_TITLE_LENGTH - 1] + "\u2026"


async def build_modal_view(
    step: FormStep,
    step_index: int,
    total_steps: int,
    hackathon_id: str,
    answers: dict[str, Any] | None = None,
    sites: list[dict[str, str]] | None = None,
    preview: bool = False,
) -> dict[str, Any]:
    """Build a Slack Block Kit modal view dict for a single form step.

    Parameters
    ----------
    step:
        The :class:`FormStep` to render.
    step_index:
        Zero-based index of this step within the applicable steps.
    total_steps:
        Total number of applicable steps (used for progress display).
    hackathon_id:
        Hackathon identifier (persisted in ``private_metadata``).
    answers:
        Previously submitted answers for pre-population and state
        transfer between steps.
    sites:
        DynamoDB site records for ``options_from: sites`` fields.
    preview:
        When ``True``, the ``preview`` flag is included in
        ``private_metadata`` so the submission handler skips persistence.

    Returns
    -------
    dict
        A Slack Block Kit view payload suitable for ``views.open``,
        ``views.update``, or ``response_action: "update"``.
    """
    answers = answers or {}
    is_last_step = step_index == total_steps - 1

    # ── Title (with step progress) ──────────────────────────────────
    step_num = step_index + 1
    progress = f"{step_num}/{total_steps}"
    raw_title = f"{progress} {step.title}"
    title = _truncate_title(raw_title)

    # ── Blocks ──────────────────────────────────────────────────────
    if step.step_type == "statement":
        blocks = _build_statement_blocks(step)
    else:
        blocks = []
        # Render preamble text (e.g. welcome message) before input fields.
        if step.text:
            blocks.append(
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": step.text},
                }
            )
        for f in step.fields:
            blocks.append(_build_input_block(f, sites=sites, answers=answers))
            # After the last_name field, inject a read-only profile info block.
            if f.id == "last_name" and (answers.get("_email") or answers.get("_github_username")):
                info_parts: list[str] = []
                if answers.get("_email"):
                    info_parts.append(f"*Email:* {answers['_email']}")
                if answers.get("_github_username"):
                    info_parts.append(f"*GitHub:* {answers['_github_username']}")
                info_parts.append("_Edit your Slack profile to change these._")
                blocks.append(
                    {
                        "type": "context",
                        "elements": [{"type": "mrkdwn", "text": "  ".join(info_parts)}],
                    }
                )

    # ── Private metadata ────────────────────────────────────────────
    meta_dict: dict[str, Any] = {
        "hackathon_id": hackathon_id,
        "step_index": step_index,
        "answers": answers,
    }
    if preview:
        meta_dict["preview"] = True
    metadata = json.dumps(meta_dict, separators=(",", ":"))  # compact encoding

    # Slack limits private_metadata to 3000 characters.
    if len(metadata) > 3000:
        logger.warning(
            "private_metadata exceeds 3000 chars (%d) at step %d — answers may be truncated.",
            len(metadata),
            step_index,
        )

    # ── Submit / Close buttons ──────────────────────────────────────
    submit_text = "Submit" if is_last_step else "Next"

    view: dict[str, Any] = {
        "type": "modal",
        "callback_id": f"hackathon_reg_step_{step_index}",
        "title": {"type": "plain_text", "text": title},
        "submit": {"type": "plain_text", "text": submit_text},
        "close": {"type": "plain_text", "text": "Cancel"},
        "private_metadata": metadata,
        "blocks": blocks,
    }

    return view
