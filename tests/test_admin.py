"""Tests for nf_core_bot.commands.hackathon.admin — admin handlers."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from nf_core_bot.commands.hackathon.admin import (
    _resolve_hackathon_id,
    handle_admin_add_site,
    handle_admin_delete_site,
    handle_admin_edit_site,
    handle_admin_edit_site_picker,
    handle_admin_list,
    handle_admin_list_sites,
    handle_admin_preview,
    handle_admin_site_submission,
)

# ── Shared helpers ──────────────────────────────────────────────────

_KNOWN_HACKATHON = {"hackathon_id": "h1", "title": "Test"}


def _meta_for_h1(hid: str) -> dict[str, str] | None:
    """Monkeypatch helper: recognise ``h1`` as a valid hackathon."""
    return {"hackathon_id": hid, "title": "Test"} if hid == "h1" else None


def _site_submission_body(
    hackathon_id: str = "h1",
    site_id: str = "stockholm-uni",
    name: str = "Stockholm University",
    city: str = "Stockholm",
    country: str = "sweden",
    organiser_ids: list[str] | None = None,
    private_metadata: str = "{}",
) -> dict:
    """Build a mock view_submission body for the site modal."""
    return {
        "user": {"id": "U123"},
        "view": {
            "id": "V123",
            "private_metadata": private_metadata,
            "state": {
                "values": {
                    "hackathon": {"hackathon": {"selected_option": {"value": hackathon_id}}},
                    "site_id": {"site_id": {"value": site_id}},
                    "name": {"name": {"value": name}},
                    "city": {"city": {"value": city}},
                    "country": {"country": {"selected_option": {"value": country}}},
                    "organisers": {"organisers": {"selected_users": organiser_ids or []}},
                }
            },
        },
    }


@pytest.fixture()
def ack() -> AsyncMock:
    return AsyncMock()


@pytest.fixture()
def respond() -> AsyncMock:
    return AsyncMock()


@pytest.fixture()
def _patch_known_hackathon(monkeypatch: pytest.MonkeyPatch) -> None:
    """Monkeypatch ``get_form_metadata`` so that ``h1`` is always recognised."""
    monkeypatch.setattr(
        "nf_core_bot.commands.hackathon.admin.get_form_metadata",
        lambda hid: {"hackathon_id": hid, "title": "Test"},
    )


@pytest.fixture()
def _patch_no_active(monkeypatch: pytest.MonkeyPatch) -> None:
    """Monkeypatch ``get_active_form`` to return ``None``."""
    monkeypatch.setattr(
        "nf_core_bot.commands.hackathon.admin.get_active_form",
        lambda: None,
    )


# ── _resolve_hackathon_id ──────────────────────────────────────────


class TestResolveHackathonId:
    def test_explicit_known_hackathon(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "nf_core_bot.commands.hackathon.admin.get_form_metadata",
            lambda hid: {"hackathon_id": hid} if hid == "h1" else None,
        )
        hid, remaining = _resolve_hackathon_id(["h1", "site-id", "@user"])
        assert hid == "h1"
        assert remaining == ["site-id", "@user"]

    def test_unknown_first_token_defaults_to_active(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "nf_core_bot.commands.hackathon.admin.get_form_metadata",
            lambda hid: None,
        )
        monkeypatch.setattr(
            "nf_core_bot.commands.hackathon.admin.get_active_form",
            lambda: {"hackathon_id": "active-hack"},
        )
        hid, remaining = _resolve_hackathon_id(["site-id", "@user"])
        assert hid == "active-hack"
        assert remaining == ["site-id", "@user"]

    def test_empty_args_defaults_to_active(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "nf_core_bot.commands.hackathon.admin.get_active_form",
            lambda: {"hackathon_id": "active-hack"},
        )
        hid, remaining = _resolve_hackathon_id([])
        assert hid == "active-hack"
        assert remaining == []

    def test_empty_args_no_active(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "nf_core_bot.commands.hackathon.admin.get_active_form",
            lambda: None,
        )
        hid, remaining = _resolve_hackathon_id([])
        assert hid is None
        assert remaining == []

    def test_unknown_token_no_active(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "nf_core_bot.commands.hackathon.admin.get_form_metadata",
            lambda hid: None,
        )
        monkeypatch.setattr(
            "nf_core_bot.commands.hackathon.admin.get_active_form",
            lambda: None,
        )
        hid, remaining = _resolve_hackathon_id(["site-id"])
        assert hid is None
        assert remaining == ["site-id"]


# ── handle_admin_list ────────────────────────────────────────────────


class TestAdminList:
    async def test_empty_list(self, ack: AsyncMock, respond: AsyncMock, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "nf_core_bot.commands.hackathon.admin.list_all_forms",
            lambda: [],
        )
        await handle_admin_list(ack, respond)
        ack.assert_awaited_once()
        assert "No hackathon forms found" in respond.call_args.kwargs["text"]

    async def test_multiple_hackathons(
        self, ack: AsyncMock, respond: AsyncMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "nf_core_bot.commands.hackathon.admin.list_all_forms",
            lambda: [
                {
                    "hackathon_id": "h1",
                    "title": "First",
                    "status": "open",
                    "date_start": "2026-03-11",
                    "date_end": "2026-03-13",
                    "url": "https://nf-co.re/events/2026/hackathon-march-2026",
                },
                {
                    "hackathon_id": "h2",
                    "title": "Second",
                    "status": "draft",
                    "date_start": "2026-06-01",
                    "date_end": "2026-06-03",
                    "url": "https://nf-co.re/events/2026/hackathon-june-2026",
                },
            ],
        )
        await handle_admin_list(ack, respond)
        ack.assert_awaited_once()
        text = respond.call_args.kwargs["text"]
        assert "h1" in text
        assert "h2" in text


# ── handle_admin_preview ─────────────────────────────────────────────


class TestAdminPreview:
    @pytest.mark.usefixtures("_patch_no_active")
    async def test_no_args_no_active(self, ack: AsyncMock, respond: AsyncMock) -> None:
        client = AsyncMock()
        body = {"trigger_id": "T123", "user_id": "U123"}
        await handle_admin_preview(ack, respond, client, body, [])
        ack.assert_awaited_once()
        assert "No active hackathon" in str(respond.call_args)

    async def test_success_opens_modal(
        self, ack: AsyncMock, respond: AsyncMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = AsyncMock()
        body = {"trigger_id": "T123", "user_id": "U123"}
        monkeypatch.setattr(
            "nf_core_bot.commands.hackathon.admin.get_form_metadata",
            lambda hid: {"hackathon_id": "h1", "title": "Test"},
        )
        mock_open = AsyncMock()
        monkeypatch.setattr("nf_core_bot.forms.handler.open_registration_modal", mock_open)
        await handle_admin_preview(ack, respond, client, body, ["h1"])
        ack.assert_awaited_once()
        mock_open.assert_awaited_once()
        call_kwargs = mock_open.call_args
        assert call_kwargs[1].get("preview") is True or call_kwargs[0][-1] is True


# ── handle_admin_add_site ────────────────────────────────────────────


class TestAdminAddSite:
    async def test_opens_modal(self, ack: AsyncMock, respond: AsyncMock, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "nf_core_bot.commands.hackathon.admin.list_all_forms",
            lambda: [{"hackathon_id": "h1", "title": "Test Hack"}],
        )
        monkeypatch.setattr(
            "nf_core_bot.commands.hackathon.admin.get_active_form",
            lambda: {"hackathon_id": "h1"},
        )
        client = AsyncMock()
        body: dict[str, str] = {"trigger_id": "T123"}

        await handle_admin_add_site(ack, respond, client, body, [])

        ack.assert_awaited_once()
        client.views_open.assert_awaited_once()
        view = client.views_open.call_args.kwargs["view"]
        assert view["callback_id"] == "admin_site"
        assert "Add" in view["title"]["text"]

    async def test_no_forms_found(self, ack: AsyncMock, respond: AsyncMock, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "nf_core_bot.commands.hackathon.admin.list_all_forms",
            lambda: [],
        )
        client = AsyncMock()
        body: dict[str, str] = {"trigger_id": "T123"}

        await handle_admin_add_site(ack, respond, client, body, [])

        ack.assert_awaited_once()
        assert "No hackathon forms found" in respond.call_args.kwargs["text"]


# ── handle_admin_edit_site ───────────────────────────────────────────


class TestAdminEditSite:
    async def test_opens_picker_modal(
        self, ack: AsyncMock, respond: AsyncMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "nf_core_bot.commands.hackathon.admin.list_all_forms",
            lambda: [{"hackathon_id": "h1", "title": "Test"}],
        )
        monkeypatch.setattr(
            "nf_core_bot.commands.hackathon.admin.get_active_form",
            lambda: {"hackathon_id": "h1"},
        )
        monkeypatch.setattr(
            "nf_core_bot.commands.hackathon.admin.list_sites",
            AsyncMock(return_value=[{"site_id": "s1", "name": "Site One", "city": "London"}]),
        )
        client = AsyncMock()
        body: dict[str, str] = {"trigger_id": "T123"}

        await handle_admin_edit_site(ack, respond, client, body, [])

        ack.assert_awaited_once()
        client.views_open.assert_awaited_once()
        view = client.views_open.call_args.kwargs["view"]
        assert view["callback_id"] == "admin_edit_site_picker"

    async def test_no_sites_shows_error(
        self, ack: AsyncMock, respond: AsyncMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "nf_core_bot.commands.hackathon.admin.list_all_forms",
            lambda: [{"hackathon_id": "h1", "title": "Test"}],
        )
        monkeypatch.setattr(
            "nf_core_bot.commands.hackathon.admin.get_active_form",
            lambda: {"hackathon_id": "h1"},
        )
        monkeypatch.setattr(
            "nf_core_bot.commands.hackathon.admin.list_sites",
            AsyncMock(return_value=[]),
        )
        client = AsyncMock()
        body: dict[str, str] = {"trigger_id": "T123"}

        await handle_admin_edit_site(ack, respond, client, body, [])

        ack.assert_awaited_once()
        assert "No sites found" in respond.call_args.kwargs["text"]

    async def test_picker_submission_loads_edit_form(self, ack: AsyncMock, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "nf_core_bot.commands.hackathon.admin.get_site",
            AsyncMock(return_value={"site_id": "s1", "name": "Site One", "city": "London", "country": "uk"}),
        )
        monkeypatch.setattr(
            "nf_core_bot.commands.hackathon.admin.list_organisers",
            AsyncMock(return_value=[{"user_id": "U1"}]),
        )
        monkeypatch.setattr(
            "nf_core_bot.commands.hackathon.admin.list_all_forms",
            lambda: [{"hackathon_id": "h1", "title": "Test"}],
        )
        client = AsyncMock()
        body = {
            "user": {"id": "U123"},
            "view": {
                "state": {
                    "values": {
                        "hackathon": {"hackathon": {"selected_option": {"value": "h1"}}},
                        "site": {"site": {"selected_option": {"value": "s1"}}},
                    }
                }
            },
        }

        await handle_admin_edit_site_picker(ack, body, client)

        ack.assert_awaited_once()
        # Should update the view to the edit form.
        view = ack.call_args.kwargs["view"]
        assert view["callback_id"] == "admin_site"
        assert "Edit" in view["title"]["text"]
        meta = json.loads(view["private_metadata"])
        assert meta["edit_site_id"] == "s1"


# ── handle_admin_site_submission ─────────────────────────────────────


class TestAdminSiteSubmission:
    async def test_add_success(self, ack: AsyncMock, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("nf_core_bot.commands.hackathon.admin.add_site", AsyncMock())
        monkeypatch.setattr("nf_core_bot.commands.hackathon.admin.list_organisers", AsyncMock(return_value=[]))
        client = AsyncMock()

        await handle_admin_site_submission(ack, _site_submission_body(), client)

        ack.assert_awaited_once()
        text = client.chat_postMessage.call_args.kwargs["text"]
        assert "stockholm-uni" in text
        assert "added" in text

    async def test_edit_success(self, ack: AsyncMock, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("nf_core_bot.commands.hackathon.admin.update_site", AsyncMock())
        monkeypatch.setattr("nf_core_bot.commands.hackathon.admin.list_organisers", AsyncMock(return_value=[]))
        client = AsyncMock()
        meta = json.dumps({"edit_site_id": "stockholm-uni", "hackathon_id": "h1"})

        await handle_admin_site_submission(ack, _site_submission_body(private_metadata=meta), client)

        ack.assert_awaited_once()
        text = client.chat_postMessage.call_args.kwargs["text"]
        assert "updated" in text

    async def test_bad_site_id(self, ack: AsyncMock) -> None:
        client = AsyncMock()
        await handle_admin_site_submission(ack, _site_submission_body(site_id="Bad Site!"), client)
        ack.assert_awaited_once()
        assert ack.call_args.kwargs.get("response_action") == "errors"

    async def test_duplicate_site(self, ack: AsyncMock, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "nf_core_bot.commands.hackathon.admin.add_site",
            AsyncMock(side_effect=ValueError("already exists")),
        )
        monkeypatch.setattr("nf_core_bot.commands.hackathon.admin.list_organisers", AsyncMock(return_value=[]))
        client = AsyncMock()

        await handle_admin_site_submission(ack, _site_submission_body(), client)

        ack.assert_awaited_once()
        text = client.chat_postMessage.call_args.kwargs["text"]
        assert "already exists" in text

    async def test_syncs_organisers(self, ack: AsyncMock, monkeypatch: pytest.MonkeyPatch) -> None:
        """Organisers are added/removed to match the submitted list."""
        mock_add_site = AsyncMock()
        mock_add_org = AsyncMock()
        mock_remove_org = AsyncMock()
        monkeypatch.setattr("nf_core_bot.commands.hackathon.admin.add_site", mock_add_site)
        monkeypatch.setattr("nf_core_bot.commands.hackathon.admin.add_organiser", mock_add_org)
        monkeypatch.setattr("nf_core_bot.commands.hackathon.admin.remove_organiser", mock_remove_org)
        # Existing: U1, U2. New: U2, U3. → add U3, remove U1.
        monkeypatch.setattr(
            "nf_core_bot.commands.hackathon.admin.list_organisers",
            AsyncMock(return_value=[{"user_id": "U1"}, {"user_id": "U2"}]),
        )
        client = AsyncMock()

        await handle_admin_site_submission(ack, _site_submission_body(organiser_ids=["U2", "U3"]), client)

        ack.assert_awaited_once()
        mock_add_org.assert_awaited_once()
        assert mock_add_org.call_args[0][2] == "U3"
        mock_remove_org.assert_awaited_once()
        assert mock_remove_org.call_args[0][2] == "U1"


# ── handle_admin_delete_site ─────────────────────────────────────────


class TestAdminDeleteSite:
    async def test_success(self, ack: AsyncMock, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("nf_core_bot.commands.hackathon.admin.remove_site", AsyncMock())
        client = AsyncMock()
        meta = json.dumps({"edit_site_id": "s1", "hackathon_id": "h1"})
        body = {
            "user": {"id": "U123"},
            "view": {"id": "V123", "private_metadata": meta},
        }

        await handle_admin_delete_site(ack, body, client)

        ack.assert_awaited_once()
        client.views_update.assert_awaited_once()
        text = client.chat_postMessage.call_args.kwargs["text"]
        assert "deleted" in text.lower()
        assert "s1" in text

    async def test_missing_metadata(self, ack: AsyncMock) -> None:
        client = AsyncMock()
        body = {
            "user": {"id": "U123"},
            "view": {"id": "V123", "private_metadata": "{}"},
        }

        await handle_admin_delete_site(ack, body, client)

        ack.assert_awaited_once()
        text = client.chat_postMessage.call_args.kwargs["text"]
        assert "Could not determine" in text


# ── handle_admin_list_sites ──────────────────────────────────────────


class TestAdminListSites:
    @pytest.mark.usefixtures("_patch_known_hackathon")
    async def test_success_with_sites(
        self, ack: AsyncMock, respond: AsyncMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "nf_core_bot.commands.hackathon.admin.list_sites",
            AsyncMock(
                return_value=[
                    {"site_id": "s1", "name": "Site One", "city": "London", "country": "UK"},
                    {"site_id": "s2", "name": "Site Two", "city": "Paris", "country": "France"},
                ]
            ),
        )
        monkeypatch.setattr(
            "nf_core_bot.commands.hackathon.admin.list_organisers",
            AsyncMock(return_value=[{"user_id": "U1"}]),
        )

        await handle_admin_list_sites(ack, respond, ["h1"])

        ack.assert_awaited_once()
        text = respond.call_args.kwargs["text"]
        assert "Site One" in text
        assert "Site Two" in text
        assert "1 organiser" in text

    @pytest.mark.usefixtures("_patch_no_active")
    async def test_no_args_no_active(self, ack: AsyncMock, respond: AsyncMock) -> None:
        await handle_admin_list_sites(ack, respond, [])
        ack.assert_awaited_once()
        assert "No active hackathon" in respond.call_args.kwargs["text"]

    @pytest.mark.usefixtures("_patch_known_hackathon")
    async def test_no_sites(self, ack: AsyncMock, respond: AsyncMock, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "nf_core_bot.commands.hackathon.admin.list_sites",
            AsyncMock(return_value=[]),
        )
        await handle_admin_list_sites(ack, respond, ["h1"])
        ack.assert_awaited_once()
        assert "No sites found" in respond.call_args.kwargs["text"]
