"""Tests for the /nf-core proposals review slash command + router gate."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, patch

from slack_sdk.errors import SlackApiError

from nf_core_bot.checks.github import IssueWithComments
from nf_core_bot.commands import router
from nf_core_bot.commands.proposals import review as cmd

if TYPE_CHECKING:
    import pytest


def _issue() -> IssueWithComments:
    return IssueWithComments(
        148,
        "New pipeline: foo",
        "https://github.com/nf-core/proposals/issues/148",
        "a",
        "open",
        ["new-pipeline"],
        "b",
        [],
    )


class TestParseArgs:
    def test_number(self) -> None:
        assert cmd._parse_args(["148"]) == (148, False)

    def test_hash_and_preview(self) -> None:
        assert cmd._parse_args(["#148", "preview"]) == (148, True)

    def test_preview_only(self) -> None:
        assert cmd._parse_args(["preview"]) == (None, True)

    def test_empty(self) -> None:
        assert cmd._parse_args([]) == (None, False)


class TestHandler:
    async def test_no_number_shows_usage(self) -> None:
        respond = AsyncMock()
        await cmd.handle_proposals_review(respond, AsyncMock(), "U1", {"channel_id": "C1"}, [])
        respond.assert_awaited_once()
        assert "Usage" in respond.await_args.args[0]

    async def test_kicks_off_background(self, monkeypatch: pytest.MonkeyPatch) -> None:
        respond = AsyncMock()
        captured: list = []
        monkeypatch.setattr(cmd, "spawn", lambda coro: captured.append(coro))
        await cmd.handle_proposals_review(respond, AsyncMock(), "U1", {"channel_id": "C1"}, ["148"])
        respond.assert_awaited_once()
        assert len(captured) == 1
        captured[0].close()  # don't leave an un-awaited coroutine


_BLOCKS = [{"type": "markdown", "text": "THE REVIEW"}]


class TestRunAndPost:
    async def test_visible_post_uses_chat_post_message(self) -> None:
        # The review body is delivered via chat.postMessage (markdown blocks render
        # there), not the slash response URL, to the channel the command was run in.
        respond = AsyncMock()
        client = AsyncMock()
        with patch.object(cmd, "build_review_message", new=AsyncMock(return_value=(_issue(), _BLOCKS, "fb"))):
            await cmd._run_and_post(respond, client, "C1", "U1", 148, preview=False)
        client.chat_postMessage.assert_awaited_once()
        kwargs = client.chat_postMessage.await_args.kwargs
        assert kwargs["channel"] == "C1"
        assert kwargs["blocks"] == _BLOCKS
        assert kwargs["text"] == "fb"

    async def test_preview_goes_to_caller_dm(self) -> None:
        # `preview` keeps the result private: it's posted to the caller's DM with
        # the bot, with an ephemeral pointer left where the command was run.
        respond = AsyncMock()
        client = AsyncMock()
        client.conversations_open = AsyncMock(return_value={"channel": {"id": "D9"}})
        with patch.object(cmd, "build_review_message", new=AsyncMock(return_value=(_issue(), _BLOCKS, "fb"))):
            await cmd._run_and_post(respond, client, "C1", "U1", 148, preview=True)
        client.conversations_open.assert_awaited_once_with(users=["U1"])
        client.chat_postMessage.assert_awaited_once()
        assert client.chat_postMessage.await_args.kwargs["channel"] == "D9"
        assert respond.await_args.kwargs.get("response_type") == "ephemeral"

    async def test_falls_back_to_dm_when_not_in_channel(self) -> None:
        # Posting where the command was run can fail (e.g. a personal self-DM the
        # bot isn't in) — the review is then delivered to the caller's DM instead.
        respond = AsyncMock()
        client = AsyncMock()
        client.conversations_open = AsyncMock(return_value={"channel": {"id": "D9"}})
        err = SlackApiError("nope", {"error": "channel_not_found"})
        client.chat_postMessage = AsyncMock(side_effect=[err, {"ok": True}])
        with patch.object(cmd, "build_review_message", new=AsyncMock(return_value=(_issue(), _BLOCKS, "fb"))):
            await cmd._run_and_post(respond, client, "C_selfdm", "U1", 148, preview=False)
        assert client.chat_postMessage.await_count == 2
        assert client.chat_postMessage.await_args_list[1].kwargs["channel"] == "D9"

    async def test_missing_issue_warns_ephemerally(self) -> None:
        respond = AsyncMock()
        client = AsyncMock()
        with patch.object(cmd, "build_review_message", new=AsyncMock(return_value=(None, None, None))):
            await cmd._run_and_post(respond, client, "C1", "U1", 999, preview=False)
        respond.assert_awaited_once()
        assert "Couldn't fetch" in respond.await_args.args[0]
        assert respond.await_args.kwargs.get("response_type") == "ephemeral"
        client.chat_postMessage.assert_not_awaited()


class TestRouterGate:
    async def test_non_member_denied(self, monkeypatch: pytest.MonkeyPatch) -> None:
        ack, respond = AsyncMock(), AsyncMock()
        monkeypatch.setattr(router, "is_core_team_or_maintainers", AsyncMock(return_value=False))
        await router._route_proposals(ack, respond, AsyncMock(), "U1", {"channel_id": "C1"}, ["review", "148"])
        ack.assert_awaited_once()
        assert "restricted" in respond.await_args.args[0]

    async def test_member_dispatched(self, monkeypatch: pytest.MonkeyPatch) -> None:
        ack, respond = AsyncMock(), AsyncMock()
        monkeypatch.setattr(router, "is_core_team_or_maintainers", AsyncMock(return_value=True))
        handler = AsyncMock()
        monkeypatch.setattr(router, "handle_proposals_review", handler)
        await router._route_proposals(ack, respond, AsyncMock(), "U1", {"channel_id": "C1"}, ["review", "148"])
        handler.assert_awaited_once()

    async def test_help(self, monkeypatch: pytest.MonkeyPatch) -> None:
        ack, respond = AsyncMock(), AsyncMock()
        monkeypatch.setattr(router, "is_core_team_or_maintainers", AsyncMock(return_value=True))
        await router._route_proposals(ack, respond, AsyncMock(), "U1", {"channel_id": "C1"}, [])
        assert "proposals review" in respond.await_args.args[0]
