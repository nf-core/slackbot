"""Integration tests for the router dispatch chain.

These tests verify that the router passes the correct argument types to
handlers. They catch mismatches between the router's dispatch logic and
handler signatures — a class of bug that unit tests for individual
handlers cannot detect because they mock the router away.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

import nf_core_bot.commands.router as router_mod
from nf_core_bot.commands.router import dispatch


def _command(text: str = "", command: str = "/nf-core") -> dict[str, str]:
    """Build a minimal Slack command dict."""
    return {
        "text": text,
        "user_id": "U_TEST",
        "trigger_id": "T_TEST",
        "command": command,
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

    async def test_admin_add_site_receives_ack_respond_client_body_args(self, monkeypatch):
        mock = AsyncMock()
        monkeypatch.setitem(router_mod._ADMIN_DISPATCH, "add-site", mock)
        await dispatch(
            AsyncMock(),
            AsyncMock(),
            AsyncMock(),
            _command("hackathon admin add-site 2026-march"),
        )
        mock.assert_awaited_once()
        args = mock.call_args[0]
        assert len(args) == 5  # ack, respond, client, body, args_list
        assert isinstance(args[4], list)  # args is a list

    async def test_admin_edit_site_receives_ack_respond_client_body_args(self, monkeypatch):
        mock = AsyncMock()
        monkeypatch.setitem(router_mod._ADMIN_DISPATCH, "edit-site", mock)
        await dispatch(
            AsyncMock(),
            AsyncMock(),
            AsyncMock(),
            _command("hackathon admin edit-site 2026-march barcelona"),
        )
        mock.assert_awaited_once()
        args = mock.call_args[0]
        assert len(args) == 5  # ack, respond, client, body, args_list
        assert isinstance(args[4], list)


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

    async def test_add_site_body_contains_trigger_id(self, monkeypatch):
        mock = AsyncMock()
        monkeypatch.setitem(router_mod._ADMIN_DISPATCH, "add-site", mock)
        await dispatch(AsyncMock(), AsyncMock(), AsyncMock(), _command("hackathon admin add-site"))
        body = mock.call_args[0][3]
        assert "trigger_id" in body
        assert "user_id" in body

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

    async def test_export_receives_ack_respond_client_body_rest(self, monkeypatch):
        mock = AsyncMock()
        monkeypatch.setattr("nf_core_bot.commands.router.handle_export", mock)
        await dispatch(AsyncMock(), AsyncMock(), AsyncMock(), _command("hackathon export h1"))
        mock.assert_awaited_once()
        args = mock.call_args[0]
        assert len(args) == 5  # ack, respond, client, body, rest
        assert isinstance(args[4], list)
        assert args[4] == ["h1"]


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


class TestHackathonAliases:
    """Verify that 'h', 'hack', and 'hackathons' route like 'hackathon'."""

    @pytest.mark.parametrize("alias", ["h", "hack", "hackathons"])
    async def test_alias_routes_to_hackathon(self, alias: str, monkeypatch):
        """Each alias should dispatch the same as 'hackathon'."""
        mock = AsyncMock()
        monkeypatch.setattr(router_mod, "_route_hackathon", mock)
        await dispatch(AsyncMock(), AsyncMock(), AsyncMock(), _command(f"{alias} list"))
        mock.assert_awaited_once()

    @pytest.mark.parametrize("alias", ["h", "hack", "hackathons"])
    async def test_alias_admin_dispatches(self, alias: str, monkeypatch):
        mock = AsyncMock()
        monkeypatch.setitem(router_mod._ADMIN_DISPATCH, "list", mock)
        await dispatch(AsyncMock(), AsyncMock(), AsyncMock(), _command(f"{alias} admin list"))
        mock.assert_awaited_once()


# ── /hackathon command name threading ───────────────────────────────


class TestCommandNameThreading:
    """Verify that the command name (/nf-core vs /hackathon) is threaded
    through to help handlers and error messages."""

    async def test_hackathon_help_receives_command_name(self, monkeypatch):
        """handle_hackathon_help gets command_name='/hackathon' when invoked via /hackathon."""
        mock = AsyncMock()
        monkeypatch.setattr("nf_core_bot.commands.router.handle_hackathon_help", mock)
        await dispatch(AsyncMock(), AsyncMock(), AsyncMock(), _command("hackathon help", command="/hackathon"))
        mock.assert_awaited_once()
        assert mock.call_args[1]["command_name"] == "/hackathon"

    async def test_hackathon_help_default_nfcore(self, monkeypatch):
        """handle_hackathon_help gets command_name='/nf-core' when invoked via /nf-core."""
        mock = AsyncMock()
        monkeypatch.setattr("nf_core_bot.commands.router.handle_hackathon_help", mock)
        await dispatch(AsyncMock(), AsyncMock(), AsyncMock(), _command("hackathon help", command="/nf-core"))
        mock.assert_awaited_once()
        assert mock.call_args[1]["command_name"] == "/nf-core"

    async def test_top_help_receives_command_name(self, monkeypatch):
        """handle_help gets command_name from the Slack command dict."""
        mock = AsyncMock()
        monkeypatch.setattr("nf_core_bot.commands.router.handle_help", mock)
        await dispatch(AsyncMock(), AsyncMock(), AsyncMock(), _command("help", command="/nf-core"))
        mock.assert_awaited_once()
        assert mock.call_args[1]["command_name"] == "/nf-core"

    async def test_unknown_hackathon_error_uses_hackathon_hint(self):
        """Unknown hackathon subcommand error should reference /hackathon help when invoked via /hackathon."""
        ack = AsyncMock()
        respond = AsyncMock()
        await dispatch(ack, respond, AsyncMock(), _command("hackathon bogus", command="/hackathon"))
        msg = respond.call_args[0][0]
        assert "/hackathon help" in msg
        assert "/nf-core" not in msg

    async def test_unknown_hackathon_error_uses_nfcore_hint(self):
        """Unknown hackathon subcommand error should reference /nf-core hackathon help when invoked via /nf-core."""
        ack = AsyncMock()
        respond = AsyncMock()
        await dispatch(ack, respond, AsyncMock(), _command("hackathon bogus", command="/nf-core"))
        msg = respond.call_args[0][0]
        assert "/nf-core hackathon help" in msg

    async def test_unknown_admin_error_uses_hackathon_hint(self):
        """Unknown admin subcommand error should reference /hackathon help when invoked via /hackathon."""
        ack = AsyncMock()
        respond = AsyncMock()
        await dispatch(ack, respond, AsyncMock(), _command("hackathon admin bogus", command="/hackathon"))
        msg = respond.call_args[0][0]
        assert "/hackathon help" in msg
        assert "/nf-core" not in msg

    async def test_unknown_top_level_error_uses_command_name(self):
        """Unknown top-level command error should use the actual command name."""
        ack = AsyncMock()
        respond = AsyncMock()
        await dispatch(ack, respond, AsyncMock(), _command("bogus", command="/nf-core"))
        msg = respond.call_args[0][0]
        assert "/nf-core help" in msg
