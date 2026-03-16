"""Integration tests for the router dispatch chain.

These tests verify that the router passes the correct argument types to
handlers. They catch mismatches between the router's dispatch logic and
handler signatures — a class of bug that unit tests for individual
handlers cannot detect because they mock the router away.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import nf_core_bot.commands.router as router_mod
from nf_core_bot.commands.router import dispatch


def _command(text: str = "") -> dict[str, str]:
    """Build a minimal Slack command dict."""
    return {
        "text": text,
        "user_id": "U_TEST",
        "trigger_id": "T_TEST",
    }


# ── Admin dispatch — argument types ─────────────────────────────────


class TestAdminDispatchTypes:
    """Verify the router passes correct argument types to admin handlers."""

    async def test_admin_list_receives_ack_respond(self, monkeypatch):
        """admin list handler receives (ack, respond) only."""
        mock = AsyncMock()
        monkeypatch.setitem(router_mod._ADMIN_DISPATCH, "list", mock)
        await dispatch(AsyncMock(), AsyncMock(), AsyncMock(), _command("hackathon admin list"))
        mock.assert_awaited_once()
        args = mock.call_args[0]
        assert len(args) == 2  # ack, respond

    async def test_admin_preview_receives_ack_respond_client_body_args(self, monkeypatch):
        """admin preview handler receives (ack, respond, client, body, args) where args is a list."""
        mock = AsyncMock()
        monkeypatch.setitem(router_mod._ADMIN_DISPATCH, "preview", mock)
        await dispatch(AsyncMock(), AsyncMock(), AsyncMock(), _command("hackathon admin preview 2026-march"))
        mock.assert_awaited_once()
        args = mock.call_args[0]
        assert len(args) == 5  # ack, respond, client, body, args_list
        assert isinstance(args[3], dict)  # body is a dict
        assert isinstance(args[4], list)  # args is a list
        assert args[4] == ["2026-march"]

    async def test_admin_add_site_receives_ack_respond_args_list(self, monkeypatch):
        mock = AsyncMock()
        monkeypatch.setitem(router_mod._ADMIN_DISPATCH, "add-site", mock)
        await dispatch(
            AsyncMock(),
            AsyncMock(),
            AsyncMock(),
            _command("hackathon admin add-site 2026-march barcelona Barcelona | Barcelona | Spain"),
        )
        mock.assert_awaited_once()
        args = mock.call_args[0]
        assert len(args) == 3  # ack, respond, args_list
        assert isinstance(args[2], list)  # args is a list

    async def test_admin_remove_site_receives_args_list(self, monkeypatch):
        mock = AsyncMock()
        monkeypatch.setitem(router_mod._ADMIN_DISPATCH, "remove-site", mock)
        await dispatch(
            AsyncMock(), AsyncMock(), AsyncMock(), _command("hackathon admin remove-site 2026-march barcelona")
        )
        mock.assert_awaited_once()
        args = mock.call_args[0]
        assert isinstance(args[2], list)

    async def test_admin_list_sites_receives_args_list(self, monkeypatch):
        mock = AsyncMock()
        monkeypatch.setitem(router_mod._ADMIN_DISPATCH, "list-sites", mock)
        await dispatch(AsyncMock(), AsyncMock(), AsyncMock(), _command("hackathon admin list-sites 2026-march"))
        mock.assert_awaited_once()
        args = mock.call_args[0]
        assert isinstance(args[2], list)

    async def test_admin_add_organiser_receives_args_list(self, monkeypatch):
        mock = AsyncMock()
        monkeypatch.setitem(router_mod._ADMIN_DISPATCH, "add-organiser", mock)
        await dispatch(
            AsyncMock(),
            AsyncMock(),
            AsyncMock(),
            _command("hackathon admin add-organiser 2026-march barcelona <@U123>"),
        )
        mock.assert_awaited_once()
        args = mock.call_args[0]
        assert isinstance(args[2], list)

    async def test_admin_remove_organiser_receives_args_list(self, monkeypatch):
        mock = AsyncMock()
        monkeypatch.setitem(router_mod._ADMIN_DISPATCH, "remove-organiser", mock)
        await dispatch(
            AsyncMock(),
            AsyncMock(),
            AsyncMock(),
            _command("hackathon admin remove-organiser 2026-march barcelona <@U123>"),
        )
        mock.assert_awaited_once()
        args = mock.call_args[0]
        assert isinstance(args[2], list)


# ── Admin dispatch — argument values ────────────────────────────────


class TestAdminDispatchArgValues:
    """Verify the router splits arguments correctly."""

    async def test_preview_with_no_args(self, monkeypatch):
        mock = AsyncMock()
        monkeypatch.setitem(router_mod._ADMIN_DISPATCH, "preview", mock)
        await dispatch(AsyncMock(), AsyncMock(), AsyncMock(), _command("hackathon admin preview"))
        args = mock.call_args[0]
        assert args[4] == []  # empty list when no hackathon-id provided

    async def test_preview_with_hackathon_id(self, monkeypatch):
        mock = AsyncMock()
        monkeypatch.setitem(router_mod._ADMIN_DISPATCH, "preview", mock)
        await dispatch(AsyncMock(), AsyncMock(), AsyncMock(), _command("hackathon admin preview 2026-march"))
        args = mock.call_args[0]
        assert args[4] == ["2026-march"]

    async def test_add_site_all_tokens_passed(self, monkeypatch):
        mock = AsyncMock()
        monkeypatch.setitem(router_mod._ADMIN_DISPATCH, "add-site", mock)
        await dispatch(
            AsyncMock(), AsyncMock(), AsyncMock(), _command("hackathon admin add-site h1 site1 Name | City | Country")
        )
        args = mock.call_args[0]
        assert args[2] == ["h1", "site1", "Name", "|", "City", "|", "Country"]

    async def test_body_contains_trigger_id_and_user_id(self, monkeypatch):
        mock = AsyncMock()
        monkeypatch.setitem(router_mod._ADMIN_DISPATCH, "preview", mock)
        await dispatch(AsyncMock(), AsyncMock(), AsyncMock(), _command("hackathon admin preview test"))
        body = mock.call_args[0][3]
        assert "trigger_id" in body
        assert "user_id" in body
        assert body["user_id"] == "U_TEST"
        assert body["trigger_id"] == "T_TEST"


# ── Hackathon commands — argument types ─────────────────────────────


class TestHackathonDispatchTypes:
    """Verify router passes correct types to hackathon command handlers."""

    async def test_register_receives_ack_respond_client_body(self, monkeypatch):
        mock = AsyncMock()
        monkeypatch.setattr("nf_core_bot.commands.router.handle_register", mock)
        await dispatch(AsyncMock(), AsyncMock(), AsyncMock(), _command("hackathon register"))
        mock.assert_awaited_once()
        args = mock.call_args[0]
        assert len(args) == 4  # ack, respond, client, body
        assert isinstance(args[3], dict)  # body

    async def test_edit_receives_ack_respond_client_body(self, monkeypatch):
        mock = AsyncMock()
        monkeypatch.setattr("nf_core_bot.commands.router.handle_edit", mock)
        await dispatch(AsyncMock(), AsyncMock(), AsyncMock(), _command("hackathon edit"))
        mock.assert_awaited_once()
        assert len(mock.call_args[0]) == 4

    async def test_cancel_receives_ack_respond_client_body(self, monkeypatch):
        mock = AsyncMock()
        monkeypatch.setattr("nf_core_bot.commands.router.handle_cancel", mock)
        await dispatch(AsyncMock(), AsyncMock(), AsyncMock(), _command("hackathon cancel"))
        mock.assert_awaited_once()
        assert len(mock.call_args[0]) == 4

    async def test_list_receives_ack_respond_client_body(self, monkeypatch):
        mock = AsyncMock()
        monkeypatch.setattr("nf_core_bot.commands.router.handle_list", mock)
        await dispatch(AsyncMock(), AsyncMock(), AsyncMock(), _command("hackathon list"))
        mock.assert_awaited_once()
        assert len(mock.call_args[0]) == 4

    async def test_attendees_receives_ack_respond_client_body_rest(self, monkeypatch):
        mock = AsyncMock()
        monkeypatch.setattr("nf_core_bot.commands.router.handle_attendees", mock)
        await dispatch(AsyncMock(), AsyncMock(), AsyncMock(), _command("hackathon attendees h1"))
        mock.assert_awaited_once()
        args = mock.call_args[0]
        assert len(args) == 5  # ack, respond, client, body, rest
        assert isinstance(args[4], list)  # rest is a list
        assert args[4] == ["h1"]

    async def test_attendees_with_no_args(self, monkeypatch):
        mock = AsyncMock()
        monkeypatch.setattr("nf_core_bot.commands.router.handle_attendees", mock)
        await dispatch(AsyncMock(), AsyncMock(), AsyncMock(), _command("hackathon attendees"))
        args = mock.call_args[0]
        assert args[4] == []  # empty list


# ── GitHub commands — argument types ────────────────────────────────


class TestGithubDispatchTypes:
    async def test_add_member_receives_correct_args(self, monkeypatch):
        mock = AsyncMock()
        monkeypatch.setitem(router_mod._GITHUB_DISPATCH, "add-member", mock)
        await dispatch(AsyncMock(), AsyncMock(), AsyncMock(), _command("github add-member octocat"))
        mock.assert_awaited_once()
        args = mock.call_args[0]
        assert len(args) == 6  # ack, respond, client, user_id, command, rest
        assert isinstance(args[5], list)  # rest is a list


# ── Error handling — unknown commands still ack ─────────────────────


class TestUnknownCommandsAck:
    """Verify that unknown commands still call ack() so Slack doesn't time out."""

    async def test_unknown_top_level_acks(self):
        ack = AsyncMock()
        respond = AsyncMock()
        await dispatch(ack, respond, AsyncMock(), _command("unknown"))
        ack.assert_awaited_once()

    async def test_unknown_hackathon_sub_acks(self):
        ack = AsyncMock()
        respond = AsyncMock()
        await dispatch(ack, respond, AsyncMock(), _command("hackathon unknown"))
        ack.assert_awaited_once()

    async def test_unknown_admin_sub_acks(self):
        ack = AsyncMock()
        respond = AsyncMock()
        await dispatch(ack, respond, AsyncMock(), _command("hackathon admin unknown"))
        ack.assert_awaited_once()
