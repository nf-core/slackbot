"""Tests for nf_core_bot.checks.github."""

from __future__ import annotations

import httpx
import pytest

from nf_core_bot.checks.github import (
    GitHubResult,
    add_to_team,
    check_org_membership,
    check_user_exists,
    close_client,
    invite_to_org,
)


@pytest.fixture(autouse=True)
async def _close_shared_client() -> None:  # type: ignore[misc]
    """Ensure the module-level httpx client is closed between tests."""
    yield  # type: ignore[misc]
    await close_client()


def _mock_response(status_code: int, json_body: dict | None = None, text: str = "") -> httpx.Response:
    """Build a fake ``httpx.Response``."""
    request = httpx.Request("GET", "https://api.github.com/test")
    if json_body is not None:
        return httpx.Response(status_code=status_code, json=json_body, request=request)
    return httpx.Response(status_code=status_code, text=text, request=request)


# ── check_org_membership ─────────────────────────────────────────────


class TestCheckOrgMembership:
    async def test_member(self, monkeypatch: pytest.MonkeyPatch) -> None:
        async def mock_get(path: str) -> httpx.Response:
            return _mock_response(204)

        monkeypatch.setattr("nf_core_bot.checks.github._github_get", mock_get)
        result = await check_org_membership("octocat")
        assert result.ok is True
        assert "already a member" in result.message

    async def test_not_member(self, monkeypatch: pytest.MonkeyPatch) -> None:
        async def mock_get(path: str) -> httpx.Response:
            return _mock_response(404)

        monkeypatch.setattr("nf_core_bot.checks.github._github_get", mock_get)
        result = await check_org_membership("octocat")
        assert result.ok is False
        assert "not a member" in result.message

    async def test_unexpected_status(self, monkeypatch: pytest.MonkeyPatch) -> None:
        async def mock_get(path: str) -> httpx.Response:
            return _mock_response(500, text="Internal Server Error")

        monkeypatch.setattr("nf_core_bot.checks.github._github_get", mock_get)
        result = await check_org_membership("octocat")
        assert result.ok is False
        assert "500" in result.message


# ── check_user_exists ────────────────────────────────────────────────


class TestCheckUserExists:
    async def test_exists(self, monkeypatch: pytest.MonkeyPatch) -> None:
        async def mock_get(path: str) -> httpx.Response:
            return _mock_response(200, json_body={"login": "octocat"})

        monkeypatch.setattr("nf_core_bot.checks.github._github_get", mock_get)
        result = await check_user_exists("octocat")
        assert result.ok is True

    async def test_not_found(self, monkeypatch: pytest.MonkeyPatch) -> None:
        async def mock_get(path: str) -> httpx.Response:
            return _mock_response(404)

        monkeypatch.setattr("nf_core_bot.checks.github._github_get", mock_get)
        result = await check_user_exists("no-such-user")
        assert result.ok is False
        assert "does not exist" in result.message


# ── invite_to_org ────────────────────────────────────────────────────


class TestInviteToOrg:
    async def test_success_201(self, monkeypatch: pytest.MonkeyPatch) -> None:
        async def mock_put(path: str, *, json: dict) -> httpx.Response:  # type: ignore[type-arg]
            return _mock_response(201, json_body={"state": "pending"})

        monkeypatch.setattr("nf_core_bot.checks.github._github_put", mock_put)
        result = await invite_to_org("octocat")
        assert result.ok is True
        assert "pending" in result.message

    async def test_idempotent_200(self, monkeypatch: pytest.MonkeyPatch) -> None:
        async def mock_put(path: str, *, json: dict) -> httpx.Response:  # type: ignore[type-arg]
            return _mock_response(200, json_body={"state": "active"})

        monkeypatch.setattr("nf_core_bot.checks.github._github_put", mock_put)
        result = await invite_to_org("octocat")
        assert result.ok is True

    async def test_failure_422(self, monkeypatch: pytest.MonkeyPatch) -> None:
        async def mock_put(path: str, *, json: dict) -> httpx.Response:  # type: ignore[type-arg]
            return _mock_response(422, text="Validation failed")

        monkeypatch.setattr("nf_core_bot.checks.github._github_put", mock_put)
        result = await invite_to_org("octocat")
        assert result.ok is False
        assert "422" in result.message


# ── add_to_team ──────────────────────────────────────────────────────


class TestAddToTeam:
    async def test_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        async def mock_put(path: str, *, json: dict) -> httpx.Response:  # type: ignore[type-arg]
            assert "contributors" in path
            return _mock_response(200, json_body={"state": "active"})

        monkeypatch.setattr("nf_core_bot.checks.github._github_put", mock_put)
        result = await add_to_team("octocat")
        assert result.ok is True

    async def test_custom_team_slug(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured_path: str = ""

        async def mock_put(path: str, *, json: dict) -> httpx.Response:  # type: ignore[type-arg]
            nonlocal captured_path
            captured_path = path
            return _mock_response(200, json_body={"state": "active"})

        monkeypatch.setattr("nf_core_bot.checks.github._github_put", mock_put)
        await add_to_team("octocat", team_slug="my-team")
        assert "my-team" in captured_path

    async def test_failure_403(self, monkeypatch: pytest.MonkeyPatch) -> None:
        async def mock_put(path: str, *, json: dict) -> httpx.Response:  # type: ignore[type-arg]
            return _mock_response(403, text="Forbidden")

        monkeypatch.setattr("nf_core_bot.checks.github._github_put", mock_put)
        result = await add_to_team("octocat")
        assert result.ok is False


# ── GitHubResult ─────────────────────────────────────────────────────


class TestGitHubResult:
    def test_dataclass_fields(self) -> None:
        r = GitHubResult(ok=True, message="done")
        assert r.ok is True
        assert r.message == "done"
