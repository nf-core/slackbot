"""Tests for nf_core_bot.commands.hackathon.admin — admin handlers."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from nf_core_bot.commands.hackathon.admin import (
    handle_admin_add_organiser,
    handle_admin_add_site,
    handle_admin_list,
    handle_admin_list_sites,
    handle_admin_preview,
    handle_admin_remove_organiser,
    handle_admin_remove_site,
)


@pytest.fixture()
def ack() -> AsyncMock:
    return AsyncMock()


@pytest.fixture()
def respond() -> AsyncMock:
    return AsyncMock()


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
    async def test_missing_hackathon_id(self, ack: AsyncMock, respond: AsyncMock) -> None:
        client = AsyncMock()
        body = {"trigger_id": "T123", "user_id": "U123"}
        await handle_admin_preview(ack, respond, client, body, "")
        ack.assert_awaited_once()
        assert "Usage" in str(respond.call_args)

    async def test_hackathon_not_found(
        self, ack: AsyncMock, respond: AsyncMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = AsyncMock()
        body = {"trigger_id": "T123", "user_id": "U123"}
        monkeypatch.setattr("nf_core_bot.commands.hackathon.admin.get_form_metadata", lambda hid: None)
        await handle_admin_preview(ack, respond, client, body, "unknown")
        ack.assert_awaited_once()
        assert "No form YAML found" in str(respond.call_args)

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
        await handle_admin_preview(ack, respond, client, body, "h1")
        ack.assert_awaited_once()
        mock_open.assert_awaited_once()
        # Check preview=True was passed
        call_kwargs = mock_open.call_args
        assert call_kwargs[1].get("preview") is True or call_kwargs[0][-1] is True  # last positional or keyword


# ── handle_admin_add_site ────────────────────────────────────────────


class TestAdminAddSite:
    async def test_success(self, ack: AsyncMock, respond: AsyncMock, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "nf_core_bot.commands.hackathon.admin.get_form_metadata",
            lambda hid: {"hackathon_id": hid, "title": "Test"},
        )
        monkeypatch.setattr(
            "nf_core_bot.commands.hackathon.admin.add_site",
            AsyncMock(),
        )

        await handle_admin_add_site(
            ack, respond, ["h1", "stockholm-uni", "Stockholm", "University", "|", "Stockholm", "|", "Sweden"]
        )

        ack.assert_awaited_once()
        text = respond.call_args.kwargs["text"]
        assert "stockholm-uni" in text
        assert "Sweden" in text

    async def test_missing_args(self, ack: AsyncMock, respond: AsyncMock) -> None:
        await handle_admin_add_site(ack, respond, ["h1", "site-id"])

        ack.assert_awaited_once()
        assert "Usage:" in respond.call_args.kwargs["text"]

    async def test_duplicate_site(self, ack: AsyncMock, respond: AsyncMock, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "nf_core_bot.commands.hackathon.admin.get_form_metadata",
            lambda hid: {"hackathon_id": hid, "title": "Test"},
        )
        monkeypatch.setattr(
            "nf_core_bot.commands.hackathon.admin.add_site",
            AsyncMock(side_effect=ValueError("already exists")),
        )

        await handle_admin_add_site(ack, respond, ["h1", "dup", "Name", "|", "City", "|", "Country"])

        ack.assert_awaited_once()
        assert "already exists" in respond.call_args.kwargs["text"]

    async def test_bad_pipe_format(self, ack: AsyncMock, respond: AsyncMock, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "nf_core_bot.commands.hackathon.admin.get_form_metadata",
            lambda hid: {"hackathon_id": hid, "title": "Test"},
        )

        # Missing pipe separators — only two parts instead of three
        await handle_admin_add_site(ack, respond, ["h1", "site-id", "Name", "|", "City"])

        ack.assert_awaited_once()
        assert "pipe-delimited" in respond.call_args.kwargs["text"]

    async def test_hackathon_not_found(
        self, ack: AsyncMock, respond: AsyncMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "nf_core_bot.commands.hackathon.admin.get_form_metadata",
            lambda hid: None,
        )

        await handle_admin_add_site(ack, respond, ["h1", "site-id", "Name", "|", "City", "|", "Country"])

        ack.assert_awaited_once()
        assert "not found" in respond.call_args.kwargs["text"]


# ── handle_admin_remove_site ─────────────────────────────────────────


class TestAdminRemoveSite:
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

    async def test_missing_args(self, ack: AsyncMock, respond: AsyncMock) -> None:
        await handle_admin_remove_site(ack, respond, ["h1"])

        ack.assert_awaited_once()
        assert "Usage:" in respond.call_args.kwargs["text"]

    async def test_site_not_found(self, ack: AsyncMock, respond: AsyncMock, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "nf_core_bot.commands.hackathon.admin.remove_site",
            AsyncMock(side_effect=ValueError("not found")),
        )

        await handle_admin_remove_site(ack, respond, ["h1", "no-such"])

        ack.assert_awaited_once()
        assert "not found" in respond.call_args.kwargs["text"]


# ── handle_admin_list_sites ──────────────────────────────────────────


class TestAdminListSites:
    async def test_success_with_sites_and_organisers(
        self, ack: AsyncMock, respond: AsyncMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "nf_core_bot.commands.hackathon.admin.get_form_metadata",
            lambda hid: {"hackathon_id": hid, "title": "Test"},
        )
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

    async def test_missing_args(self, ack: AsyncMock, respond: AsyncMock) -> None:
        await handle_admin_list_sites(ack, respond, [])

        ack.assert_awaited_once()
        assert "Usage:" in respond.call_args.kwargs["text"]

    async def test_hackathon_not_found(
        self, ack: AsyncMock, respond: AsyncMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "nf_core_bot.commands.hackathon.admin.get_form_metadata",
            lambda hid: None,
        )

        await handle_admin_list_sites(ack, respond, ["no-such"])

        ack.assert_awaited_once()
        assert "not found" in respond.call_args.kwargs["text"]

    async def test_no_sites(self, ack: AsyncMock, respond: AsyncMock, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "nf_core_bot.commands.hackathon.admin.get_form_metadata",
            lambda hid: {"hackathon_id": hid, "title": "Test"},
        )
        monkeypatch.setattr(
            "nf_core_bot.commands.hackathon.admin.list_sites",
            AsyncMock(return_value=[]),
        )

        await handle_admin_list_sites(ack, respond, ["h1"])

        ack.assert_awaited_once()
        assert "No sites found" in respond.call_args.kwargs["text"]


# ── handle_admin_add_organiser ───────────────────────────────────────


class TestAdminAddOrganiser:
    async def test_success(self, ack: AsyncMock, respond: AsyncMock, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "nf_core_bot.commands.hackathon.admin.get_form_metadata",
            lambda hid: {"hackathon_id": hid, "title": "Test"},
        )
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

    async def test_missing_args(self, ack: AsyncMock, respond: AsyncMock) -> None:
        await handle_admin_add_organiser(ack, respond, ["h1", "s1"])

        ack.assert_awaited_once()
        assert "Usage:" in respond.call_args.kwargs["text"]

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

        await handle_admin_add_organiser(ack, respond, ["h1", "s1", "<@U01ABCDEF>"])

        ack.assert_awaited_once()
        assert "not found" in respond.call_args.kwargs["text"]

    async def test_site_not_found(self, ack: AsyncMock, respond: AsyncMock, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "nf_core_bot.commands.hackathon.admin.get_form_metadata",
            lambda hid: {"hackathon_id": hid, "title": "Test"},
        )
        monkeypatch.setattr(
            "nf_core_bot.db.sites.get_site",
            AsyncMock(return_value=None),
        )

        await handle_admin_add_organiser(ack, respond, ["h1", "s1", "<@U01ABCDEF>"])

        ack.assert_awaited_once()
        assert "Site" in respond.call_args.kwargs["text"]
        assert "not found" in respond.call_args.kwargs["text"]

    async def test_mention_with_name(self, ack: AsyncMock, respond: AsyncMock, monkeypatch: pytest.MonkeyPatch) -> None:
        """Slack mentions can include a pipe-delimited display name."""
        monkeypatch.setattr(
            "nf_core_bot.commands.hackathon.admin.get_form_metadata",
            lambda hid: {"hackathon_id": hid, "title": "Test"},
        )
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

    async def test_missing_args(self, ack: AsyncMock, respond: AsyncMock) -> None:
        await handle_admin_remove_organiser(ack, respond, ["h1", "s1"])

        ack.assert_awaited_once()
        assert "Usage:" in respond.call_args.kwargs["text"]

    async def test_bad_mention(self, ack: AsyncMock, respond: AsyncMock) -> None:
        await handle_admin_remove_organiser(ack, respond, ["h1", "s1", "bad"])

        ack.assert_awaited_once()
        assert "Could not parse" in respond.call_args.kwargs["text"]

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
