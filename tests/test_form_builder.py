"""Tests for the Slack Block Kit modal builder."""

from __future__ import annotations

import json

from nf_core_bot.forms.builder import build_modal_view
from nf_core_bot.forms.loader import COUNTRIES, FormField, FormStep

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _statement_step() -> FormStep:
    return FormStep(
        id="welcome",
        title="Welcome",
        step_type="statement",
        text="Hello, world!",
    )


def _text_fields_step() -> FormStep:
    return FormStep(
        id="about",
        title="About You",
        step_type="form",
        fields=[
            FormField(id="first_name", type="text", label="First name", required=True),
            FormField(id="bio", type="text", label="Bio", required=False, multiline=True),
        ],
    )


def _select_step() -> FormStep:
    return FormStep(
        id="demographics",
        title="Demographics",
        step_type="form",
        fields=[
            FormField(
                id="age_group",
                type="static_select",
                label="Age group",
                required=True,
                options=[
                    {"label": "Under 20", "value": "under_20"},
                    {"label": "20-30", "value": "20_30"},
                ],
            ),
        ],
    )


def _checkboxes_step() -> FormStep:
    return FormStep(
        id="agreements",
        title="Agreements",
        step_type="form",
        fields=[
            FormField(
                id="coc",
                type="checkboxes",
                label="Code of Conduct",
                required=True,
                options=[
                    {"label": "I agree", "value": "accepted"},
                ],
            ),
        ],
    )


def _country_step() -> FormStep:
    return FormStep(
        id="location",
        title="Location",
        step_type="form",
        fields=[
            FormField(
                id="country",
                type="static_select",
                label="Country",
                required=True,
                options_from="countries",
            ),
        ],
    )


def _sites_step() -> FormStep:
    return FormStep(
        id="site_choice",
        title="Choose Site",
        step_type="form",
        fields=[
            FormField(
                id="local_site",
                type="static_select",
                label="Which site?",
                required=True,
                options_from="sites",
            ),
        ],
    )


# ---------------------------------------------------------------------------
# Statement step
# ---------------------------------------------------------------------------


async def test_statement_step_structure() -> None:
    view = await build_modal_view(_statement_step(), step_index=0, total_steps=3, hackathon_id="h1")
    assert view["type"] == "modal"
    assert len(view["blocks"]) == 1
    assert view["blocks"][0]["type"] == "section"
    assert view["blocks"][0]["text"]["type"] == "mrkdwn"
    assert view["blocks"][0]["text"]["text"] == "Hello, world!"


# ---------------------------------------------------------------------------
# Form step with text fields
# ---------------------------------------------------------------------------


async def test_text_fields_step() -> None:
    view = await build_modal_view(_text_fields_step(), step_index=1, total_steps=5, hackathon_id="h1")
    blocks = view["blocks"]
    assert len(blocks) == 2

    # First field — plain_text_input, not multiline.
    first = blocks[0]
    assert first["type"] == "input"
    assert first["block_id"] == "first_name"
    assert first["element"]["type"] == "plain_text_input"
    assert first["element"]["multiline"] is False
    assert first["optional"] is False  # required=True → optional=False

    # Second field — multiline.
    second = blocks[1]
    assert second["element"]["multiline"] is True
    assert second["optional"] is True  # required=False → optional=True


# ---------------------------------------------------------------------------
# Form step with static_select
# ---------------------------------------------------------------------------


async def test_static_select_options() -> None:
    view = await build_modal_view(_select_step(), step_index=0, total_steps=2, hackathon_id="h1")
    element = view["blocks"][0]["element"]
    assert element["type"] == "static_select"
    assert len(element["options"]) == 2
    assert element["options"][0]["text"]["text"] == "Under 20"
    assert element["options"][0]["value"] == "under_20"


# ---------------------------------------------------------------------------
# Form step with checkboxes
# ---------------------------------------------------------------------------


async def test_checkboxes_step() -> None:
    view = await build_modal_view(_checkboxes_step(), step_index=0, total_steps=1, hackathon_id="h1")
    element = view["blocks"][0]["element"]
    assert element["type"] == "checkboxes"
    assert len(element["options"]) == 1
    assert element["options"][0]["value"] == "accepted"


# ---------------------------------------------------------------------------
# Options from countries
# ---------------------------------------------------------------------------


async def test_options_from_countries() -> None:
    view = await build_modal_view(_country_step(), step_index=0, total_steps=1, hackathon_id="h1")
    element = view["blocks"][0]["element"]
    assert element["type"] == "static_select"
    # Slack limits to 100 options per element.
    assert len(element["options"]) == min(len(COUNTRIES), 100)
    # Spot-check options that appear in the first 100 (alphabetical by label).
    values = {o["value"] for o in element["options"]}
    assert "AF" in values  # Afghanistan — first entry
    assert "AU" in values  # Australia
    assert "DE" in values  # Germany


