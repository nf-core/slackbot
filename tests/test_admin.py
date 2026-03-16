"""Tests for nf_core_bot.commands.hackathon.admin — admin handlers."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from nf_core_bot.commands.hackathon.admin import (
    _resolve_hackathon_id,
    handle_admin_add_organiser,
    handle_admin_add_site,
    handle_admin_add_site_submission,
    handle_admin_list,
    handle_admin_list_sites,
    handle_admin_preview,
    handle_admin_remove_organiser,
    handle_admin_remove_site,
)

# ── Shared helpers ──────────────────────────────────────────────────

_KNOWN_HACKATHON = {"hackathon_id": "h1", "title": "Test"}


def _meta_for_h1(hid: str) -> dict[str, str] | None:
    """Monkeypatch helper: recognise ``h1`` as a valid hackathon."""
    return {"hackathon_id": hid, "title": "Test"} if hid == "h1" else None


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
        assert "First" in text
        assert "Second" in text
        assert "open" in text
        assert "draft" in text
        assert "2026-03-11" in text
        assert "2026-06-01" in text
        assert "https://nf-co.re/events/2026/hackathon-march-2026" in text


# ── handle_admin_preview ─────────────────────────────────────────────


class TestAdminPreview:
    @pytest.mark.usefixtures("_patch_no_active")
    async def test_no_args_no_active(self, ack: AsyncMock, respond: AsyncMock) -> None:
        """No hackathon-id provided and no active hackathon → usage error."""
        client = AsyncMock()
        body = {"trigger_id": "T123", "user_id": "U123"}
        await handle_admin_preview(ack, respond, client, body, [])
        ack.assert_awaited_once()
        text = str(respond.call_args)
        assert "Usage" in text
        assert "No active hackathon" in text

    async def test_no_args_defaults_to_active(
        self, ack: AsyncMock, respond: AsyncMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """No hackathon-id → uses the active hackathon."""
        client = AsyncMock()
        body = {"trigger_id": "T123", "user_id": "U123"}
        monkeypatch.setattr(
            "nf_core_bot.commands.hackathon.admin.get_active_form",
            lambda: {"hackathon_id": "active-hack"},
        )
        monkeypatch.setattr(
            "nf_core_bot.commands.hackathon.admin.get_form_metadata",
            lambda hid: {"hackathon_id": hid, "title": "Active Hackathon"},
        )
        mock_open = AsyncMock()
        monkeypatch.setattr("nf_core_bot.forms.handler.open_registration_modal", mock_open)

        await handle_admin_preview(ack, respond, client, body, [])

        ack.assert_awaited_once()
        mock_open.assert_awaited_once()
        assert mock_open.call_args[0][2] == "active-hack"

    async def test_hackathon_not_found(
        self, ack: AsyncMock, respond: AsyncMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Explicit unknown hackathon-id and no active form → not-found message."""
        client = AsyncMock()
        body = {"trigger_id": "T123", "user_id": "U123"}
        monkeypatch.setattr("nf_core_bot.commands.hackathon.admin.get_form_metadata", lambda hid: None)
        monkeypatch.setattr("nf_core_bot.commands.hackathon.admin.get_active_form", lambda: None)
        await handle_admin_preview(ack, respond, client, body, ["unknown"])
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
        # Check preview=True was passed
        call_kwargs = mock_open.call_args
        assert call_kwargs[1].get("preview") is True or call_kwargs[0][-1] is True  # last positional or keyword


# ── handle_admin_add_site ────────────────────────────────────────────


