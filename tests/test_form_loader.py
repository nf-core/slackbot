"""Tests for the YAML form loader and conditional step evaluation."""

from __future__ import annotations

from pathlib import Path

import pytest

from nf_core_bot.forms.loader import (
    COUNTRIES,
    FormDefinition,
    FormStep,
    get_active_form,
    get_applicable_steps,
    get_form_metadata,
    list_all_forms,
    load_form,
    load_form_by_hackathon,
)

# Resolve the actual 2026-march.yaml file relative to the project root.
_FORMS_DIR = Path(__file__).resolve().parents[1] / "forms"
_MARCH_YAML = _FORMS_DIR / "2026-march.yaml"


# ---------------------------------------------------------------------------
# load_form — parse the real YAML
# ---------------------------------------------------------------------------


def test_load_form_parses_all_steps() -> None:
    form = load_form(_MARCH_YAML)
    assert isinstance(form, FormDefinition)
    assert form.hackathon == "2026-march"
    assert len(form.steps) == 8


def test_load_form_step_ids() -> None:
    form = load_form(_MARCH_YAML)
    step_ids = [s.id for s in form.steps]
    assert step_ids == [
        "welcome",
        "about_you",
        "community_demographics",
        "hackathon_experience",
        "attendance_mode",
        "local_site_selection",
        "online_details",
        "additional",
    ]


def test_load_form_welcome_step() -> None:
    form = load_form(_MARCH_YAML)
    welcome = form.steps[0]
    assert welcome.step_type == "form"
    assert welcome.text is not None
    assert "Code of Conduct" in welcome.text
    # Welcome step now includes the CoC checkbox field.
    assert len(welcome.fields) == 1
    assert welcome.fields[0].id == "code_of_conduct"
    assert welcome.fields[0].type == "checkboxes"


def test_load_form_field_types() -> None:
    form = load_form(_MARCH_YAML)
    about = form.steps[1]  # about_you
    assert about.step_type == "form"

    field_types = {f.id: f.type for f in about.fields}
    assert field_types["first_name"] == "text"
    assert field_types["country"] == "external_select"


def test_load_form_field_required() -> None:
    form = load_form(_MARCH_YAML)
    about = form.steps[1]
    first_name = next(f for f in about.fields if f.id == "first_name")
    assert first_name.required is True
    # 'comments' in the additional step is optional.
    additional = next(s for s in form.steps if s.id == "additional")
    comments = next(f for f in additional.fields if f.id == "comments")
    assert comments.required is False


def test_load_form_field_options() -> None:
    form = load_form(_MARCH_YAML)
    demographics = form.steps[2]  # community_demographics
    age_field = next(f for f in demographics.fields if f.id == "age_group")
    assert age_field.options is not None
    assert len(age_field.options) == 7
    values = {o["value"] for o in age_field.options}
    assert "under_20" in values
    assert "prefer_not_to_say" in values


def test_load_form_field_options_from() -> None:
    form = load_form(_MARCH_YAML)
    about = form.steps[1]
    country_field = next(f for f in about.fields if f.id == "country")
    assert country_field.options_from == "countries"
    assert country_field.options is None  # options_from overrides inline options


def test_load_form_conditions() -> None:
    form = load_form(_MARCH_YAML)
    local_site = next(s for s in form.steps if s.id == "local_site_selection")
    online = next(s for s in form.steps if s.id == "online_details")
    assert local_site.condition == {"field": "attend_local_site", "equals": "yes"}
    assert online.condition == {"field": "attend_local_site", "equals": "no"}


def test_load_form_checkboxes_field() -> None:
    form = load_form(_MARCH_YAML)
    welcome = form.steps[0]  # welcome — CoC checkbox moved here
    coc = next(f for f in welcome.fields if f.id == "code_of_conduct")
    assert coc.type == "checkboxes"
    assert coc.required is True
    assert coc.options is not None
    assert coc.options[0]["value"] == "accepted"


def test_load_form_multiline_field() -> None:
    form = load_form(_MARCH_YAML)
    additional = form.steps[-1]
    comments = next(f for f in additional.fields if f.id == "comments")
    assert comments.multiline is True


def test_load_form_options_from_sites() -> None:
    form = load_form(_MARCH_YAML)
    local_step = next(s for s in form.steps if s.id == "local_site_selection")
    site_field = next(f for f in local_step.fields if f.id == "local_site")
    assert site_field.options_from == "sites"


def test_load_form_file_not_found() -> None:
    with pytest.raises(FileNotFoundError, match="Form YAML not found"):
        load_form("/tmp/nonexistent-form-file.yaml")


# ---------------------------------------------------------------------------
# load_form_by_hackathon
# ---------------------------------------------------------------------------


def test_load_form_by_hackathon_success() -> None:
    form = load_form_by_hackathon("2026-march")
    assert form.hackathon == "2026-march"
    assert len(form.steps) == 8


def test_load_form_by_hackathon_missing_raises() -> None:
    with pytest.raises(FileNotFoundError, match="No form YAML found"):
        load_form_by_hackathon("does-not-exist-999")


# ---------------------------------------------------------------------------
# get_applicable_steps — condition evaluation
# ---------------------------------------------------------------------------


def _load_form() -> FormDefinition:
    return load_form(_MARCH_YAML)


def test_applicable_steps_no_conditions() -> None:
    """With no answers, only unconditional steps are returned."""
    form = _load_form()
    steps = get_applicable_steps(form, {})
    step_ids = [s.id for s in steps]
    # Both conditional steps should be excluded when no answers given.
    assert "local_site_selection" not in step_ids
    assert "online_details" not in step_ids
    # Unconditional steps should all be present.
    assert "welcome" in step_ids
    assert "about_you" in step_ids
    assert "additional" in step_ids


