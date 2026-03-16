"""Tests for nf_core_bot.forms.handler — modal open, step submission, value extraction."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock

import pytest

from nf_core_bot.forms.handler import _extract_values, handle_registration_step, open_registration_modal
from nf_core_bot.forms.loader import FormDefinition, FormField, FormStep

# Default metadata fields for constructing FormDefinition in tests.
_FORM_DEFAULTS = {
    "title": "Test Hackathon",
    "status": "open",
    "channel_id": "C123TEST",
    "url": "https://example.com",
    "date_start": "2026-01-01",
    "date_end": "2026-01-03",
}


@pytest.fixture()
def client() -> AsyncMock:
    return AsyncMock()


# ── _extract_values ──────────────────────────────────────────────────


class TestExtractValues:
    def test_plain_text_input(self) -> None:
        state_values: dict[str, dict[str, Any]] = {
            "name": {
                "name_action": {
                    "type": "plain_text_input",
                    "value": "Alice",
                }
            }
        }
        result = _extract_values(state_values)
        assert result == {"name": "Alice"}

    def test_static_select(self) -> None:
        state_values: dict[str, dict[str, Any]] = {
            "site": {
                "site_action": {
                    "type": "static_select",
                    "selected_option": {"text": {"type": "plain_text", "text": "London"}, "value": "london"},
                }
            }
        }
        result = _extract_values(state_values)
        assert result == {"site": "london"}

    def test_static_select_none(self) -> None:
        state_values: dict[str, dict[str, Any]] = {
            "site": {
                "site_action": {
                    "type": "static_select",
                    "selected_option": None,
                }
            }
        }
        result = _extract_values(state_values)
        assert result == {"site": None}

    def test_checkboxes(self) -> None:
        state_values: dict[str, dict[str, Any]] = {
            "dietary": {
                "dietary_action": {
                    "type": "checkboxes",
                    "selected_options": [
                        {"text": {"type": "plain_text", "text": "Vegan"}, "value": "vegan"},
                        {"text": {"type": "plain_text", "text": "Gluten-free"}, "value": "gf"},
                    ],
                }
            }
        }
        result = _extract_values(state_values)
        assert result == {"dietary": ["vegan", "gf"]}

    def test_checkboxes_none_selected(self) -> None:
        state_values: dict[str, dict[str, Any]] = {
            "dietary": {
                "dietary_action": {
                    "type": "checkboxes",
                    "selected_options": None,
                }
            }
        }
        result = _extract_values(state_values)
        assert result == {"dietary": []}

    def test_unknown_type_fallback(self) -> None:
        state_values: dict[str, dict[str, Any]] = {
            "field": {
                "action": {
                    "type": "number_input",
                    "value": "42",
                }
            }
        }
        result = _extract_values(state_values)
        assert result == {"field": "42"}

    def test_multiple_blocks(self) -> None:
        state_values: dict[str, dict[str, Any]] = {
            "name": {"name_action": {"type": "plain_text_input", "value": "Alice"}},
            "site": {
                "site_action": {
                    "type": "static_select",
                    "selected_option": {"value": "london", "text": {"type": "plain_text", "text": "London"}},
                }
            },
        }
        result = _extract_values(state_values)
        assert result == {"name": "Alice", "site": "london"}

    def test_empty_text_value(self) -> None:
        state_values: dict[str, dict[str, Any]] = {
            "bio": {
                "bio_action": {
                    "type": "plain_text_input",
                    "value": None,
                }
            }
        }
        result = _extract_values(state_values)
        assert result == {"bio": ""}


# ── open_registration_modal ──────────────────────────────────────────


class TestOpenRegistrationModal:
    async def test_success_opens_view(self, client: AsyncMock, monkeypatch: pytest.MonkeyPatch) -> None:
        form = FormDefinition(
            hackathon="h1",
            **_FORM_DEFAULTS,
            steps=[
                FormStep(
                    id="step1",
                    title="Basic Info",
                    fields=[FormField(id="name", type="text", label="Your name", required=True)],
                ),
            ],
        )
        monkeypatch.setattr(
            "nf_core_bot.forms.handler.load_form_by_hackathon",
            lambda hid: form,
        )
        monkeypatch.setattr(
            "nf_core_bot.forms.handler._load_sites",
            AsyncMock(return_value=[]),
        )

        await open_registration_modal(client, "T_TRIGGER", "h1", "U_USER")

        client.views_open.assert_awaited_once()
        call_kwargs = client.views_open.call_args.kwargs
        assert call_kwargs["trigger_id"] == "T_TRIGGER"
        view = call_kwargs["view"]
        assert view["type"] == "modal"
        assert "step1" in view["callback_id"] or "reg_step" in view["callback_id"]

    async def test_no_form_yaml(self, client: AsyncMock, monkeypatch: pytest.MonkeyPatch) -> None:
        def _raise(hid: str) -> None:
            raise FileNotFoundError("no yaml")

        monkeypatch.setattr(
            "nf_core_bot.forms.handler.load_form_by_hackathon",
            _raise,
        )

        await open_registration_modal(client, "T_TRIGGER", "h1", "U_USER")

        client.chat_postEphemeral.assert_awaited_once()
        text = client.chat_postEphemeral.call_args.kwargs["text"]
        assert "No registration form found" in text

    async def test_existing_data_passed(self, client: AsyncMock, monkeypatch: pytest.MonkeyPatch) -> None:
        form = FormDefinition(
            hackathon="h1",
            **_FORM_DEFAULTS,
            steps=[
                FormStep(
                    id="step1",
                    title="Basic Info",
                    fields=[FormField(id="name", type="text", label="Your name")],
                ),
            ],
        )
        monkeypatch.setattr(
            "nf_core_bot.forms.handler.load_form_by_hackathon",
            lambda hid: form,
        )
        monkeypatch.setattr(
            "nf_core_bot.forms.handler._load_sites",
            AsyncMock(return_value=[]),
        )

        await open_registration_modal(client, "T_TRIGGER", "h1", "U_USER", existing_data={"name": "Alice"})

        client.views_open.assert_awaited_once()
        view = client.views_open.call_args.kwargs["view"]
        # The answers should be passed through to private_metadata
        metadata = json.loads(view["private_metadata"])
        assert metadata["answers"]["name"] == "Alice"


# ── handle_registration_step ─────────────────────────────────────────


def _make_view(
    hackathon_id: str,
    step_index: int,
    answers: dict[str, Any] | None = None,
    state_values: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a minimal Slack view payload for testing step submission."""
    metadata = json.dumps(
        {
            "hackathon_id": hackathon_id,
            "step_index": step_index,
            "answers": answers or {},
        }
    )
    return {
        "private_metadata": metadata,
        "state": {"values": state_values or {}},
    }


