"""Tests for the /nf-core security summary slash command + router gate."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from slack_sdk.errors import SlackApiError

from nf_core_bot.commands import router
from nf_core_bot.commands.security import summary as cmd


class TestHandler:
    async def test_posts_summary_where_command_was_run(self) -> None:
        respond = AsyncMock()
        client = AsyncMock()
        with (
            patch.object(cmd, "list_all_org_advisories", new=AsyncMock(return_value=[])),
            patch.object(cmd, "format_advisories_summary", return_value="SUMMARY TEXT"),
        ):
            await cmd.handle_security_summary(respond, client, "U1", {"channel_id": "C1"})

        client.chat_postMessage.assert_awaited_once_with(channel="C1", text="SUMMARY TEXT")
        respond.assert_not_awaited()

    async def test_fetch_failure_reports_ephemerally(self) -> None:
        respond = AsyncMock()
        client = AsyncMock()
        with patch.object(cmd, "list_all_org_advisories", new=AsyncMock(side_effect=RuntimeError("403"))):
            await cmd.handle_security_summary(respond, client, "U1", {"channel_id": "C1"})

        client.chat_postMessage.assert_not_awaited()
        respond.assert_awaited_once()
        assert "Could not fetch" in respond.await_args.args[0]
        assert respond.await_args.kwargs.get("response_type") == "ephemeral"

    async def test_falls_back_to_dm_when_not_in_channel(self) -> None:
        respond = AsyncMock()
        client = AsyncMock()
        client.conversations_open = AsyncMock(return_value={"channel": {"id": "D9"}})
        err = SlackApiError("nope", {"error": "channel_not_found"})
        client.chat_postMessage = AsyncMock(side_effect=[err, {"ok": True}])
        with (
            patch.object(cmd, "list_all_org_advisories", new=AsyncMock(return_value=[])),
            patch.object(cmd, "format_advisories_summary", return_value="SUMMARY TEXT"),
        ):
            await cmd.handle_security_summary(respond, client, "U1", {"channel_id": "C_selfdm"})

        assert client.chat_postMessage.await_count == 2
        assert client.chat_postMessage.await_args_list[1].kwargs["channel"] == "D9"
        assert respond.await_args.kwargs.get("response_type") == "ephemeral"

    async def test_reraises_unexpected_slack_errors(self) -> None:
        respond = AsyncMock()
        client = AsyncMock()
        err = SlackApiError("nope", {"error": "some_other_error"})
        client.chat_postMessage = AsyncMock(side_effect=err)
        with (
            patch.object(cmd, "list_all_org_advisories", new=AsyncMock(return_value=[])),
            patch.object(cmd, "format_advisories_summary", return_value="SUMMARY TEXT"),
        ):
            try:
                await cmd.handle_security_summary(respond, client, "U1", {"channel_id": "C1"})
            except SlackApiError:
                pass
            else:
                raise AssertionError("expected SlackApiError to propagate")


class TestRouterGate:
    async def test_non_member_denied(self) -> None:
        ack, respond = AsyncMock(), AsyncMock()
        with patch.object(router, "is_core_team", new=AsyncMock(return_value=False)):
            await router._route_security(ack, respond, AsyncMock(), "U1", {"channel_id": "C1"}, ["summary"])
        ack.assert_awaited_once()
        assert "restricted" in respond.await_args.args[0]

    async def test_member_dispatched(self) -> None:
        ack, respond = AsyncMock(), AsyncMock()
        handler = AsyncMock()
        with (
            patch.object(router, "is_core_team", new=AsyncMock(return_value=True)),
            patch.object(router, "handle_security_summary", handler),
        ):
            await router._route_security(ack, respond, AsyncMock(), "U1", {"channel_id": "C1"}, ["summary"])
        handler.assert_awaited_once()

    async def test_help(self) -> None:
        ack, respond = AsyncMock(), AsyncMock()
        with patch.object(router, "is_core_team", new=AsyncMock(return_value=True)):
            await router._route_security(ack, respond, AsyncMock(), "U1", {"channel_id": "C1"}, [])
        assert "security summary" in respond.await_args.args[0]

    async def test_unknown_subcommand(self) -> None:
        ack, respond = AsyncMock(), AsyncMock()
        with patch.object(router, "is_core_team", new=AsyncMock(return_value=True)):
            await router._route_security(ack, respond, AsyncMock(), "U1", {"channel_id": "C1"}, ["bogus"])
        assert "Unknown security command" in respond.await_args.args[0]