def test_applicable_steps_local_yes() -> None:
    """attend_local_site='yes' includes local_site_selection, excludes online_details."""
    form = _load_form()
    steps = get_applicable_steps(form, {"attend_local_site": "yes"})
    step_ids = [s.id for s in steps]
    assert "local_site_selection" in step_ids
    assert "online_details" not in step_ids


def test_applicable_steps_local_no() -> None:
    """attend_local_site='no' includes online_details, excludes local_site_selection."""
    form = _load_form()
    steps = get_applicable_steps(form, {"attend_local_site": "no"})
    step_ids = [s.id for s in steps]
    assert "online_details" in step_ids
    assert "local_site_selection" not in step_ids


def test_applicable_steps_preserves_order() -> None:
    form = _load_form()
    steps = get_applicable_steps(form, {"attend_local_site": "yes"})
    step_ids = [s.id for s in steps]
    # local_site_selection should come after attendance_mode and before additional.
    assert step_ids.index("attendance_mode") < step_ids.index("local_site_selection")
    assert step_ids.index("local_site_selection") < step_ids.index("additional")


def test_applicable_steps_returns_formstep_instances() -> None:
    form = _load_form()
    steps = get_applicable_steps(form, {})
    for step in steps:
        assert isinstance(step, FormStep)


# ---------------------------------------------------------------------------
# COUNTRIES list
# ---------------------------------------------------------------------------


def test_countries_list_populated() -> None:
    assert len(COUNTRIES) > 100  # There are ~195 countries.


def test_countries_list_structure() -> None:
    for country in COUNTRIES:
        assert "label" in country
        assert "value" in country
        # ISO 3166-1 alpha-2 codes are 2 chars (except Kosovo "XK").
        assert len(country["value"]) == 2


def test_countries_list_has_known_entries() -> None:
    values = {c["value"] for c in COUNTRIES}
    assert "US" in values
    assert "GB" in values
    assert "DE" in values
    assert "SE" in values


# ---------------------------------------------------------------------------
# FormDefinition metadata fields
# ---------------------------------------------------------------------------


class TestFormMetadataFields:
    """Test the new metadata fields in FormDefinition."""

    def test_form_has_title(self) -> None:
        form = load_form_by_hackathon("2026-march")
        assert form.title == "nf-core Hackathon \u2014 March 2026"

    def test_form_has_status(self) -> None:
        form = load_form_by_hackathon("2026-march")
        assert form.status == "draft"

    def test_form_has_channel_id(self) -> None:
        form = load_form_by_hackathon("2026-march")
        assert form.channel_id == "C0ACF0TPF5E"

    def test_form_has_url(self) -> None:
        form = load_form_by_hackathon("2026-march")
        assert form.url == "https://nf-co.re/events/2026/hackathon-march-2026"

    def test_form_has_dates(self) -> None:
        form = load_form_by_hackathon("2026-march")
        assert form.date_start == "2026-03-11"
        assert form.date_end == "2026-03-13"


# ---------------------------------------------------------------------------
# _parse_channel_id
# ---------------------------------------------------------------------------


class TestParseChannelId:
    """Test _parse_channel_id function."""

    def test_raw_id(self) -> None:
        from nf_core_bot.forms.loader import _parse_channel_id

        assert _parse_channel_id("C0ACF0TPF5E") == "C0ACF0TPF5E"

    def test_url(self) -> None:
        from nf_core_bot.forms.loader import _parse_channel_id

        assert _parse_channel_id("https://nfcore.slack.com/archives/C0ACF0TPF5E") == "C0ACF0TPF5E"

    def test_invalid_raises(self) -> None:
        from nf_core_bot.forms.loader import _parse_channel_id

        with pytest.raises(ValueError):
            _parse_channel_id("not-a-channel")


# ---------------------------------------------------------------------------
# list_all_forms
# ---------------------------------------------------------------------------


class TestListAllForms:
    """Test the list_all_forms function."""

    def test_returns_list(self) -> None:
        forms = list_all_forms()
        assert isinstance(forms, list)
        assert len(forms) >= 1

    def test_dict_has_expected_keys(self) -> None:
        forms = list_all_forms()
        form = forms[0]
        assert "hackathon_id" in form
        assert "title" in form
        assert "status" in form
        assert "date_start" in form
        assert "date_end" in form
        assert "url" in form

    def test_sorted_by_date_descending(self) -> None:
        forms = list_all_forms()
        if len(forms) > 1:
            dates = [f["date_start"] for f in forms]
            assert dates == sorted(dates, reverse=True)


# ---------------------------------------------------------------------------
# get_active_form
# ---------------------------------------------------------------------------


class TestGetActiveForm:
    """Test the get_active_form function."""

    def test_returns_none_when_no_open(self) -> None:
        # The 2026-march form has status "draft", not "open"
        result = get_active_form()
        assert result is None  # since we set status to draft in the YAML


# ---------------------------------------------------------------------------
# get_form_metadata
# ---------------------------------------------------------------------------


class TestGetFormMetadata:
    """Test the get_form_metadata function."""

    def test_returns_dict_for_existing(self) -> None:
        result = get_form_metadata("2026-march")
        assert result is not None
        assert result["hackathon_id"] == "2026-march"
        assert result["title"] == "nf-core Hackathon \u2014 March 2026"

    def test_returns_none_for_missing(self) -> None:
        result = get_form_metadata("nonexistent")
        assert result is None
