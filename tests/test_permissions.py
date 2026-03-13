"""Tests for nf_core_bot.permissions.checks."""

from __future__ import annotations

import time
from unittest.mock import AsyncMock

import pytest

import nf_core_bot.permissions.checks as perms


@pytest.fixture(autouse=True)
def _reset_cache() -> None:
    """Clear the core-team cache before each test."""
    perms._core_team_ids = set()
    perms._core_team_fetched_at = 0.0
    perms._core_team_lock = None


def _make_client(group_handle: str = "core-team", members: list[str] | None = None) -> AsyncMock:
    """Build a mock Slack client that returns a single usergroup with *members*."""
    if members is None:
        members = ["U_ADMIN"]

    client = AsyncMock()
    client.usergroups_list.return_value = {"usergroups": [{"id": "G123", "handle": group_handle}]}
    client.usergroups_users_list.return_value = {"users": members}
    return client


# ── refresh_core_team ────────────────────────────────────────────────


class TestRefreshCoreTeam:
    async def test_fetches_members(self) -> None:
        client = _make_client(members=["U1", "U2"])
        members = await perms.refresh_core_team(client, "core-team")
        assert members == {"U1", "U2"}

    async def test_caches_result(self) -> None:
        client = _make_client(members=["U1"])
        await perms.refresh_core_team(client, "core-team")
        await perms.refresh_core_team(client, "core-team")

        # Second call should hit cache — only 1 API call each
        assert client.usergroups_list.await_count == 1
        assert client.usergroups_users_list.await_count == 1

    async def test_refreshes_after_ttl(self) -> None:
        client = _make_client(members=["U1"])
        await perms.refresh_core_team(client, "core-team")

        # Fake TTL expiration
        perms._core_team_fetched_at = time.monotonic() - perms.CACHE_TTL - 1

        await perms.refresh_core_team(client, "core-team")
        assert client.usergroups_list.await_count == 2

    async def test_group_not_found(self) -> None:
        client = _make_client(group_handle="other-team")
        members = await perms.refresh_core_team(client, "core-team")
        assert members == set()

    async def test_api_failure_preserves_stale_cache(self) -> None:
        """If refresh fails, the old cache should still be returned."""
        client = _make_client(members=["U1"])
        await perms.refresh_core_team(client, "core-team")

        # Expire cache
        perms._core_team_fetched_at = time.monotonic() - perms.CACHE_TTL - 1

        # Make the next call fail
        client.usergroups_list.side_effect = RuntimeError("network error")
        members = await perms.refresh_core_team(client, "core-team")

        # Should return stale data (the lock catches the exception)
        assert members == {"U1"}


# ── is_core_team ─────────────────────────────────────────────────────


class TestIsCoreTeam:
    async def test_returns_true_for_member(self) -> None:
        client = _make_client(members=["U_ADMIN"])
        assert await perms.is_core_team(client, "U_ADMIN", "core-team") is True

    async def test_returns_false_for_non_member(self) -> None:
        client = _make_client(members=["U_ADMIN"])
        assert await perms.is_core_team(client, "U_OTHER", "core-team") is False

    async def test_uses_config_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """When no handle is passed, it falls back to config."""
        monkeypatch.setenv("CORE_TEAM_USERGROUP_HANDLE", "my-team")
        client = _make_client(group_handle="my-team", members=["U1"])

        # Force re-read of config by clearing the cache that config.py may hold
        import importlib

        import nf_core_bot.config

        importlib.reload(nf_core_bot.config)

        assert await perms.is_core_team(client, "U1") is True