class TestAdminAddSite:
    """Test the add-site modal flow (open + submission)."""

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
        assert view["callback_id"] == "admin_add_site"

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

    async def test_submission_success(self, ack: AsyncMock, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "nf_core_bot.commands.hackathon.admin.add_site",
            AsyncMock(),
        )
        client = AsyncMock()
        body = {
            "user": {"id": "U123"},
            "view": {
                "state": {
                    "values": {
                        "hackathon": {"hackathon": {"selected_option": {"value": "h1"}}},
                        "site_id": {"site_id": {"value": "stockholm-uni"}},
                        "name": {"name": {"value": "Stockholm University"}},
                        "city": {"city": {"value": "Stockholm"}},
                        "country": {"country": {"selected_option": {"value": "sweden"}}},
                    }
                }
            },
        }

        await handle_admin_add_site_submission(ack, body, client)

        ack.assert_awaited_once()
        client.chat_postMessage.assert_awaited_once()
        text = client.chat_postMessage.call_args.kwargs["text"]
        assert "stockholm-uni" in text
        assert "h1" in text

    async def test_submission_bad_site_id(self, ack: AsyncMock) -> None:
        client = AsyncMock()
        body = {
            "user": {"id": "U123"},
            "view": {
                "state": {
                    "values": {
                        "hackathon": {"hackathon": {"selected_option": {"value": "h1"}}},
                        "site_id": {"site_id": {"value": "Bad Site!"}},
                        "name": {"name": {"value": "Test"}},
                        "city": {"city": {"value": "City"}},
                        "country": {"country": {"selected_option": {"value": "sweden"}}},
                    }
                }
            },
        }

        await handle_admin_add_site_submission(ack, body, client)

        # Should return validation errors, not ack normally.
        ack.assert_awaited_once()
        assert ack.call_args.kwargs.get("response_action") == "errors"

    async def test_submission_duplicate_site(self, ack: AsyncMock, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "nf_core_bot.commands.hackathon.admin.add_site",
            AsyncMock(side_effect=ValueError("already exists")),
        )
        client = AsyncMock()
        body = {
            "user": {"id": "U123"},
            "view": {
                "state": {
                    "values": {
                        "hackathon": {"hackathon": {"selected_option": {"value": "h1"}}},
                        "site_id": {"site_id": {"value": "dup"}},
                        "name": {"name": {"value": "Dup Site"}},
                        "city": {"city": {"value": "City"}},
                        "country": {"country": {"selected_option": {"value": "sweden"}}},
                    }
                }
            },
        }

        await handle_admin_add_site_submission(ack, body, client)

        ack.assert_awaited_once()
        text = client.chat_postMessage.call_args.kwargs["text"]
        assert "already exists" in text


# ── handle_admin_remove_site ─────────────────────────────────────────


