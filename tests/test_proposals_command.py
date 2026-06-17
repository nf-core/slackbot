"""Tests for the /nf-core proposals review slash command + router gate."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, patch

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


class TestRunAndPost:
    async def test_visible_post(self) -> None:
        with (
            patch.object(cmd, "build_review_message", new=AsyncMock(return_value=(_issue(), "TEXT"))),
            patch.object(cmd, "post_review", new=AsyncMock()) as post,
        ):
            await cmd._run_and_post(AsyncMock(), 148, "C1", "U1", preview=False)
        post.assert_awaited_once()
        assert post.await_args.kwargs.get("ephemeral_user") is None

    async def test_preview_is_ephemeral(self) -> None:
        with (
            patch.object(cmd, "build_review_message", new=AsyncMock(return_value=(_issue(), "TEXT"))),
            patch.object(cmd, "post_review", new=AsyncMock()) as post,
        ):
            await cmd._run_and_post(AsyncMock(), 148, "C1", "U1", preview=True)
        assert post.await_args.kwargs.get("ephemeral_user") == "U1"

    async def test_missing_issue_warns(self) -> None:
        client = AsyncMock()
        with patch.object(cmd, "build_review_message", new=AsyncMock(return_value=(None, None))):
            await cmd._run_and_post(client, 999, "C1", "U1", preview=False)
        client.chat_postEphemeral.assert_awaited_once()


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
