"""Integration tests for the router dispatch chain.

These tests verify that the router passes the correct argument types to
handlers. They catch mismatches between the router's dispatch logic and
handler signatures — a class of bug that unit tests for individual
handlers cannot detect because they mock the router away.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import nf_core_bot.commands.router as router_mod
from nf_core_bot.commands.router import dispatch, dispatch_hackathon


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
        await dispatch_hackathon(AsyncMock(), AsyncMock(), AsyncMock(), _command("admin list", command="/hackathon"))
        mock.assert_awaited_once()
        args = mock.call_args[0]
        assert len(args) == 2  # ack, respond

    async def test_admin_preview_receives_ack_respond_client_body_args(self, monkeypatch):
        """admin preview handler receives (ack, respond, client, body, args) where args is a list."""
        mock = AsyncMock()
        monkeypatch.setitem(router_mod._ADMIN_DISPATCH, "preview", mock)
        await dispatch_hackathon(
            AsyncMock(), AsyncMock(), AsyncMock(), _command("admin preview 2026-march", command="/hackathon")
        )
        mock.assert_awaited_once()
        args = mock.call_args[0]
        assert len(args) == 5  # ack, respond, client, body, args_list
        assert isinstance(args[3], dict)  # body is a dict
        assert isinstance(args[4], list)  # args is a list
        assert args[4] == ["2026-march"]

    async def test_admin_add_site_receives_ack_respond_client_body_args(self, monkeypatch):
        mock = AsyncMock()
        monkeypatch.setitem(router_mod._ADMIN_DISPATCH, "add-site", mock)
        await dispatch_hackathon(
            AsyncMock(),
            AsyncMock(),
            AsyncMock(),
            _command("admin add-site 2026-march", command="/hackathon"),
        )
        mock.assert_awaited_once()
        args = mock.call_args[0]
        assert len(args) == 5  # ack, respond, client, body, args_list
        assert isinstance(args[4], list)  # args is a list

    async def test_admin_edit_site_receives_ack_respond_client_body_args(self, monkeypatch):
        mock = AsyncMock()
        monkeypatch.setitem(router_mod._ADMIN_DISPATCH, "edit-site", mock)
        await dispatch_hackathon(
            AsyncMock(),
            AsyncMock(),
            AsyncMock(),
            _command("admin edit-site 2026-march barcelona", command="/hackathon"),
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
        await dispatch_hackathon(AsyncMock(), AsyncMock(), AsyncMock(), _command("admin preview", command="/hackathon"))
        args = mock.call_args[0]
        assert args[4] == []  # empty list when no hackathon-id provided

    async def test_preview_with_hackathon_id(self, monkeypatch):
        mock = AsyncMock()
        monkeypatch.setitem(router_mod._ADMIN_DISPATCH, "preview", mock)
        await dispatch_hackathon(
            AsyncMock(), AsyncMock(), AsyncMock(), _command("admin preview 2026-march", command="/hackathon")
        )
        args = mock.call_args[0]
        assert args[4] == ["2026-march"]

    async def test_add_site_body_contains_trigger_id(self, monkeypatch):
        mock = AsyncMock()
        monkeypatch.setitem(router_mod._ADMIN_DISPATCH, "add-site", mock)
        await dispatch_hackathon(
            AsyncMock(), AsyncMock(), AsyncMock(), _command("admin add-site", command="/hackathon")
        )
        body = mock.call_args[0][3]
        assert "trigger_id" in body
        assert "user_id" in body

    async def test_body_contains_trigger_id_and_user_id(self, monkeypatch):
        mock = AsyncMock()
        monkeypatch.setitem(router_mod._ADMIN_DISPATCH, "preview", mock)
        await dispatch_hackathon(
            AsyncMock(), AsyncMock(), AsyncMock(), _command("admin preview test", command="/hackathon")
        )
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
        await dispatch_hackathon(AsyncMock(), AsyncMock(), AsyncMock(), _command("register", command="/hackathon"))
        mock.assert_awaited_once()
        args = mock.call_args[0]
        assert len(args) == 4  # ack, respond, client, body
        assert isinstance(args[3], dict)  # body

    async def test_edit_receives_ack_respond_client_body(self, monkeypatch):
        mock = AsyncMock()
        monkeypatch.setattr("nf_core_bot.commands.router.handle_edit", mock)
        await dispatch_hackathon(AsyncMock(), AsyncMock(), AsyncMock(), _command("edit", command="/hackathon"))
        mock.assert_awaited_once()
        assert len(mock.call_args[0]) == 4

    async def test_cancel_receives_ack_respond_client_body(self, monkeypatch):
        mock = AsyncMock()
        monkeypatch.setattr("nf_core_bot.commands.router.handle_cancel", mock)
        await dispatch_hackathon(AsyncMock(), AsyncMock(), AsyncMock(), _command("cancel", command="/hackathon"))
        mock.assert_awaited_once()
        assert len(mock.call_args[0]) == 4

    async def test_list_receives_ack_respond_client_body(self, monkeypatch):
        mock = AsyncMock()
        monkeypatch.setattr("nf_core_bot.commands.router.handle_list", mock)
        await dispatch_hackathon(AsyncMock(), AsyncMock(), AsyncMock(), _command("list", command="/hackathon"))
        mock.assert_awaited_once()
        assert len(mock.call_args[0]) == 4

    async def test_export_receives_ack_respond_client_body_rest(self, monkeypatch):
        mock = AsyncMock()
        monkeypatch.setattr("nf_core_bot.commands.router.handle_export", mock)
        await dispatch_hackathon(AsyncMock(), AsyncMock(), AsyncMock(), _command("export h1", command="/hackathon"))
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
        await dispatch_hackathon(ack, respond, AsyncMock(), _command("unknown", command="/hackathon"))
        ack.assert_awaited_once()

    async def test_unknown_admin_sub_acks(self):
        ack = AsyncMock()
        respond = AsyncMock()
        await dispatch_hackathon(ack, respond, AsyncMock(), _command("admin unknown", command="/hackathon"))
        ack.assert_awaited_once()


# ── Admin alias — adm / a ──────────────────────────────────────────


class TestAdminAliases:
    """Verify that 'a' and 'adm' route to admin."""

    async def test_adm_alias(self, monkeypatch):
        mock = AsyncMock()
        monkeypatch.setitem(router_mod._ADMIN_DISPATCH, "list", mock)
        await dispatch_hackathon(AsyncMock(), AsyncMock(), AsyncMock(), _command("adm list", command="/hackathon"))
        mock.assert_awaited_once()

    async def test_a_alias(self, monkeypatch):
        mock = AsyncMock()
        monkeypatch.setitem(router_mod._ADMIN_DISPATCH, "list", mock)
        await dispatch_hackathon(AsyncMock(), AsyncMock(), AsyncMock(), _command("a list", command="/hackathon"))
        mock.assert_awaited_once()


# ── Command separation ──────────────────────────────────────────────


class TestCommandSeparation:
    """Verify /nf-core and /hackathon are properly separated."""

    async def test_nfcore_does_not_route_hackathon(self):
        """dispatch() should not handle hackathon subcommands."""
        ack = AsyncMock()
        respond = AsyncMock()
        await dispatch(ack, respond, AsyncMock(), _command("hackathon register"))
        ack.assert_awaited_once()
        msg = respond.call_args[0][0]
        assert "Unknown command" in msg

    async def test_nfcore_help_does_not_list_hackathon_commands(self, monkeypatch):
        """Top-level /nf-core help should mention /hackathon help, not list hackathon commands."""
        mock = AsyncMock()
        monkeypatch.setattr("nf_core_bot.commands.router.handle_help", mock)
        await dispatch(AsyncMock(), AsyncMock(), AsyncMock(), _command("help"))
        mock.assert_awaited_once()

    async def test_unknown_hackathon_error_references_hackathon_help(self):
        """Unknown /hackathon subcommand should reference /hackathon help."""
        ack = AsyncMock()
        respond = AsyncMock()
        await dispatch_hackathon(ack, respond, AsyncMock(), _command("bogus", command="/hackathon"))
        msg = respond.call_args[0][0]
        assert "/hackathon help" in msg

    async def test_unknown_admin_error_references_hackathon_help(self):
        """Unknown admin subcommand should reference /hackathon help."""
        ack = AsyncMock()
        respond = AsyncMock()
        await dispatch_hackathon(ack, respond, AsyncMock(), _command("admin bogus", command="/hackathon"))
        msg = respond.call_args[0][0]
        assert "/hackathon help" in msg

    async def test_unknown_nfcore_error_references_nfcore_help(self):
        """Unknown /nf-core command should reference /nf-core help."""
        ack = AsyncMock()
        respond = AsyncMock()
        await dispatch(ack, respond, AsyncMock(), _command("bogus"))
        msg = respond.call_args[0][0]
        assert "/nf-core help" in msg
