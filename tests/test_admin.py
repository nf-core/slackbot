"""Tests for nf_core_bot.commands.hackathon.admin — all 10 admin handlers."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from nf_core_bot.commands.hackathon.admin import (
    handle_admin_add_organiser,
    handle_admin_add_site,
    handle_admin_archive,
    handle_admin_close,
    handle_admin_create,
    handle_admin_list,
    handle_admin_list_sites,
    handle_admin_open,
    handle_admin_remove_organiser,
    handle_admin_remove_site,
)
from nf_core_bot.forms.loader import FormDefinition, FormStep


@pytest.fixture()
def ack() -> AsyncMock:
    return AsyncMock()


@pytest.fixture()
def respond() -> AsyncMock:
    return AsyncMock()


# ── handle_admin_create ──────────────────────────────────────────────


class TestAdminCreate:
    async def test_success(self, ack: AsyncMock, respond: AsyncMock, monkeypatch: pytest.MonkeyPatch) -> None:
        form = FormDefinition(hackathon="march-2026", steps=[FormStep(id="s1", title="Step 1")])
        monkeypatch.setattr(
            "nf_core_bot.commands.hackathon.admin.load_form_by_hackathon",
            lambda hid: form,
        )
        monkeypatch.setattr(
            "nf_core_bot.commands.hackathon.admin.create_hackathon",
            AsyncMock(),
        )

        await handle_admin_create(ack, respond, ["march-2026", "March", "2026", "Hackathon"])

        ack.assert_awaited_once()
        respond.assert_awaited_once()
        text = respond.call_args.kwargs["text"]
        assert "march-2026" in text
        assert "draft" in text
        assert "1 steps" in text

    async def test_missing_args(self, ack: AsyncMock, respond: AsyncMock) -> None:
        await handle_admin_create(ack, respond, ["only-id"])

        ack.assert_awaited_once()
        respond.assert_awaited_once()
        assert "Usage:" in respond.call_args.kwargs["text"]

    async def test_missing_all_args(self, ack: AsyncMock, respond: AsyncMock) -> None:
        await handle_admin_create(ack, respond, [])

        ack.assert_awaited_once()
        respond.assert_awaited_once()
        assert "Usage:" in respond.call_args.kwargs["text"]

    async def test_duplicate_id(self, ack: AsyncMock, respond: AsyncMock, monkeypatch: pytest.MonkeyPatch) -> None:
        form = FormDefinition(hackathon="march-2026", steps=[FormStep(id="s1", title="Step 1")])
        monkeypatch.setattr(
            "nf_core_bot.commands.hackathon.admin.load_form_by_hackathon",
            lambda hid: form,
        )
        monkeypatch.setattr(
            "nf_core_bot.commands.hackathon.admin.create_hackathon",
            AsyncMock(side_effect=ValueError("already exists")),
        )

        await handle_admin_create(ack, respond, ["march-2026", "March", "Hackathon"])

        ack.assert_awaited_once()
        respond.assert_awaited_once()
        assert "already exists" in respond.call_args.kwargs["text"]

    async def test_missing_yaml(self, ack: AsyncMock, respond: AsyncMock, monkeypatch: pytest.MonkeyPatch) -> None:
        def _no_yaml(hid: str) -> None:
            raise FileNotFoundError("no yaml")

        monkeypatch.setattr(
            "nf_core_bot.commands.hackathon.admin.load_form_by_hackathon",
            _no_yaml,
        )

        await handle_admin_create(ack, respond, ["march-2026", "March", "Hackathon"])

        ack.assert_awaited_once()
        respond.assert_awaited_once()
        assert "No form YAML found" in respond.call_args.kwargs["text"]


# ── handle_admin_open ────────────────────────────────────────────────


class TestAdminOpen:
    async def test_success(self, ack: AsyncMock, respond: AsyncMock, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "nf_core_bot.commands.hackathon.admin.get_hackathon",
            AsyncMock(return_value={"hackathon_id": "h1", "status": "draft"}),
        )
        monkeypatch.setattr(
            "nf_core_bot.commands.hackathon.admin.update_hackathon_status",
            AsyncMock(),
        )

        await handle_admin_open(ack, respond, ["h1"])

        ack.assert_awaited_once()
        respond.assert_awaited_once()
        text = respond.call_args.kwargs["text"]
        assert "open" in text
        assert "draft" in text

    async def test_missing_args(self, ack: AsyncMock, respond: AsyncMock) -> None:
        await handle_admin_open(ack, respond, [])

        ack.assert_awaited_once()
        assert "Usage:" in respond.call_args.kwargs["text"]

    async def test_hackathon_not_found(
        self, ack: AsyncMock, respond: AsyncMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "nf_core_bot.commands.hackathon.admin.get_hackathon",
            AsyncMock(return_value=None),
        )

        await handle_admin_open(ack, respond, ["no-such"])

        ack.assert_awaited_once()
        assert "not found" in respond.call_args.kwargs["text"]

    async def test_wrong_status(self, ack: AsyncMock, respond: AsyncMock, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "nf_core_bot.commands.hackathon.admin.get_hackathon",
            AsyncMock(return_value={"hackathon_id": "h1", "status": "archived"}),
        )

        await handle_admin_open(ack, respond, ["h1"])

        ack.assert_awaited_once()
        assert "Cannot open" in respond.call_args.kwargs["text"]

    async def test_open_from_closed(self, ack: AsyncMock, respond: AsyncMock, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "nf_core_bot.commands.hackathon.admin.get_hackathon",
            AsyncMock(return_value={"hackathon_id": "h1", "status": "closed"}),
        )
        monkeypatch.setattr(
            "nf_core_bot.commands.hackathon.admin.update_hackathon_status",
            AsyncMock(),
        )

        await handle_admin_open(ack, respond, ["h1"])

        ack.assert_awaited_once()
        text = respond.call_args.kwargs["text"]
        assert "open" in text
        assert "closed" in text


# ── handle_admin_close ───────────────────────────────────────────────


class TestAdminClose:
    async def test_success(self, ack: AsyncMock, respond: AsyncMock, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "nf_core_bot.commands.hackathon.admin.get_hackathon",
            AsyncMock(return_value={"hackathon_id": "h1", "status": "open"}),
        )
        monkeypatch.setattr(
            "nf_core_bot.commands.hackathon.admin.update_hackathon_status",
            AsyncMock(),
        )

        await handle_admin_close(ack, respond, ["h1"])

        ack.assert_awaited_once()
        text = respond.call_args.kwargs["text"]
        assert "closed" in text

    async def test_missing_args(self, ack: AsyncMock, respond: AsyncMock) -> None:
        await handle_admin_close(ack, respond, [])

        ack.assert_awaited_once()
        assert "Usage:" in respond.call_args.kwargs["text"]

    async def test_hackathon_not_found(
        self, ack: AsyncMock, respond: AsyncMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "nf_core_bot.commands.hackathon.admin.get_hackathon",
            AsyncMock(return_value=None),
        )

        await handle_admin_close(ack, respond, ["no-such"])

        ack.assert_awaited_once()
        assert "not found" in respond.call_args.kwargs["text"]

    async def test_wrong_status(self, ack: AsyncMock, respond: AsyncMock, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "nf_core_bot.commands.hackathon.admin.get_hackathon",
            AsyncMock(return_value={"hackathon_id": "h1", "status": "draft"}),
        )

        await handle_admin_close(ack, respond, ["h1"])

        ack.assert_awaited_once()
        assert "Cannot close" in respond.call_args.kwargs["text"]


# ── handle_admin_archive ─────────────────────────────────────────────


class TestAdminArchive:
    async def test_success(self, ack: AsyncMock, respond: AsyncMock, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "nf_core_bot.commands.hackathon.admin.get_hackathon",
            AsyncMock(return_value={"hackathon_id": "h1", "status": "closed"}),
        )
        monkeypatch.setattr(
            "nf_core_bot.commands.hackathon.admin.update_hackathon_status",
            AsyncMock(),
        )

        await handle_admin_archive(ack, respond, ["h1"])

        ack.assert_awaited_once()
        text = respond.call_args.kwargs["text"]
        assert "archived" in text

    async def test_missing_args(self, ack: AsyncMock, respond: AsyncMock) -> None:
        await handle_admin_archive(ack, respond, [])

        ack.assert_awaited_once()
        assert "Usage:" in respond.call_args.kwargs["text"]

    async def test_hackathon_not_found(
        self, ack: AsyncMock, respond: AsyncMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "nf_core_bot.commands.hackathon.admin.get_hackathon",
            AsyncMock(return_value=None),
        )

        await handle_admin_archive(ack, respond, ["no-such"])

        ack.assert_awaited_once()
        assert "not found" in respond.call_args.kwargs["text"]


# ── handle_admin_list ────────────────────────────────────────────────


class TestAdminList:
    async def test_empty_list(self, ack: AsyncMock, respond: AsyncMock, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "nf_core_bot.commands.hackathon.admin.list_hackathons",
            AsyncMock(return_value=[]),
        )

        await handle_admin_list(ack, respond)

        ack.assert_awaited_once()
        assert "No hackathons found" in respond.call_args.kwargs["text"]

    async def test_multiple_hackathons(
        self, ack: AsyncMock, respond: AsyncMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "nf_core_bot.commands.hackathon.admin.list_hackathons",
            AsyncMock(
                return_value=[
                    {"hackathon_id": "h1", "title": "First", "status": "open", "created_at": "2026-01-01"},
                    {"hackathon_id": "h2", "title": "Second", "status": "draft", "created_at": "2026-02-01"},
                ]
            ),
        )

        await handle_admin_list(ack, respond)

        ack.assert_awaited_once()
        text = respond.call_args.kwargs["text"]
        assert "h1" in text
        assert "h2" in text
        assert "First" in text
        assert "Second" in text


# ── handle_admin_add_site ────────────────────────────────────────────


class TestAdminAddSite:
    async def test_success(self, ack: AsyncMock, respond: AsyncMock, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "nf_core_bot.commands.hackathon.admin.get_hackathon",
            AsyncMock(return_value={"hackathon_id": "h1"}),
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
            "nf_core_bot.commands.hackathon.admin.get_hackathon",
            AsyncMock(return_value={"hackathon_id": "h1"}),
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
            "nf_core_bot.commands.hackathon.admin.get_hackathon",
            AsyncMock(return_value={"hackathon_id": "h1"}),
        )

        # Missing pipe separators — only two parts instead of three
        await handle_admin_add_site(ack, respond, ["h1", "site-id", "Name", "|", "City"])

        ack.assert_awaited_once()
        assert "pipe-delimited" in respond.call_args.kwargs["text"]

    async def test_hackathon_not_found(
        self, ack: AsyncMock, respond: AsyncMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "nf_core_bot.commands.hackathon.admin.get_hackathon",
            AsyncMock(return_value=None),
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
            "nf_core_bot.commands.hackathon.admin.get_hackathon",
            AsyncMock(return_value={"hackathon_id": "h1"}),
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
            "nf_core_bot.commands.hackathon.admin.get_hackathon",
            AsyncMock(return_value=None),
        )

        await handle_admin_list_sites(ack, respond, ["no-such"])

        ack.assert_awaited_once()
        assert "not found" in respond.call_args.kwargs["text"]

    async def test_no_sites(self, ack: AsyncMock, respond: AsyncMock, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "nf_core_bot.commands.hackathon.admin.get_hackathon",
            AsyncMock(return_value={"hackathon_id": "h1"}),
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
            "nf_core_bot.commands.hackathon.admin.get_hackathon",
            AsyncMock(return_value={"hackathon_id": "h1"}),
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
            "nf_core_bot.commands.hackathon.admin.get_hackathon",
            AsyncMock(return_value=None),
        )

        await handle_admin_add_organiser(ack, respond, ["h1", "s1", "<@U01ABCDEF>"])

        ack.assert_awaited_once()
        assert "not found" in respond.call_args.kwargs["text"]

    async def test_site_not_found(self, ack: AsyncMock, respond: AsyncMock, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "nf_core_bot.commands.hackathon.admin.get_hackathon",
            AsyncMock(return_value={"hackathon_id": "h1"}),
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
            "nf_core_bot.commands.hackathon.admin.get_hackathon",
            AsyncMock(return_value={"hackathon_id": "h1"}),
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
