"""Tests for nf_core_bot.commands.hackathon.register — register, edit, cancel."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

from nf_core_bot.commands.hackathon.register import handle_cancel, handle_edit, handle_register


@pytest.fixture()
def ack() -> AsyncMock:
    return AsyncMock()


@pytest.fixture()
def respond() -> AsyncMock:
    return AsyncMock()


@pytest.fixture()
def client() -> AsyncMock:
    return AsyncMock()


def _body(user_id: str = "U_USER", trigger_id: str = "T_TRIGGER") -> dict[str, Any]:
    return {"user_id": user_id, "trigger_id": trigger_id}


# ── handle_register ──────────────────────────────────────────────────


class TestRegister:
    async def test_no_active_hackathon(
        self, ack: AsyncMock, respond: AsyncMock, client: AsyncMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "nf_core_bot.commands.hackathon.register.get_active_form",
            lambda: None,
        )

        await handle_register(ack, respond, client, _body())

        ack.assert_awaited_once()
        assert "No hackathon is currently open" in respond.call_args.kwargs["text"]

    async def test_already_registered(
        self, ack: AsyncMock, respond: AsyncMock, client: AsyncMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "nf_core_bot.commands.hackathon.register.get_active_form",
            lambda: {"hackathon_id": "h1"},
        )
        monkeypatch.setattr(
            "nf_core_bot.commands.hackathon.register.get_registration",
            AsyncMock(return_value={"user_id": "U_USER"}),
        )

        await handle_register(ack, respond, client, _body())

        ack.assert_awaited_once()
        assert "already registered" in respond.call_args.kwargs["text"]

    async def test_success_opens_modal(
        self, ack: AsyncMock, respond: AsyncMock, client: AsyncMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "nf_core_bot.commands.hackathon.register.get_active_form",
            lambda: {"hackathon_id": "h1"},
        )
        monkeypatch.setattr(
            "nf_core_bot.commands.hackathon.register.get_registration",
            AsyncMock(return_value=None),
        )
        mock_open_modal = AsyncMock()
        monkeypatch.setattr(
            "nf_core_bot.commands.hackathon.register.open_registration_modal",
            mock_open_modal,
        )

        await handle_register(ack, respond, client, _body())

        ack.assert_awaited_once()
        mock_open_modal.assert_awaited_once_with(client, "T_TRIGGER", "h1", "U_USER")

    async def test_get_active_form_exception(
        self, ack: AsyncMock, respond: AsyncMock, client: AsyncMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _raise() -> None:
            raise RuntimeError("db down")

        monkeypatch.setattr(
            "nf_core_bot.commands.hackathon.register.get_active_form",
            _raise,
        )

        await handle_register(ack, respond, client, _body())

        ack.assert_awaited_once()
        assert "Something went wrong" in respond.call_args.kwargs["text"]


# ── handle_edit ──────────────────────────────────────────────────────


class TestEdit:
    async def test_no_active_hackathon(
        self, ack: AsyncMock, respond: AsyncMock, client: AsyncMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "nf_core_bot.commands.hackathon.register.get_active_form",
            lambda: None,
        )

        await handle_edit(ack, respond, client, _body())

        ack.assert_awaited_once()
        assert "No hackathon is currently open" in respond.call_args.kwargs["text"]

    async def test_not_registered(
        self, ack: AsyncMock, respond: AsyncMock, client: AsyncMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "nf_core_bot.commands.hackathon.register.get_active_form",
            lambda: {"hackathon_id": "h1"},
        )
        monkeypatch.setattr(
            "nf_core_bot.commands.hackathon.register.get_registration",
            AsyncMock(return_value=None),
        )

        await handle_edit(ack, respond, client, _body())

        ack.assert_awaited_once()
        assert "not registered yet" in respond.call_args.kwargs["text"]

    async def test_success_opens_modal_with_data(
        self, ack: AsyncMock, respond: AsyncMock, client: AsyncMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "nf_core_bot.commands.hackathon.register.get_active_form",
            lambda: {"hackathon_id": "h1"},
        )
        monkeypatch.setattr(
            "nf_core_bot.commands.hackathon.register.get_registration",
            AsyncMock(
                return_value={
                    "user_id": "U_USER",
                    "site_id": "stockholm",
                    "form_data": {"name": "Alice"},
                }
            ),
        )
        mock_open_modal = AsyncMock()
        monkeypatch.setattr(
            "nf_core_bot.commands.hackathon.register.open_registration_modal",
            mock_open_modal,
        )

        await handle_edit(ack, respond, client, _body())

        ack.assert_awaited_once()
        mock_open_modal.assert_awaited_once()
        call_kwargs = mock_open_modal.call_args
        # Check existing_data includes form_data and site
        existing_data = call_kwargs.kwargs["existing_data"]
        assert existing_data["name"] == "Alice"
        assert existing_data["local_site"] == "stockholm"


# ── handle_cancel ────────────────────────────────────────────────────


class TestCancel:
    async def test_no_active_hackathon(
        self, ack: AsyncMock, respond: AsyncMock, client: AsyncMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "nf_core_bot.commands.hackathon.register.get_active_form",
            lambda: None,
        )

        await handle_cancel(ack, respond, client, _body())

        ack.assert_awaited_once()
        assert "No hackathon is currently open" in respond.call_args.kwargs["text"]

    async def test_not_registered(
        self, ack: AsyncMock, respond: AsyncMock, client: AsyncMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "nf_core_bot.commands.hackathon.register.get_active_form",
            lambda: {"hackathon_id": "h1"},
        )
        monkeypatch.setattr(
            "nf_core_bot.commands.hackathon.register.get_registration",
            AsyncMock(return_value=None),
        )

        await handle_cancel(ack, respond, client, _body())

        ack.assert_awaited_once()
        assert "don't have an active registration" in respond.call_args.kwargs["text"]

    async def test_success_deletes_registration(
        self, ack: AsyncMock, respond: AsyncMock, client: AsyncMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "nf_core_bot.commands.hackathon.register.get_active_form",
            lambda: {"hackathon_id": "h1", "title": "March 2026"},
        )
        monkeypatch.setattr(
            "nf_core_bot.commands.hackathon.register.get_registration",
            AsyncMock(return_value={"user_id": "U_USER"}),
        )
        mock_delete = AsyncMock()
        monkeypatch.setattr(
            "nf_core_bot.commands.hackathon.register.delete_registration",
            mock_delete,
        )

        await handle_cancel(ack, respond, client, _body())

        ack.assert_awaited_once()
        mock_delete.assert_awaited_once_with("h1", "U_USER")
        assert "cancelled" in respond.call_args.kwargs["text"]
        assert "March 2026" in respond.call_args.kwargs["text"]

    async def test_delete_failure(
        self, ack: AsyncMock, respond: AsyncMock, client: AsyncMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "nf_core_bot.commands.hackathon.register.get_active_form",
            lambda: {"hackathon_id": "h1", "title": "March 2026"},
        )
        monkeypatch.setattr(
            "nf_core_bot.commands.hackathon.register.get_registration",
            AsyncMock(return_value={"user_id": "U_USER"}),
        )
        monkeypatch.setattr(
            "nf_core_bot.commands.hackathon.register.delete_registration",
            AsyncMock(side_effect=RuntimeError("db error")),
        )

        await handle_cancel(ack, respond, client, _body())

        ack.assert_awaited_once()
        assert "Something went wrong" in respond.call_args.kwargs["text"]
