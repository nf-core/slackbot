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
            "nf_core_bot.commands.hackathon.list_cmd.list_all_forms",
            lambda: [],
        )

        await handle_list(ack, respond, client, _body())

        ack.assert_awaited_once()
        assert "no hackathons" in respond.call_args.kwargs["text"].lower()

    async def test_draft_and_archived_hidden(
        self, ack: AsyncMock, respond: AsyncMock, client: AsyncMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "nf_core_bot.commands.hackathon.list_cmd.list_all_forms",
            lambda: [
                {
                    "hackathon_id": "h1",
                    "title": "Old One",
                    "status": "archived",
                    "date_start": "2025-01-01",
                    "date_end": "2025-01-03",
                    "url": "https://nf-co.re/events/2025/hackathon-jan-2025",
                },
                {
                    "hackathon_id": "h2",
                    "title": "Upcoming Draft",
                    "status": "draft",
                    "date_start": "2026-06-01",
                    "date_end": "2026-06-03",
                    "url": "https://nf-co.re/events/2026/hackathon-june-2026",
                },
            ],
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
            "nf_core_bot.commands.hackathon.list_cmd.list_all_forms",
            lambda: [
                {
                    "hackathon_id": "h1",
                    "title": "March 2026",
                    "status": "open",
                    "date_start": "2026-03-11",
                    "date_end": "2026-03-13",
                    "url": "https://nf-co.re/events/2026/hackathon-march-2026",
                },
            ],
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
            "nf_core_bot.commands.hackathon.list_cmd.list_all_forms",
            lambda: [
                {
                    "hackathon_id": "h1",
                    "title": "March 2026",
                    "status": "open",
                    "date_start": "2026-03-11",
                    "date_end": "2026-03-13",
                    "url": "https://nf-co.re/events/2026/hackathon-march-2026",
                },
            ],
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

    async def test_multiple_hackathons_mixed_status(
        self, ack: AsyncMock, respond: AsyncMock, client: AsyncMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "nf_core_bot.commands.hackathon.list_cmd.list_all_forms",
            lambda: [
                {
                    "hackathon_id": "h1",
                    "title": "Open One",
                    "status": "open",
                    "date_start": "2026-02-01",
                    "date_end": "2026-02-03",
                    "url": "https://nf-co.re/events/2026/hackathon-feb-2026",
                },
                {
                    "hackathon_id": "h2",
                    "title": "Closed One",
                    "status": "closed",
                    "date_start": "2026-01-01",
                    "date_end": "2026-01-03",
                    "url": "https://nf-co.re/events/2026/hackathon-jan-2026",
                },
                {
                    "hackathon_id": "h3",
                    "title": "Archived",
                    "status": "archived",
                    "date_start": "2025-01-01",
                    "date_end": "2025-01-03",
                    "url": "https://nf-co.re/events/2025/hackathon-jan-2025",
                },
            ],
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
        def _raise() -> None:
            raise RuntimeError("db down")

        monkeypatch.setattr(
            "nf_core_bot.commands.hackathon.list_cmd.list_all_forms",
            _raise,
        )

        await handle_list(ack, respond, client, _body())

        ack.assert_awaited_once()
        assert "Something went wrong" in respond.call_args.kwargs["text"]
