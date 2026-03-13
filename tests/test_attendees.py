"""Tests for nf_core_bot.commands.hackathon.attendees — attendee listing."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

from nf_core_bot.commands.hackathon.attendees import handle_attendees


@pytest.fixture()
def ack() -> AsyncMock:
    return AsyncMock()


@pytest.fixture()
def respond() -> AsyncMock:
    return AsyncMock()


@pytest.fixture()
def client() -> AsyncMock:
    return AsyncMock()


def _body(user_id: str = "U_USER") -> dict[str, Any]:
    return {"user_id": user_id}


# ── No active hackathon ─────────────────────────────────────────────


class TestNoHackathon:
    async def test_no_active_hackathon_no_id(
        self, ack: AsyncMock, respond: AsyncMock, client: AsyncMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "nf_core_bot.commands.hackathon.attendees.get_active_hackathon",
            AsyncMock(return_value=None),
        )

        await handle_attendees(ack, respond, client, _body(), [])

        ack.assert_awaited_once()
        assert "No hackathon is currently open" in respond.call_args.kwargs["text"]

    async def test_explicit_id_not_found(
        self, ack: AsyncMock, respond: AsyncMock, client: AsyncMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "nf_core_bot.commands.hackathon.attendees.get_hackathon",
            AsyncMock(return_value=None),
        )

        await handle_attendees(ack, respond, client, _body(), ["no-such"])

        ack.assert_awaited_once()
        assert "not found" in respond.call_args.kwargs["text"]


# ── Permission checks ───────────────────────────────────────────────


class TestPermissions:
    async def test_not_authorised(
        self, ack: AsyncMock, respond: AsyncMock, client: AsyncMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "nf_core_bot.commands.hackathon.attendees.get_active_hackathon",
            AsyncMock(return_value={"hackathon_id": "h1", "title": "Test"}),
        )
        monkeypatch.setattr(
            "nf_core_bot.commands.hackathon.attendees.is_core_team",
            AsyncMock(return_value=False),
        )
        monkeypatch.setattr(
            "nf_core_bot.commands.hackathon.attendees.is_organiser_any_site",
            AsyncMock(return_value=False),
        )
        monkeypatch.setattr(
            "nf_core_bot.commands.hackathon.attendees.list_sites",
            AsyncMock(return_value=[]),
        )

        await handle_attendees(ack, respond, client, _body(), [])

        ack.assert_awaited_once()
        assert "permission" in respond.call_args.kwargs["text"].lower()


# ── Core-team full view ─────────────────────────────────────────────


class TestCoreTeamView:
    async def test_core_team_sees_all(
        self, ack: AsyncMock, respond: AsyncMock, client: AsyncMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "nf_core_bot.commands.hackathon.attendees.get_active_hackathon",
            AsyncMock(return_value={"hackathon_id": "h1", "title": "March 2026"}),
        )
        monkeypatch.setattr(
            "nf_core_bot.commands.hackathon.attendees.is_core_team",
            AsyncMock(return_value=True),
        )
        monkeypatch.setattr(
            "nf_core_bot.commands.hackathon.attendees.list_sites",
            AsyncMock(return_value=[{"site_id": "s1", "name": "London"}]),
        )
        monkeypatch.setattr(
            "nf_core_bot.commands.hackathon.attendees.list_registrations",
            AsyncMock(
                return_value=[
                    {
                        "user_id": "U1",
                        "site_id": "s1",
                        "registered_at": "2026-01-15T10:00:00",
                        "profile_data": {"slack_display_name": "Alice"},
                    },
                    {
                        "user_id": "U2",
                        "site_id": None,
                        "registered_at": "2026-01-16T10:00:00",
                        "profile_data": {"slack_display_name": "Bob"},
                    },
                ]
            ),
        )

        await handle_attendees(ack, respond, client, _body("U_ADMIN"), [])

        ack.assert_awaited_once()
        respond.assert_awaited_once()
        blocks = respond.call_args.kwargs["blocks"]
        # Should contain a header block
        header_texts = [b["text"]["text"] for b in blocks if b.get("type") == "header"]
        assert any("March 2026" in t for t in header_texts)
        # Should have section blocks with registrant info
        section_texts = " ".join(
            b["text"]["text"] for b in blocks if b.get("type") == "section" and "text" in b.get("text", {})
        )
        assert "Alice" in section_texts
        assert "Bob" in section_texts
        assert "Total registrations" in section_texts or "2" in section_texts


# ── Site organiser scoped view ──────────────────────────────────────


class TestOrganiserView:
    async def test_organiser_sees_only_their_site(
        self, ack: AsyncMock, respond: AsyncMock, client: AsyncMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "nf_core_bot.commands.hackathon.attendees.get_active_hackathon",
            AsyncMock(return_value={"hackathon_id": "h1", "title": "March 2026"}),
        )
        monkeypatch.setattr(
            "nf_core_bot.commands.hackathon.attendees.is_core_team",
            AsyncMock(return_value=False),
        )
        monkeypatch.setattr(
            "nf_core_bot.commands.hackathon.attendees.is_organiser_any_site",
            AsyncMock(return_value=True),
        )
        monkeypatch.setattr(
            "nf_core_bot.commands.hackathon.attendees.list_sites",
            AsyncMock(
                return_value=[
                    {"site_id": "s1", "name": "London"},
                    {"site_id": "s2", "name": "Paris"},
                ]
            ),
        )
        monkeypatch.setattr(
            "nf_core_bot.commands.hackathon.attendees.is_site_organiser",
            AsyncMock(side_effect=lambda uid, hid, sid: sid == "s1"),
        )
        monkeypatch.setattr(
            "nf_core_bot.commands.hackathon.attendees.list_registrations_by_site",
            AsyncMock(
                return_value=[
                    {
                        "user_id": "U1",
                        "site_id": "s1",
                        "registered_at": "2026-01-15T10:00:00",
                        "profile_data": {"slack_display_name": "Alice"},
                    },
                ]
            ),
        )

        await handle_attendees(ack, respond, client, _body("U_ORG"), [])

        ack.assert_awaited_once()
        respond.assert_awaited_once()
        blocks = respond.call_args.kwargs["blocks"]
        section_texts = " ".join(
            b["text"]["text"] for b in blocks if b.get("type") == "section" and "text" in b.get("text", {})
        )
        assert "London" in section_texts
        assert "Alice" in section_texts


# ── Explicit hackathon ID ───────────────────────────────────────────


class TestExplicitHackathonId:
    async def test_hackathon_id_provided(
        self, ack: AsyncMock, respond: AsyncMock, client: AsyncMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "nf_core_bot.commands.hackathon.attendees.get_hackathon",
            AsyncMock(return_value={"hackathon_id": "h1", "title": "March 2026"}),
        )
        monkeypatch.setattr(
            "nf_core_bot.commands.hackathon.attendees.is_core_team",
            AsyncMock(return_value=True),
        )
        monkeypatch.setattr(
            "nf_core_bot.commands.hackathon.attendees.list_sites",
            AsyncMock(return_value=[]),
        )
        monkeypatch.setattr(
            "nf_core_bot.commands.hackathon.attendees.list_registrations",
            AsyncMock(return_value=[]),
        )

        await handle_attendees(ack, respond, client, _body("U_ADMIN"), ["h1"])

        ack.assert_awaited_once()
        respond.assert_awaited_once()
        # Verify blocks were returned (even with no registrations)
        blocks = respond.call_args.kwargs["blocks"]
        assert len(blocks) > 0