class TestAdminRemoveSite:
    @pytest.mark.usefixtures("_patch_known_hackathon")
    async def test_success(self, ack: AsyncMock, respond: AsyncMock, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "nf_core_bot.commands.hackathon.admin.remove_site",
            AsyncMock(),
        )

        await handle_admin_remove_site(ack, respond, ["h1", "stockholm-uni"])

        ack.assert_awaited_once()
        text = respond.call_args.kwargs["text"]
        assert "stockholm-uni" in text
        assert "removed" in text.lower()

    @pytest.mark.usefixtures("_patch_known_hackathon")
    async def test_success_without_hackathon_id(
        self, ack: AsyncMock, respond: AsyncMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Omit hackathon-id — should default to active hackathon."""
        monkeypatch.setattr(
            "nf_core_bot.commands.hackathon.admin.get_active_form",
            lambda: {"hackathon_id": "active-hack"},
        )
        monkeypatch.setattr(
            "nf_core_bot.commands.hackathon.admin.get_form_metadata",
            _meta_for_h1,
        )
        monkeypatch.setattr(
            "nf_core_bot.commands.hackathon.admin.remove_site",
            AsyncMock(),
        )

        await handle_admin_remove_site(ack, respond, ["stockholm-uni"])

        ack.assert_awaited_once()
        text = respond.call_args.kwargs["text"]
        assert "stockholm-uni" in text
        assert "removed" in text.lower()
        assert "active-hack" in text

    @pytest.mark.usefixtures("_patch_known_hackathon", "_patch_no_active")
    async def test_missing_site_id(self, ack: AsyncMock, respond: AsyncMock) -> None:
        """hackathon-id consumed but no site-id left."""
        await handle_admin_remove_site(ack, respond, ["h1"])

        ack.assert_awaited_once()
        assert "Usage:" in respond.call_args.kwargs["text"]

    @pytest.mark.usefixtures("_patch_known_hackathon")
    async def test_site_not_found(self, ack: AsyncMock, respond: AsyncMock, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "nf_core_bot.commands.hackathon.admin.remove_site",
            AsyncMock(side_effect=ValueError("not found")),
        )

        await handle_admin_remove_site(ack, respond, ["h1", "no-such"])

        ack.assert_awaited_once()
        assert "not found" in respond.call_args.kwargs["text"]

    @pytest.mark.usefixtures("_patch_no_active")
    async def test_no_args_no_active(self, ack: AsyncMock, respond: AsyncMock) -> None:
        await handle_admin_remove_site(ack, respond, [])

        ack.assert_awaited_once()
        assert "No active hackathon" in respond.call_args.kwargs["text"]


# ── handle_admin_list_sites ──────────────────────────────────────────


class TestAdminListSites:
    @pytest.mark.usefixtures("_patch_known_hackathon")
    async def test_success_with_sites_and_organisers(
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

    async def test_defaults_to_active(
        self, ack: AsyncMock, respond: AsyncMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """No args — defaults to the active hackathon."""
        monkeypatch.setattr(
            "nf_core_bot.commands.hackathon.admin.get_active_form",
            lambda: {"hackathon_id": "active-hack"},
        )
        monkeypatch.setattr(
            "nf_core_bot.commands.hackathon.admin.get_form_metadata",
            lambda hid: {"hackathon_id": hid, "title": "Active"} if hid == "active-hack" else None,
        )
        monkeypatch.setattr(
            "nf_core_bot.commands.hackathon.admin.list_sites",
            AsyncMock(return_value=[{"site_id": "s1", "name": "S1", "city": "C", "country": "X"}]),
        )
        monkeypatch.setattr(
            "nf_core_bot.commands.hackathon.admin.list_organisers",
            AsyncMock(return_value=[]),
        )

        await handle_admin_list_sites(ack, respond, [])

        ack.assert_awaited_once()
        text = respond.call_args.kwargs["text"]
        assert "active-hack" in text

    @pytest.mark.usefixtures("_patch_no_active")
    async def test_no_args_no_active(self, ack: AsyncMock, respond: AsyncMock) -> None:
        await handle_admin_list_sites(ack, respond, [])

        ack.assert_awaited_once()
        assert "No active hackathon" in respond.call_args.kwargs["text"]

    async def test_hackathon_not_found(
        self, ack: AsyncMock, respond: AsyncMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "nf_core_bot.commands.hackathon.admin.get_form_metadata",
            lambda hid: None,
        )
        monkeypatch.setattr(
            "nf_core_bot.commands.hackathon.admin.get_active_form",
            lambda: None,
        )

        await handle_admin_list_sites(ack, respond, ["no-such"])

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


# ── handle_admin_add_organiser ───────────────────────────────────────


class TestAdminAddOrganiser:
    @pytest.mark.usefixtures("_patch_known_hackathon")
    async def test_success(self, ack: AsyncMock, respond: AsyncMock, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "nf_core_bot.db.sites.get_site",
            AsyncMock(return_value={"site_id": "s1"}),
        )
        monkeypatch.setattr(
            "nf_core_bot.commands.hackathon.admin.add_organiser",
            AsyncMock(),
        )

        await handle_admin_add_organiser(ack, respond, ["h1", "s1", "<@U01ABCDEF>"])

        ack.assert_awaited_once()
        text = respond.call_args.kwargs["text"]
        assert "<@U01ABCDEF>" in text
        assert "organiser" in text.lower()

    @pytest.mark.usefixtures("_patch_known_hackathon")
    async def test_success_without_hackathon_id(
        self, ack: AsyncMock, respond: AsyncMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Omit hackathon-id — should default to active hackathon."""
        monkeypatch.setattr(
            "nf_core_bot.commands.hackathon.admin.get_active_form",
            lambda: {"hackathon_id": "active-hack"},
        )
        monkeypatch.setattr(
            "nf_core_bot.commands.hackathon.admin.get_form_metadata",
            lambda hid: {"hackathon_id": hid, "title": "Active"} if hid == "active-hack" else None,
        )
        monkeypatch.setattr(
            "nf_core_bot.db.sites.get_site",
            AsyncMock(return_value={"site_id": "s1"}),
        )
        monkeypatch.setattr(
            "nf_core_bot.commands.hackathon.admin.add_organiser",
            AsyncMock(),
        )

        await handle_admin_add_organiser(ack, respond, ["s1", "<@U01ABCDEF>"])

        ack.assert_awaited_once()
        text = respond.call_args.kwargs["text"]
        assert "<@U01ABCDEF>" in text
        assert "active-hack" in text

    @pytest.mark.usefixtures("_patch_known_hackathon")
    async def test_missing_args(self, ack: AsyncMock, respond: AsyncMock) -> None:
        await handle_admin_add_organiser(ack, respond, ["h1", "s1"])

        ack.assert_awaited_once()
        assert "Usage:" in respond.call_args.kwargs["text"]

    @pytest.mark.usefixtures("_patch_known_hackathon")
    async def test_bad_mention_format(self, ack: AsyncMock, respond: AsyncMock) -> None:
        await handle_admin_add_organiser(ack, respond, ["h1", "s1", "not-a-mention"])

        ack.assert_awaited_once()
        assert "Could not parse" in respond.call_args.kwargs["text"]

    async def test_hackathon_not_found(
        self, ack: AsyncMock, respond: AsyncMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "nf_core_bot.commands.hackathon.admin.get_form_metadata",
            lambda hid: None,
        )
        monkeypatch.setattr(
            "nf_core_bot.commands.hackathon.admin.get_active_form",
            lambda: None,
        )

        await handle_admin_add_organiser(ack, respond, ["h1", "s1", "<@U01ABCDEF>"])

        ack.assert_awaited_once()
        assert "No active hackathon" in respond.call_args.kwargs["text"]

    @pytest.mark.usefixtures("_patch_known_hackathon")
    async def test_site_not_found(self, ack: AsyncMock, respond: AsyncMock, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "nf_core_bot.db.sites.get_site",
            AsyncMock(return_value=None),
        )

        await handle_admin_add_organiser(ack, respond, ["h1", "s1", "<@U01ABCDEF>"])

        ack.assert_awaited_once()
        assert "Site" in respond.call_args.kwargs["text"]
        assert "not found" in respond.call_args.kwargs["text"]

    @pytest.mark.usefixtures("_patch_known_hackathon")
    async def test_mention_with_name(self, ack: AsyncMock, respond: AsyncMock, monkeypatch: pytest.MonkeyPatch) -> None:
        """Slack mentions can include a pipe-delimited display name."""
        monkeypatch.setattr(
            "nf_core_bot.db.sites.get_site",
            AsyncMock(return_value={"site_id": "s1"}),
        )
        monkeypatch.setattr(
            "nf_core_bot.commands.hackathon.admin.add_organiser",
            AsyncMock(),
        )

        await handle_admin_add_organiser(ack, respond, ["h1", "s1", "<@U01ABCDEF|phil>"])

        ack.assert_awaited_once()
        text = respond.call_args.kwargs["text"]
        assert "<@U01ABCDEF>" in text


# ── handle_admin_remove_organiser ────────────────────────────────────


class TestAdminRemoveOrganiser:
    @pytest.mark.usefixtures("_patch_known_hackathon")
    async def test_success(self, ack: AsyncMock, respond: AsyncMock, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "nf_core_bot.commands.hackathon.admin.remove_organiser",
            AsyncMock(),
        )

        await handle_admin_remove_organiser(ack, respond, ["h1", "s1", "<@U01ABCDEF>"])

        ack.assert_awaited_once()
        text = respond.call_args.kwargs["text"]
        assert "<@U01ABCDEF>" in text
        assert "removed" in text.lower()

    @pytest.mark.usefixtures("_patch_known_hackathon")
    async def test_success_without_hackathon_id(
        self, ack: AsyncMock, respond: AsyncMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Omit hackathon-id — should default to active hackathon."""
        monkeypatch.setattr(
            "nf_core_bot.commands.hackathon.admin.get_active_form",
            lambda: {"hackathon_id": "active-hack"},
        )
        monkeypatch.setattr(
            "nf_core_bot.commands.hackathon.admin.get_form_metadata",
            lambda hid: {"hackathon_id": hid, "title": "Active"} if hid == "active-hack" else None,
        )
        monkeypatch.setattr(
            "nf_core_bot.commands.hackathon.admin.remove_organiser",
            AsyncMock(),
        )

        await handle_admin_remove_organiser(ack, respond, ["s1", "<@U01ABCDEF>"])

        ack.assert_awaited_once()
        text = respond.call_args.kwargs["text"]
        assert "<@U01ABCDEF>" in text
        assert "active-hack" in text

    @pytest.mark.usefixtures("_patch_known_hackathon")
    async def test_missing_args(self, ack: AsyncMock, respond: AsyncMock) -> None:
        await handle_admin_remove_organiser(ack, respond, ["h1", "s1"])

        ack.assert_awaited_once()
        assert "Usage:" in respond.call_args.kwargs["text"]

    @pytest.mark.usefixtures("_patch_known_hackathon")
    async def test_bad_mention(self, ack: AsyncMock, respond: AsyncMock) -> None:
        await handle_admin_remove_organiser(ack, respond, ["h1", "s1", "bad"])

        ack.assert_awaited_once()
        assert "Could not parse" in respond.call_args.kwargs["text"]

    @pytest.mark.usefixtures("_patch_known_hackathon")
    async def test_organiser_not_found(
        self, ack: AsyncMock, respond: AsyncMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "nf_core_bot.commands.hackathon.admin.remove_organiser",
            AsyncMock(side_effect=ValueError("not found")),
        )

        await handle_admin_remove_organiser(ack, respond, ["h1", "s1", "<@U01ABCDEF>"])

        ack.assert_awaited_once()
        assert "not found" in respond.call_args.kwargs["text"]