class TestHandleRegistrationStep:
    async def test_intermediate_step_updates_view(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """When there are more steps, ack should be called with response_action='update'."""
        form = FormDefinition(
            hackathon="h1",
            **_FORM_DEFAULTS,
            steps=[
                FormStep(
                    id="step1",
                    title="Step 1",
                    fields=[FormField(id="name", type="text", label="Name")],
                ),
                FormStep(
                    id="step2",
                    title="Step 2",
                    fields=[FormField(id="site", type="text", label="Site")],
                ),
            ],
        )
        monkeypatch.setattr(
            "nf_core_bot.forms.handler.load_form_by_hackathon",
            lambda hid: form,
        )
        monkeypatch.setattr(
            "nf_core_bot.forms.handler._load_sites",
            AsyncMock(return_value=[]),
        )

        ack = AsyncMock()
        client = AsyncMock()
        body: dict[str, Any] = {"user": {"id": "U_USER"}}
        view = _make_view(
            "h1",
            0,
            answers={},
            state_values={
                "name": {"name_action": {"type": "plain_text_input", "value": "Alice"}},
            },
        )

        await handle_registration_step(ack, body, client, view)

        ack.assert_awaited_once()
        call_kwargs = ack.call_args.kwargs
        assert call_kwargs["response_action"] == "update"
        assert call_kwargs["view"]["type"] == "modal"

    async def test_final_step_clears_and_saves(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """When this is the last step, ack with 'clear' and persist registration."""
        form = FormDefinition(
            hackathon="h1",
            **_FORM_DEFAULTS,
            steps=[
                FormStep(
                    id="step1",
                    title="Only Step",
                    fields=[FormField(id="name", type="text", label="Name")],
                ),
            ],
        )
        monkeypatch.setattr(
            "nf_core_bot.forms.handler.load_form_by_hackathon",
            lambda hid: form,
        )
        mock_finalise = AsyncMock()
        monkeypatch.setattr(
            "nf_core_bot.forms.handler._finalise_registration",
            mock_finalise,
        )

        ack = AsyncMock()
        client = AsyncMock()
        body: dict[str, Any] = {"user": {"id": "U_USER"}}
        view = _make_view(
            "h1",
            0,
            answers={},
            state_values={
                "name": {"name_action": {"type": "plain_text_input", "value": "Alice"}},
            },
        )

        await handle_registration_step(ack, body, client, view)

        ack.assert_awaited_once()
        call_kwargs = ack.call_args.kwargs
        assert call_kwargs["response_action"] == "clear"
        mock_finalise.assert_awaited_once()
        # Check the finalise was called with the correct answers
        finalise_args = mock_finalise.call_args
        assert finalise_args[0][2] == "U_USER"  # user_id
        assert finalise_args[0][3]["name"] == "Alice"  # answers

    async def test_form_not_found_returns_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """If the form YAML is missing, ack with an errors response."""

        def _raise(hid: str) -> None:
            raise FileNotFoundError("no yaml")

        monkeypatch.setattr(
            "nf_core_bot.forms.handler.load_form_by_hackathon",
            _raise,
        )

        ack = AsyncMock()
        client = AsyncMock()
        body: dict[str, Any] = {"user": {"id": "U_USER"}}
        view = _make_view("h1", 0)

        await handle_registration_step(ack, body, client, view)

        ack.assert_awaited_once()
        call_kwargs = ack.call_args.kwargs
        assert call_kwargs["response_action"] == "errors"

    async def test_answers_accumulated_across_steps(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Answers from earlier steps should be preserved and merged."""
        form = FormDefinition(
            hackathon="h1",
            **_FORM_DEFAULTS,
            steps=[
                FormStep(
                    id="step1",
                    title="Step 1",
                    fields=[FormField(id="name", type="text", label="Name")],
                ),
                FormStep(
                    id="step2",
                    title="Step 2",
                    fields=[FormField(id="site", type="text", label="Site")],
                ),
                FormStep(
                    id="step3",
                    title="Step 3",
                    fields=[FormField(id="bio", type="text", label="Bio")],
                ),
            ],
        )
        monkeypatch.setattr(
            "nf_core_bot.forms.handler.load_form_by_hackathon",
            lambda hid: form,
        )
        monkeypatch.setattr(
            "nf_core_bot.forms.handler._load_sites",
            AsyncMock(return_value=[]),
        )

        ack = AsyncMock()
        client = AsyncMock()
        body: dict[str, Any] = {"user": {"id": "U_USER"}}

        # Simulate step 1 (index 0) with answers from step 0 already present
        view = _make_view(
            "h1",
            1,
            answers={"name": "Alice"},
            state_values={
                "site": {"site_action": {"type": "plain_text_input", "value": "London"}},
            },
        )

        await handle_registration_step(ack, body, client, view)

        ack.assert_awaited_once()
        # Should produce an update with step 2 (index 2)
        call_kwargs = ack.call_args.kwargs
        assert call_kwargs["response_action"] == "update"
        # Verify accumulated answers are in the new view's metadata
        new_metadata = json.loads(call_kwargs["view"]["private_metadata"])
        assert new_metadata["answers"]["name"] == "Alice"
        assert new_metadata["answers"]["site"] == "London"
