"""Tests for Seqera workspace access: checks.seqera, db.seqera and the removal job."""

from __future__ import annotations

import datetime
from collections.abc import Callable
from typing import Any
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from nf_core_bot.checks.github import get_org_membership_state
from nf_core_bot.checks.seqera import SeqeraStatus, add_to_megatests, remove_participant
from nf_core_bot.db.seqera import delete_member, list_members, put_member
from nf_core_bot.scheduler import seqera_jobs
from tests.helpers import make_slack_client

Handler = Callable[[httpx.Request], httpx.Response]


@pytest.fixture
def seqera_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SEQERA_TOKEN", "seqera-token")
    monkeypatch.setenv("SEQERA_ORG_ID", "11")
    monkeypatch.setenv("SEQERA_WORKSPACE_ID", "22")


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


def _conflict_then_search(participants: list[dict[str, Any]]) -> Handler:
    """409 on the add, then *participants* from the participant search."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "PUT":
            return httpx.Response(409, json={"message": "collaborator not permitted for organization with active SSO"})
        return httpx.Response(200, json={"participants": participants, "totalSize": len(participants)})

    return handler


def _slack_client(email: str | None = "slack@example.org") -> AsyncMock:
    client = make_slack_client()
    profile = {"email": email} if email else {}
    client.users_info.return_value = {"user": {"profile": profile}}
    return client


# ── add_to_megatests ─────────────────────────────────────────────────


class TestAddToMegatests:
    async def test_not_configured_makes_no_calls(self, monkeypatch: pytest.MonkeyPatch) -> None:
        requests = _mock_seqera(monkeypatch, lambda r: httpx.Response(200))
        client = _slack_client()

        result = await add_to_megatests(client, "U1", "octocat")

        assert result.status is SeqeraStatus.NOT_CONFIGURED
        assert not requests
        client.users_info.assert_not_awaited()

    async def test_added_and_recorded(self, monkeypatch: pytest.MonkeyPatch, seqera_env: None, ddb_table: Any) -> None:
        requests = _mock_seqera(monkeypatch, lambda r: httpx.Response(200, json={"participant": {"participantId": 99}}))

        result = await add_to_megatests(_slack_client(), "U1", "octocat")

        assert result.status is SeqeraStatus.ADDED
        assert result.has_access
        assert result.email == "slack@example.org"
        assert requests[0].method == "PUT"
        assert str(requests[0].url) == "https://api.cloud.seqera.io/orgs/11/workspaces/22/participants/add"
        assert requests[0].headers["Authorization"] == "Bearer seqera-token"
        assert b'"userNameOrEmail":"slack@example.org"' in requests[0].content.replace(b" ", b"")
        assert b'"role":"nf-core-read-only"' in requests[0].content.replace(b" ", b"")

        members = await list_members("22")
        assert len(members) == 1
        assert members[0].slack_user_id == "U1"
        assert members[0].github_username == "octocat"
        assert members[0].email == "slack@example.org"
        assert members[0].participant_id == 99

    async def test_form_email_overrides_slack_email(
        self, monkeypatch: pytest.MonkeyPatch, seqera_env: None, ddb_table: Any
    ) -> None:
        requests = _mock_seqera(monkeypatch, lambda r: httpx.Response(200, json={"participant": {"participantId": 1}}))
        client = _slack_client()

        result = await add_to_megatests(client, "U1", "octocat", "platform@example.org")

        assert result.email == "platform@example.org"
        assert b"platform@example.org" in requests[0].content
        client.users_info.assert_not_awaited()

    async def test_no_email(self, monkeypatch: pytest.MonkeyPatch, seqera_env: None) -> None:
        requests = _mock_seqera(monkeypatch, lambda r: httpx.Response(200))

        result = await add_to_megatests(_slack_client(email=None), "U1", "octocat")

        assert result.status is SeqeraStatus.NO_EMAIL
        assert not requests

    async def test_already_participant_not_recorded(
        self, monkeypatch: pytest.MonkeyPatch, seqera_env: None, ddb_table: Any
    ) -> None:
        requests = _mock_seqera(
            monkeypatch,
            _conflict_then_search([{"email": "Slack@Example.org", "participantId": 5}]),
        )

        result = await add_to_megatests(_slack_client(), "U1", "octocat")

        assert result.status is SeqeraStatus.ALREADY_PARTICIPANT
        assert result.has_access
        assert await list_members("22") == []
        assert requests[1].method == "GET"
        assert requests[1].url.params["search"] == "slack@example.org"

    async def test_conflict_without_participant_is_error(
        self, monkeypatch: pytest.MonkeyPatch, seqera_env: None
    ) -> None:
        _mock_seqera(monkeypatch, _conflict_then_search([]))

        result = await add_to_megatests(_slack_client(), "U1", "octocat")

        assert result.status is SeqeraStatus.API_ERROR
        assert not result.has_access
        assert "409" in result.message
        assert "collaborator not permitted" in result.message

    async def test_conflict_with_failed_lookup_is_error(
        self, monkeypatch: pytest.MonkeyPatch, seqera_env: None
    ) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.method == "PUT":
                return httpx.Response(409, json={"message": "Duplicate element"})
            return httpx.Response(500)

        _mock_seqera(monkeypatch, handler)

        result = await add_to_megatests(_slack_client(), "U1", "octocat")

        assert result.status is SeqeraStatus.API_ERROR
        assert "409" in result.message

    async def test_no_account(self, monkeypatch: pytest.MonkeyPatch, seqera_env: None) -> None:
        _mock_seqera(monkeypatch, lambda r: httpx.Response(404, json={"message": "User not found"}))

        result = await add_to_megatests(_slack_client(), "U1", "octocat")

        assert result.status is SeqeraStatus.NO_ACCOUNT
        assert not result.has_access
        assert "slack@example.org" in result.message
        assert "User not found" in result.message

    async def test_api_error_includes_status_and_message(
        self, monkeypatch: pytest.MonkeyPatch, seqera_env: None
    ) -> None:
        _mock_seqera(monkeypatch, lambda r: httpx.Response(403, json={"message": "Operation not allowed"}))

        result = await add_to_megatests(_slack_client(), "U1", "octocat")

        assert result.status is SeqeraStatus.API_ERROR
        assert "403" in result.message
        assert "Operation not allowed" in result.message

    async def test_network_error(self, monkeypatch: pytest.MonkeyPatch, seqera_env: None) -> None:
        def _raise(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("boom", request=request)

        _mock_seqera(monkeypatch, _raise)

        result = await add_to_megatests(_slack_client(), "U1", "octocat")

        assert result.status is SeqeraStatus.API_ERROR
        assert "ConnectError" in result.message


# ── remove_participant ───────────────────────────────────────────────


class TestRemoveParticipant:
    @pytest.mark.parametrize("status", [204, 404])
    async def test_gone(self, monkeypatch: pytest.MonkeyPatch, seqera_env: None, status: int) -> None:
        requests = _mock_seqera(monkeypatch, lambda r: httpx.Response(status))

        assert await remove_participant(99) is True
        assert requests[0].method == "DELETE"
        assert str(requests[0].url) == "https://api.cloud.seqera.io/orgs/11/workspaces/22/participants/99"

    async def test_error_raises(self, monkeypatch: pytest.MonkeyPatch, seqera_env: None) -> None:
        _mock_seqera(monkeypatch, lambda r: httpx.Response(500, json={"message": "nope"}))

        with pytest.raises(RuntimeError, match="500"):
            await remove_participant(99)


# ── db.seqera ────────────────────────────────────────────────────────


class TestSeqeraDb:
    async def test_put_list_delete(self, ddb_table: Any) -> None:
        await put_member("22", "U1", "octocat", "a@example.org", 1)
        await put_member("22", "U2", "hubot", "b@example.org", 2)
        await put_member("33", "U3", "other", "c@example.org", 3)

        members = await list_members("22")
        assert sorted(m.slack_user_id for m in members) == ["U1", "U2"]

        await delete_member("22", "U1")
        assert [m.slack_user_id for m in await list_members("22")] == ["U2"]


# ── get_org_membership_state ─────────────────────────────────────────


class TestGetOrgMembershipState:
    @pytest.mark.parametrize(
        ("status", "body", "expected"),
        [(200, {"state": "active"}, "active"), (200, {"state": "pending"}, "pending"), (404, None, None)],
    )
    async def test_states(
        self, monkeypatch: pytest.MonkeyPatch, status: int, body: dict[str, str] | None, expected: str | None
    ) -> None:
        async def mock_get(path: str) -> httpx.Response:
            assert path == "/orgs/nf-core/memberships/octocat"
            return httpx.Response(status, json=body, request=httpx.Request("GET", "https://api.github.com"))

        monkeypatch.setattr("nf_core_bot.checks.github._github_get", mock_get)
        assert await get_org_membership_state("octocat") == expected

    async def test_other_status_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        async def mock_get(path: str) -> httpx.Response:
            return httpx.Response(502, text="bad gateway", request=httpx.Request("GET", "https://api.github.com"))

        monkeypatch.setattr("nf_core_bot.checks.github._github_get", mock_get)
        with pytest.raises(RuntimeError):
            await get_org_membership_state("octocat")


# ── Weekly removal job ───────────────────────────────────────────────


async def _seed_members() -> None:
    await put_member("22", "U_ACTIVE", "active-user", "a@example.org", 1)
    await put_member("22", "U_PENDING", "pending-user", "p@example.org", 2)
    await put_member("22", "U_LEFT", "left-user", "l@example.org", 3)
    await put_member("22", "U_ERR", "error-user", "e@example.org", 4)


async def _membership(username: str) -> str | None:
    states = {"active-user": "active", "pending-user": "pending", "left-user": None}
    if username not in states:
        raise RuntimeError("GitHub API down")
    return states[username]


class TestSeqeraRemovalSync:
    async def test_not_configured(self, ddb_table: Any) -> None:
        assert await seqera_jobs.sync_seqera_removals() is None

    @patch("nf_core_bot.scheduler.seqera_jobs.remove_participant")
    @patch("nf_core_bot.scheduler.seqera_jobs.get_org_membership_state", side_effect=_membership)
    async def test_dry_run_only_logs(
        self, _state: AsyncMock, mock_remove: AsyncMock, seqera_env: None, ddb_table: Any
    ) -> None:
        await _seed_members()

        summary = await seqera_jobs.sync_seqera_removals()

        assert summary is not None
        assert summary.dry_run is True
        assert summary.checked == 4
        assert [label.split()[0] for label in summary.would_remove] == ["left-user"]
        assert summary.removed == []
        assert len(summary.errors) == 1
        mock_remove.assert_not_awaited()
        assert len(await list_members("22")) == 4

    @patch("nf_core_bot.scheduler.seqera_jobs.remove_participant", return_value=True)
    @patch("nf_core_bot.scheduler.seqera_jobs.get_org_membership_state", side_effect=_membership)
    async def test_live_removes_only_leavers(
        self,
        _state: AsyncMock,
        mock_remove: AsyncMock,
        seqera_env: None,
        ddb_table: Any,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("SEQERA_REMOVAL_DRY_RUN", "false")
        await _seed_members()

        summary = await seqera_jobs.sync_seqera_removals()

        assert summary is not None
        assert summary.dry_run is False
        assert [label.split()[0] for label in summary.removed] == ["left-user"]
        mock_remove.assert_awaited_once_with(3)
        remaining = sorted(m.slack_user_id for m in await list_members("22"))
        assert remaining == ["U_ACTIVE", "U_ERR", "U_PENDING"]

    @patch("nf_core_bot.scheduler.seqera_jobs.remove_participant", side_effect=RuntimeError("HTTP 500"))
    @patch("nf_core_bot.scheduler.seqera_jobs.get_org_membership_state", return_value=None)
    async def test_failed_removal_keeps_record(
        self,
        _state: AsyncMock,
        _remove: AsyncMock,
        seqera_env: None,
        ddb_table: Any,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("SEQERA_REMOVAL_DRY_RUN", "false")
        await put_member("22", "U_LEFT", "left-user", "l@example.org", 3)

        summary = await seqera_jobs.sync_seqera_removals()

        assert summary is not None
        assert summary.removed == []
        assert len(summary.errors) == 1
        assert len(await list_members("22")) == 1


class TestSeqeraTick:
    @patch("nf_core_bot.scheduler.seqera_jobs.sync_seqera_removals")
    async def test_runs_once_on_monday_target_hour(self, mock_sync: AsyncMock, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(seqera_jobs, "_last_weekly_run", None)
        monday = datetime.datetime(2026, 10, 19, seqera_jobs.TARGET_HOUR_UTC, 5, tzinfo=datetime.UTC)

        await seqera_jobs._tick(monday)
        await seqera_jobs._tick(monday + datetime.timedelta(minutes=10))

        mock_sync.assert_awaited_once()

    @patch("nf_core_bot.scheduler.seqera_jobs.sync_seqera_removals")
    async def test_skips_other_times(self, mock_sync: AsyncMock, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(seqera_jobs, "_last_weekly_run", None)
        tuesday = datetime.datetime(2026, 10, 20, seqera_jobs.TARGET_HOUR_UTC, 5, tzinfo=datetime.UTC)
        monday_early = datetime.datetime(2026, 10, 19, 3, 0, tzinfo=datetime.UTC)

        await seqera_jobs._tick(tuesday)
        await seqera_jobs._tick(monday_early)

        mock_sync.assert_not_awaited()
