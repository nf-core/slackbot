"""Tests for nf_core_bot.commands.hackathon.list_cmd — user-facing hackathon list."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

from nf_core_bot.commands.hackathon.list_cmd import handle_list


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


# ── No hackathons ───────────────────────────────────────────────────


class TestNoHackathons:
    async def test_empty_list(
        self, ack: AsyncMock, respond: AsyncMock, client: AsyncMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "nf_core_bot.commands.hackathon.list_cmd.list_hackathons",
            AsyncMock(return_value=[]),
        )

        await handle_list(ack, respond, client, _body())

        ack.assert_awaited_once()
        assert "no hackathons" in respond.call_args.kwargs["text"].lower()

    async def test_all_archived_shows_empty(
        self, ack: AsyncMock, respond: AsyncMock, client: AsyncMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "nf_core_bot.commands.hackathon.list_cmd.list_hackathons",
            AsyncMock(
                return_value=[
                    {"hackathon_id": "h1", "title": "Old One", "status": "archived", "created_at": "2025-01-01"},
                ]
            ),
        )

        await handle_list(ack, respond, client, _body())

        ack.assert_awaited_once()
        assert "no hackathons" in respond.call_args.kwargs["text"].lower()


# ── Hackathons with status info ─────────────────────────────────────


class TestHackathonDisplay:
    async def test_shows_open_hackathon_with_registration(
        self, ack: AsyncMock, respond: AsyncMock, client: AsyncMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "nf_core_bot.commands.hackathon.list_cmd.list_hackathons",
            AsyncMock(
                return_value=[
                    {"hackathon_id": "h1", "title": "March 2026", "status": "open", "created_at": "2026-01-01"},
                ]
            ),
        )
        monkeypatch.setattr(
            "nf_core_bot.commands.hackathon.list_cmd.get_registration",
            AsyncMock(return_value={"user_id": "U_USER", "site_id": "stockholm"}),
        )
        monkeypatch.setattr(
            "nf_core_bot.commands.hackathon.list_cmd.count_registrations",
            AsyncMock(return_value=42),
        )

        await handle_list(ack, respond, client, _body())

        ack.assert_awaited_once()
        respond.assert_awaited_once()
        blocks = respond.call_args.kwargs["blocks"]
        section_texts = " ".join(
            b["text"]["text"] for b in blocks if b.get("type") == "section" and "text" in b.get("text", {})
        )
        assert "March 2026" in section_texts
        assert "Open" in section_texts
        assert "registered" in section_texts.lower()
        assert "42" in section_texts

    async def test_shows_not_registered_for_open(
        self, ack: AsyncMock, respond: AsyncMock, client: AsyncMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "nf_core_bot.commands.hackathon.list_cmd.list_hackathons",
            AsyncMock(
                return_value=[
                    {"hackathon_id": "h1", "title": "March 2026", "status": "open", "created_at": "2026-01-01"},
                ]
            ),
        )
        monkeypatch.setattr(
            "nf_core_bot.commands.hackathon.list_cmd.get_registration",
            AsyncMock(return_value=None),
        )
        monkeypatch.setattr(
            "nf_core_bot.commands.hackathon.list_cmd.count_registrations",
            AsyncMock(return_value=10),
        )

        await handle_list(ack, respond, client, _body())

        ack.assert_awaited_once()
        blocks = respond.call_args.kwargs["blocks"]
        section_texts = " ".join(
            b["text"]["text"] for b in blocks if b.get("type") == "section" and "text" in b.get("text", {})
        )
        assert "Not registered" in section_texts
        assert "register" in section_texts.lower()

    async def test_draft_hackathon_shown(
        self, ack: AsyncMock, respond: AsyncMock, client: AsyncMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "nf_core_bot.commands.hackathon.list_cmd.list_hackathons",
            AsyncMock(
                return_value=[
                    {"hackathon_id": "h1", "title": "Upcoming", "status": "draft", "created_at": "2026-03-01"},
                ]
            ),
        )
        monkeypatch.setattr(
            "nf_core_bot.commands.hackathon.list_cmd.get_registration",
            AsyncMock(return_value=None),
        )
        monkeypatch.setattr(
            "nf_core_bot.commands.hackathon.list_cmd.count_registrations",
            AsyncMock(return_value=0),
        )

        await handle_list(ack, respond, client, _body())

        ack.assert_awaited_once()
        blocks = respond.call_args.kwargs["blocks"]
        section_texts = " ".join(
            b["text"]["text"] for b in blocks if b.get("type") == "section" and "text" in b.get("text", {})
        )
        assert "Upcoming" in section_texts
        assert "Draft" in section_texts

    async def test_multiple_hackathons_mixed_status(
        self, ack: AsyncMock, respond: AsyncMock, client: AsyncMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "nf_core_bot.commands.hackathon.list_cmd.list_hackathons",
            AsyncMock(
                return_value=[
                    {"hackathon_id": "h1", "title": "Open One", "status": "open", "created_at": "2026-02-01"},
                    {"hackathon_id": "h2", "title": "Closed One", "status": "closed", "created_at": "2026-01-01"},
                    {"hackathon_id": "h3", "title": "Archived", "status": "archived", "created_at": "2025-01-01"},
                ]
            ),
        )
        monkeypatch.setattr(
            "nf_core_bot.commands.hackathon.list_cmd.get_registration",
            AsyncMock(return_value=None),
        )
        monkeypatch.setattr(
            "nf_core_bot.commands.hackathon.list_cmd.count_registrations",
            AsyncMock(return_value=5),
        )

        await handle_list(ack, respond, client, _body())

        ack.assert_awaited_once()
        blocks = respond.call_args.kwargs["blocks"]
        all_text = " ".join(str(b) for b in blocks)
        # Archived should be filtered out
        assert "Archived" not in all_text
        assert "Open One" in all_text
        assert "Closed One" in all_text

    async def test_db_error_handled(
        self, ack: AsyncMock, respond: AsyncMock, client: AsyncMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "nf_core_bot.commands.hackathon.list_cmd.list_hackathons",
            AsyncMock(side_effect=RuntimeError("db down")),
        )

        await handle_list(ack, respond, client, _body())

        ack.assert_awaited_once()
        assert "Something went wrong" in respond.call_args.kwargs["text"]