# ---------------------------------------------------------------------------
# Options from sites
# ---------------------------------------------------------------------------


async def test_options_from_sites() -> None:
    sites = [
        {"site_id": "london", "name": "London"},
        {"site_id": "stockholm", "name": "Stockholm"},
    ]
    view = await build_modal_view(_sites_step(), step_index=0, total_steps=1, hackathon_id="h1", sites=sites)
    element = view["blocks"][0]["element"]
    assert len(element["options"]) == 2
    labels = {o["text"]["text"] for o in element["options"]}
    assert labels == {"London", "Stockholm"}


async def test_options_from_sites_empty() -> None:
    """When no sites are provided, a placeholder option is shown."""
    view = await build_modal_view(_sites_step(), step_index=0, total_steps=1, hackathon_id="h1", sites=None)
    element = view["blocks"][0]["element"]
    assert len(element["options"]) == 1
    assert element["options"][0]["value"] == "none"


# ---------------------------------------------------------------------------
# Pre-populated answers
# ---------------------------------------------------------------------------


async def test_prepopulated_text_field() -> None:
    view = await build_modal_view(
        _text_fields_step(),
        step_index=0,
        total_steps=1,
        hackathon_id="h1",
        answers={"first_name": "Ada"},
    )
    element = view["blocks"][0]["element"]
    assert element["initial_value"] == "Ada"


async def test_prepopulated_select_field() -> None:
    view = await build_modal_view(
        _select_step(),
        step_index=0,
        total_steps=1,
        hackathon_id="h1",
        answers={"age_group": "20_30"},
    )
    element = view["blocks"][0]["element"]
    assert "initial_option" in element
    assert element["initial_option"]["value"] == "20_30"


async def test_prepopulated_checkboxes() -> None:
    view = await build_modal_view(
        _checkboxes_step(),
        step_index=0,
        total_steps=1,
        hackathon_id="h1",
        answers={"coc": ["accepted"]},
    )
    element = view["blocks"][0]["element"]
    assert "initial_options" in element
    assert len(element["initial_options"]) == 1
    assert element["initial_options"][0]["value"] == "accepted"


# ---------------------------------------------------------------------------
# Submit button text
# ---------------------------------------------------------------------------


async def test_submit_text_next_for_intermediate() -> None:
    view = await build_modal_view(_text_fields_step(), step_index=1, total_steps=5, hackathon_id="h1")
    assert view["submit"]["text"] == "Next"


async def test_submit_text_submit_for_final() -> None:
    view = await build_modal_view(_text_fields_step(), step_index=4, total_steps=5, hackathon_id="h1")
    assert view["submit"]["text"] == "Submit"


async def test_submit_text_submit_for_single_step() -> None:
    view = await build_modal_view(_text_fields_step(), step_index=0, total_steps=1, hackathon_id="h1")
    assert view["submit"]["text"] == "Submit"


# ---------------------------------------------------------------------------
# Title / progress
# ---------------------------------------------------------------------------


async def test_step_progress_in_title() -> None:
    view = await build_modal_view(_text_fields_step(), step_index=2, total_steps=7, hackathon_id="h1")
    title = view["title"]["text"]
    assert title.startswith("3/7")


async def test_title_truncated_when_long() -> None:
    long_step = FormStep(id="long", title="A Very Long Title That Exceeds Limit", step_type="form", fields=[])
    view = await build_modal_view(long_step, step_index=0, total_steps=1, hackathon_id="h1")
    title = view["title"]["text"]
    assert len(title) <= 24


# ---------------------------------------------------------------------------
# Private metadata
# ---------------------------------------------------------------------------


async def test_private_metadata_contains_state() -> None:
    view = await build_modal_view(
        _text_fields_step(),
        step_index=1,
        total_steps=5,
        hackathon_id="h1",
        answers={"first_name": "Ada"},
    )
    meta = json.loads(view["private_metadata"])
    assert meta["hackathon_id"] == "h1"
    assert meta["step_index"] == 1
    assert meta["answers"]["first_name"] == "Ada"


# ---------------------------------------------------------------------------
# Callback ID
# ---------------------------------------------------------------------------


async def test_callback_id_includes_step_index() -> None:
    view = await build_modal_view(_text_fields_step(), step_index=3, total_steps=5, hackathon_id="h1")
    assert view["callback_id"] == "hackathon_reg_step_3"
