"""Tests for Seqera groups (team targets, remove, list) and the /nf-core seqera command."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from nf_core_bot.checks import seqera
from nf_core_bot.checks.seqera import SeqeraGroup, SeqeraStatus, add_to_group, groups_for_user, remove_from_group
from nf_core_bot.commands import router
from nf_core_bot.commands.seqera import manage
from nf_core_bot.db.seqera import get_member, list_members, put_member
from nf_core_bot.scheduler import seqera_jobs
from tests.helpers import make_slack_client

Handler = Callable[[httpx.Request], httpx.Response]

TEAM = SeqeraGroup("test team", team_id="77")


@pytest.fixture
def seqera_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SEQERA_TOKEN", "seqera-token")
    monkeypatch.setenv("SEQERA_ORG_ID", "11")
    monkeypatch.setenv("SEQERA_WORKSPACE_ID", "22")
    monkeypatch.setattr(seqera, "SEQERA_GROUPS", {"team": TEAM})


def _mock_seqera(monkeypatch: pytest.MonkeyPatch, handler: Handler) -> list[httpx.Request]:
    """Route the module's httpx client through *handler*; return the captured requests."""
    requests: list[httpx.Request] = []

    def _record(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return handler(request)

    real_client = httpx.AsyncClient

    def _factory(**kwargs: Any) -> httpx.AsyncClient:
        return real_client(transport=httpx.MockTransport(_record), **kwargs)

    monkeypatch.setattr("nf_core_bot.checks.seqera.httpx.AsyncClient", _factory)
    return requests


def _slack_client(email: str | None = "slack@example.org") -> AsyncMock:
    client = make_slack_client()
    profile = {"email": email} if email else {}
    client.users_info.return_value = {"user": {"profile": profile}}
    return client


# ── checks.seqera: groups ────────────────────────────────────────────


class TestGroups:
    def test_megatests_from_config(self, seqera_env: None) -> None:
        groups = seqera.seqera_groups()
        assert groups["megatests"].workspace_id == "22"
        assert groups["megatests"].role == "nf-core-read-only"
        assert groups["megatests"].target_key == "22"
        assert groups["team"].target_key == "TEAM#77"

    def test_unconfigured_megatests_has_no_target(self) -> None:
        assert seqera.seqera_groups()["megatests"].target_key is None


class TestAddToGroup:
    async def test_unknown_group(self, seqera_env: None) -> None:
        result = await add_to_group(_slack_client(), "U1", "octocat", "nope")
        assert result.status is SeqeraStatus.UNKNOWN_GROUP

    async def test_team_add_recorded(self, monkeypatch: pytest.MonkeyPatch, seqera_env: None, ddb_table: Any) -> None:
        requests = _mock_seqera(monkeypatch, lambda r: httpx.Response(200, json={"member": {"memberId": 5}}))

        result = await add_to_group(_slack_client(), "U1", "octocat", "team", "me@example.org")

        assert result.status is SeqeraStatus.ADDED
        assert requests[0].method == "POST"
        assert str(requests[0].url) == "https://api.cloud.seqera.io/orgs/11/teams/77/members"
        assert b'"userNameOrEmail":"me@example.org"' in requests[0].content.replace(b" ", b"")
        member = await get_member("TEAM#77", "U1")
        assert member is not None
        assert member.participant_id == 5
        assert member.group == "team"


class TestRemoveFromGroup:
    async def test_not_managed(self, monkeypatch: pytest.MonkeyPatch, seqera_env: None, ddb_table: Any) -> None:
        requests = _mock_seqera(monkeypatch, lambda r: httpx.Response(204))

        result = await remove_from_group("U1", "megatests")

        assert result.status is SeqeraStatus.NOT_MANAGED
        assert not requests

    async def test_removes_team_member(self, monkeypatch: pytest.MonkeyPatch, seqera_env: None, ddb_table: Any) -> None:
        requests = _mock_seqera(monkeypatch, lambda r: httpx.Response(204))
        await put_member("TEAM#77", "U1", "octocat", "a@example.org", 5, group="team")

        result = await remove_from_group("U1", "team")

        assert result.status is SeqeraStatus.REMOVED
        assert requests[0].method == "DELETE"
        assert str(requests[0].url) == "https://api.cloud.seqera.io/orgs/11/teams/77/members/5/delete"
        assert await get_member("TEAM#77", "U1") is None

    async def test_api_error_keeps_record(
        self, monkeypatch: pytest.MonkeyPatch, seqera_env: None, ddb_table: Any
    ) -> None:
        _mock_seqera(monkeypatch, lambda r: httpx.Response(403, json={"message": "Operation not allowed"}))
        await put_member("22", "U1", "octocat", "a@example.org", 9)

        result = await remove_from_group("U1", "megatests")

        assert result.status is SeqeraStatus.API_ERROR
        assert "403" in result.message
        assert await get_member("22", "U1") is not None

    async def test_not_configured(self, ddb_table: Any) -> None:
        result = await remove_from_group("U1", "megatests")
        assert result.status is SeqeraStatus.NOT_CONFIGURED


class TestGroupsForUser:
    async def test_lists_recorded_groups(self, seqera_env: None, ddb_table: Any) -> None:
        await put_member("22", "U1", "octocat", "a@example.org", 9)
        await put_member("TEAM#77", "U1", "octocat", "a@example.org", 5, group="team")
        await put_member("22", "U2", "hubot", "b@example.org", 10)

        found = await groups_for_user("U1")

        assert [name for name, _ in found] == ["megatests", "team"]


class TestRemovalSyncTeams:
    async def test_dry_run_covers_team_groups(self, seqera_env: None, ddb_table: Any) -> None:
        await put_member("TEAM#77", "U1", "left-user", "a@example.org", 5, group="team")

        with patch("nf_core_bot.scheduler.seqera_jobs.get_org_membership_state", return_value=None):
            summary = await seqera_jobs.sync_seqera_removals()

        assert summary is not None
        assert summary.checked == 1
        assert len(summary.would_remove) == 1
        assert "team" in summary.would_remove[0]


# ── commands.seqera.manage ───────────────────────────────────────────


class TestParseEmail:
    @pytest.mark.parametrize(
        "args",
        [
            ["<@U1>", "megatests", "--email", "me@x.org"],
            ["<@U1>", "--email=me@x.org", "megatests"],
            ["<@U1>", "megatests", "--email", "<mailto:me@x.org|me@x.org>"],
        ],
    )
    def test_forms(self, args: list[str]) -> None:
        assert manage._parse_email(args) == (["<@U1>", "megatests"], "me@x.org", True)

    @pytest.mark.parametrize("args", [["<@U1>", "megatests", "--email"], ["<@U1>", "megatests", "--email", "nope"]])
    def test_invalid(self, args: list[str]) -> None:
        assert manage._parse_email(args)[2] is False


class TestAddCommand:
    async def test_usage_on_bad_args(self, seqera_env: None) -> None:
        respond = AsyncMock()
        await manage.handle_seqera_add(respond, AsyncMock(), "U_CALLER", ["octocat", "megatests"])
        assert respond.await_args.args[0] == manage.ADD_USAGE

    async def test_unknown_group(self, seqera_env: None) -> None:
        respond = AsyncMock()
        await manage.handle_seqera_add(respond, AsyncMock(), "U_CALLER", ["<@U1>", "nope"])
        assert "Unknown Seqera group `nope`" in respond.await_args.args[0]
        assert "`megatests`" in respond.await_args.args[0]

    async def test_requires_github_username(self, seqera_env: None) -> None:
        respond = AsyncMock()
        with (
            patch.object(manage, "get_github_username", new=AsyncMock(return_value=None)),
            patch.object(manage, "add_to_group", new=AsyncMock()) as mock_add,
        ):
            await manage.handle_seqera_add(respond, AsyncMock(), "U_CALLER", ["<@U1>", "megatests"])
        assert "no GitHub username" in respond.await_args.args[0]
        mock_add.assert_not_awaited()

    async def test_added_with_email_override(self, seqera_env: None) -> None:
        respond = AsyncMock()
        client = AsyncMock()
        result = seqera.SeqeraResult(SeqeraStatus.ADDED, "added", "me@x.org")
        with (
            patch.object(manage, "get_github_username", new=AsyncMock(return_value="octocat")),
            patch.object(manage, "add_to_group", new=AsyncMock(return_value=result)) as mock_add,
        ):
            await manage.handle_seqera_add(
                respond, client, "U_CALLER", ["<@U1|alice>", "MEGATESTS", "--email", "me@x.org"]
            )
        mock_add.assert_awaited_once_with(client, "U1", "octocat", "megatests", "me@x.org")
        assert "Added <@U1> to `megatests` as `me@x.org`" in respond.await_args.args[0]
        assert respond.await_args.kwargs["response_type"] == "ephemeral"

    async def test_no_account_suggests_email(self, seqera_env: None) -> None:
        respond = AsyncMock()
        result = seqera.SeqeraResult(SeqeraStatus.NO_ACCOUNT, "no Seqera Platform account was found", "s@x.org")
        with (
            patch.object(manage, "get_github_username", new=AsyncMock(return_value="octocat")),
            patch.object(manage, "add_to_group", new=AsyncMock(return_value=result)),
        ):
            await manage.handle_seqera_add(respond, AsyncMock(), "U_CALLER", ["<@U1>", "megatests"])
        assert "--email" in respond.await_args.args[0]


class TestRemoveCommand:
    async def test_usage(self) -> None:
        respond = AsyncMock()
        await manage.handle_seqera_remove(respond, AsyncMock(), "U_CALLER", ["<@U1>"])
        assert respond.await_args.args[0] == manage.REMOVE_USAGE

    async def test_removed(self) -> None:
        respond = AsyncMock()
        result = seqera.SeqeraResult(SeqeraStatus.REMOVED, "removed")
        with patch.object(manage, "remove_from_group", new=AsyncMock(return_value=result)) as mock_remove:
            await manage.handle_seqera_remove(respond, AsyncMock(), "U_CALLER", ["<@U1>", "megatests"])
        mock_remove.assert_awaited_once_with("U1", "megatests")
        assert "Removed <@U1> from `megatests`" in respond.await_args.args[0]

    async def test_not_managed(self) -> None:
        respond = AsyncMock()
        result = seqera.SeqeraResult(SeqeraStatus.NOT_MANAGED, "the bot has no record")
        with patch.object(manage, "remove_from_group", new=AsyncMock(return_value=result)):
            await manage.handle_seqera_remove(respond, AsyncMock(), "U_CALLER", ["<@U1>", "megatests"])
        assert "Couldn't remove" in respond.await_args.args[0]
        assert "no record" in respond.await_args.args[0]


class TestListCommand:
    async def test_all_groups(self, seqera_env: None, ddb_table: Any) -> None:
        await put_member("22", "U1", "octocat", "a@example.org", 9)
        respond = AsyncMock()

        await manage.handle_seqera_list(respond, AsyncMock(), "U_CALLER", [])

        text = respond.await_args.args[0]
        assert "`megatests` — nf-core/megatests workspace (read-only): 1 member added by the bot" in text
        assert "`team` — test team: 0 members added by the bot" in text

    async def test_unconfigured_group(self, ddb_table: Any) -> None:
        respond = AsyncMock()
        await manage.handle_seqera_list(respond, AsyncMock(), "U_CALLER", [])
        assert "_(not configured)_" in respond.await_args.args[0]

    async def test_user_groups(self, seqera_env: None, ddb_table: Any) -> None:
        await put_member("22", "U1", "octocat", "a@example.org", 9)
        respond = AsyncMock()

        await manage.handle_seqera_list(respond, AsyncMock(), "U_CALLER", ["<@U1>"])

        text = respond.await_args.args[0]
        assert "`megatests` — as `a@example.org`" in text
        assert "team" not in text.split("\n", 1)[1]

    async def test_user_with_no_groups(self, seqera_env: None, ddb_table: Any) -> None:
        respond = AsyncMock()
        await manage.handle_seqera_list(respond, AsyncMock(), "U_CALLER", ["<@U1>"])
        assert "hasn't added <@U1>" in respond.await_args.args[0]
        assert await list_members("22") == []


# ── Router gate ──────────────────────────────────────────────────────


class TestRouter:
    async def test_dispatch_routes_seqera(self) -> None:
        with patch.object(router, "_route_seqera", new=AsyncMock()) as mock_route:
            await router.dispatch(AsyncMock(), AsyncMock(), AsyncMock(), {"text": "seqera list", "user_id": "U1"})
        assert mock_route.await_args.args[-1] == ["list"]

    async def test_non_member_denied(self) -> None:
        ack, respond = AsyncMock(), AsyncMock()
        with patch.object(router, "is_core_team", new=AsyncMock(return_value=False)):
            await router._route_seqera(ack, respond, AsyncMock(), "U1", ["list"])
        ack.assert_awaited_once()
        assert "restricted to `@core-team`" in respond.await_args.args[0]

    async def test_member_dispatched(self) -> None:
        ack, respond, client = AsyncMock(), AsyncMock(), AsyncMock()
        handler = AsyncMock()
        with (
            patch.object(router, "is_core_team", new=AsyncMock(return_value=True)),
            patch.dict(router._SEQERA_DISPATCH, {"add": handler}),
        ):
            await router._route_seqera(ack, respond, client, "U1", ["add", "<@U2>", "megatests"])
        ack.assert_awaited_once()
        handler.assert_awaited_once_with(respond, client, "U1", ["<@U2>", "megatests"])

    async def test_help(self) -> None:
        ack, respond = AsyncMock(), AsyncMock()
        with patch.object(router, "is_core_team", new=AsyncMock(return_value=True)):
            await router._route_seqera(ack, respond, AsyncMock(), "U1", [])
        assert "seqera add @user <group>" in respond.await_args.args[0]

    async def test_unknown_subcommand(self) -> None:
        ack, respond = AsyncMock(), AsyncMock()
        with patch.object(router, "is_core_team", new=AsyncMock(return_value=True)):
            await router._route_seqera(ack, respond, AsyncMock(), "U1", ["bogus"])
        assert "Unknown seqera command" in respond.await_args.args[0]
