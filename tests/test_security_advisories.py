"""Tests for the daily security advisory scheduler."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import httpx
import pytest

from nf_core_bot.checks.github import SecurityAdvisory, close_client


@pytest.fixture(autouse=True)
async def _close_shared_client() -> None:  # type: ignore[misc]
    """Ensure the module-level httpx client is closed between tests."""
    yield  # type: ignore[misc]
    await close_client()


@pytest.fixture
def client() -> AsyncMock:
    mock = AsyncMock()
    mock.chat_postMessage.return_value = {"ts": "1700000000.000100"}
    return mock


def _mock_response(
    status_code: int, json_body: list | dict | None = None, text: str = "", link: str = ""
) -> httpx.Response:
    request = httpx.Request("GET", "https://api.github.com/test")
    headers = {"Link": link} if link else {}
    if json_body is not None:
        return httpx.Response(status_code=status_code, json=json_body, request=request, headers=headers)
    return httpx.Response(status_code=status_code, text=text, request=request, headers=headers)


def _advisory(repo: str, ghsa_id: str, state: str = "triage", updated_at: str = "2026-08-01T00:00:00Z") -> dict:
    return {
        "ghsa_id": ghsa_id,
        "summary": f"Summary for {ghsa_id}",
        "state": state,
        "severity": "high",
        "updated_at": updated_at,
        "html_url": f"https://github.com/nf-core/{repo}/security/advisories/{ghsa_id}",
        "url": f"https://api.github.com/repos/nf-core/{repo}/security-advisories/{ghsa_id}",
    }


# ── checks.github: list_all_org_advisories ─────────────────────────────


class TestListAllOrgAdvisories:
    async def test_extracts_repo_from_url_and_paginates(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from nf_core_bot.checks.github import list_all_org_advisories

        pages = [
            _mock_response(
                200,
                json_body=[_advisory("rnaseq", "GHSA-pq68-g636-8gwf")],
                link='<https://api.github.com/orgs/nf-core/security-advisories?after=CURSOR>; rel="next"',
            ),
            _mock_response(200, json_body=[_advisory("sarek", "GHSA-aaaa-bbbb-cccc", state="published")]),
        ]

        calls: list[str] = []

        async def mock_get(path: str) -> httpx.Response:
            calls.append(path)
            return pages.pop(0)

        monkeypatch.setattr("nf_core_bot.checks.github._github_get", mock_get)
        advisories = await list_all_org_advisories()

        assert len(advisories) == 2
        assert advisories[0].repo == "rnaseq"
        assert advisories[0].ghsa_id == "GHSA-pq68-g636-8gwf"
        assert advisories[1].repo == "sarek"
        # Second call followed the cursor from the Link header.
        assert calls[1] == "https://api.github.com/orgs/nf-core/security-advisories?after=CURSOR"

    async def test_raises_on_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from nf_core_bot.checks.github import list_all_org_advisories

        async def mock_get(path: str) -> httpx.Response:
            return _mock_response(403, text="Forbidden — not a security manager")

        monkeypatch.setattr("nf_core_bot.checks.github._github_get", mock_get)
        with pytest.raises(RuntimeError, match="403"):
            await list_all_org_advisories()

    async def test_falls_back_to_unknown_repo_if_url_unparseable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from nf_core_bot.checks.github import list_all_org_advisories

        async def mock_get(path: str) -> httpx.Response:
            return _mock_response(200, json_body=[{"ghsa_id": "GHSA-x", "url": "not-a-real-url"}])

        monkeypatch.setattr("nf_core_bot.checks.github._github_get", mock_get)
        advisories = await list_all_org_advisories()
        assert advisories[0].repo == "unknown"


# ── db.advisories ──────────────────────────────────────────────────────


class TestAdvisoryStateStorage:
    async def test_round_trips(self, ddb_table) -> None:
        from nf_core_bot.db.advisories import get_known_advisories, save_advisory_state

        await save_advisory_state("rnaseq", "GHSA-pq68-g636-8gwf", "triage", "2026-08-01T00:00:00Z")
        known = await get_known_advisories("rnaseq")
        assert known == {"GHSA-pq68-g636-8gwf": {"state": "triage", "updated_at": "2026-08-01T00:00:00Z"}}

    async def test_scoped_per_repo(self, ddb_table) -> None:
        from nf_core_bot.db.advisories import get_known_advisories, save_advisory_state

        await save_advisory_state("rnaseq", "GHSA-aaaa", "triage", "2026-08-01T00:00:00Z")
        await save_advisory_state("sarek", "GHSA-bbbb", "triage", "2026-08-01T00:00:00Z")
        assert "GHSA-aaaa" in await get_known_advisories("rnaseq")
        assert "GHSA-aaaa" not in await get_known_advisories("sarek")

    async def test_overwrites_existing(self, ddb_table) -> None:
        from nf_core_bot.db.advisories import get_known_advisories, save_advisory_state

        await save_advisory_state("rnaseq", "GHSA-aaaa", "triage", "2026-08-01T00:00:00Z")
        await save_advisory_state("rnaseq", "GHSA-aaaa", "published", "2026-08-02T00:00:00Z")
        known = await get_known_advisories("rnaseq")
        assert known["GHSA-aaaa"]["state"] == "published"


# ── security.advisories: check_security_advisories ────────────────────


class TestCheckSecurityAdvisories:
    @patch("nf_core_bot.security.advisories.resolve_channel_id", new_callable=AsyncMock, return_value="C_SECURITY")
    @patch("nf_core_bot.security.advisories.list_all_org_advisories")
    async def test_posts_new_advisory(self, mock_advisories, _mock_ch, ddb_table, client) -> None:
        from nf_core_bot.security.advisories import check_security_advisories

        mock_advisories.return_value = [
            SecurityAdvisory("rnaseq", "GHSA-pq68", "leak", "triage", "high", "2026-08-01", "https://x")
        ]

        await check_security_advisories(client)

        posts = [c for c in client.chat_postMessage.call_args_list if c.kwargs.get("channel") == "C_SECURITY"]
        assert len(posts) == 1
        assert "GHSA-pq68" in posts[0].kwargs["text"]
        assert "rnaseq" in posts[0].kwargs["text"]

    @patch("nf_core_bot.security.advisories.resolve_channel_id", new_callable=AsyncMock, return_value="C_SECURITY")
    @patch("nf_core_bot.security.advisories.list_all_org_advisories")
    async def test_escapes_mrkdwn_in_summary(self, mock_advisories, _mock_ch, ddb_table, client) -> None:
        """An advisory summary is attacker-controlled (anyone can file a report); a stray
        `>`/`<` must not be able to close the link early and inject a second one."""
        from nf_core_bot.security.advisories import check_security_advisories

        mock_advisories.return_value = [
            SecurityAdvisory(
                "rnaseq",
                "GHSA-pq68",
                "leak> <https://evil.example.com|click here>",
                "triage",
                "high",
                "2026-08-01",
                "https://x",
            )
        ]

        await check_security_advisories(client)

        text = client.chat_postMessage.call_args.kwargs["text"]
        assert "leak&gt; &lt;https://evil.example.com|click here&gt;" in text
        assert "<https://evil.example.com|click here>" not in text

    @patch("nf_core_bot.security.advisories.resolve_channel_id", new_callable=AsyncMock, return_value="C_SECURITY")
    @patch("nf_core_bot.security.advisories.list_all_org_advisories")
    async def test_does_not_repost_unchanged_advisory(self, mock_advisories, _mock_ch, ddb_table, client) -> None:
        from nf_core_bot.db.advisories import save_advisory_state
        from nf_core_bot.security.advisories import check_security_advisories

        await save_advisory_state("rnaseq", "GHSA-pq68", "triage", "2026-08-01")
        mock_advisories.return_value = [
            SecurityAdvisory("rnaseq", "GHSA-pq68", "leak", "triage", "high", "2026-08-01", "https://x")
        ]

        await check_security_advisories(client)

        client.chat_postMessage.assert_not_awaited()

    @patch("nf_core_bot.security.advisories.resolve_channel_id", new_callable=AsyncMock, return_value="C_SECURITY")
    @patch("nf_core_bot.security.advisories.list_all_org_advisories")
    async def test_reposts_when_state_changes(self, mock_advisories, _mock_ch, ddb_table, client) -> None:
        from nf_core_bot.db.advisories import save_advisory_state
        from nf_core_bot.security.advisories import check_security_advisories

        await save_advisory_state("rnaseq", "GHSA-pq68", "triage", "2026-08-01")
        mock_advisories.return_value = [
            SecurityAdvisory("rnaseq", "GHSA-pq68", "leak", "published", "high", "2026-08-05", "https://x")
        ]

        await check_security_advisories(client)

        posts = [c for c in client.chat_postMessage.call_args_list if c.kwargs.get("channel") == "C_SECURITY"]
        assert len(posts) == 1
        assert "published" in posts[0].kwargs["text"]

    @patch("nf_core_bot.security.advisories.resolve_channel_id", new_callable=AsyncMock, return_value="C_SECURITY")
    @patch("nf_core_bot.security.advisories.list_all_org_advisories")
    async def test_notifies_slack_when_fetch_fails(self, mock_advisories, _mock_ch, ddb_table, client) -> None:
        from nf_core_bot.security.advisories import check_security_advisories

        mock_advisories.side_effect = RuntimeError("403 Forbidden — not a security manager")

        await check_security_advisories(client)

        client.chat_postMessage.assert_awaited_once()
        text = client.chat_postMessage.call_args.kwargs["text"]
        assert "Could not fetch security advisories" in text

    @patch("nf_core_bot.security.advisories.resolve_channel_id", new_callable=AsyncMock, return_value=None)
    @patch("nf_core_bot.security.advisories.list_all_org_advisories")
    async def test_no_op_when_channel_not_resolved(self, mock_advisories, _mock_ch, ddb_table, client) -> None:
        from nf_core_bot.security.advisories import check_security_advisories

        mock_advisories.side_effect = RuntimeError("boom")

        # Should not raise even though it can't notify anyone.
        await check_security_advisories(client)
        client.chat_postMessage.assert_not_awaited()

    @patch("nf_core_bot.security.advisories.resolve_channel_id", new_callable=AsyncMock, return_value="C_SECURITY")
    @patch("nf_core_bot.security.advisories.list_all_org_advisories", new_callable=AsyncMock, return_value=[])
    async def test_no_post_when_nothing_flagged(self, _mock_advisories, _mock_ch, ddb_table, client) -> None:
        from nf_core_bot.security.advisories import check_security_advisories

        await check_security_advisories(client)

        client.chat_postMessage.assert_not_awaited()


# ── security.advisories: format_advisories_summary ─────────────────────


class TestFormatAdvisoriesSummary:
    def test_no_open_advisories(self) -> None:
        from nf_core_bot.security.advisories import format_advisories_summary

        assert "No open security advisories" in format_advisories_summary([])

    def test_excludes_closed_and_withdrawn(self) -> None:
        from nf_core_bot.security.advisories import format_advisories_summary

        advisories = [
            SecurityAdvisory("rnaseq", "GHSA-a", "fixed one", "closed", "high", "2026-08-01", "https://x"),
            SecurityAdvisory("rnaseq", "GHSA-b", "withdrawn one", "withdrawn", "high", "2026-08-01", "https://x"),
        ]
        summary = format_advisories_summary(advisories)
        assert "No open security advisories" in summary

    def test_groups_by_repo_and_includes_open_states(self) -> None:
        from nf_core_bot.security.advisories import format_advisories_summary

        advisories = [
            SecurityAdvisory("rnaseq", "GHSA-a", "triage issue", "triage", "high", "2026-08-01", "https://x/a"),
            SecurityAdvisory("sarek", "GHSA-b", "published issue", "published", None, "2026-08-02", "https://x/b"),
            SecurityAdvisory("rnaseq", "GHSA-c", "old closed", "closed", "low", "2026-08-01", "https://x/c"),
        ]
        summary = format_advisories_summary(advisories)

        assert "2 open security advisories" in summary
        assert summary.index("*rnaseq*") < summary.index("*sarek*")
        assert "<https://x/a|triage issue>" in summary
        assert "`triage`" in summary and "high" in summary
        assert "<https://x/b|published issue>" in summary
        assert "GHSA-c" not in summary

    def test_singular_count(self) -> None:
        from nf_core_bot.security.advisories import format_advisories_summary

        advisories = [SecurityAdvisory("rnaseq", "GHSA-a", "leak", "triage", "high", "2026-08-01", "https://x")]
        assert "1 open security advisory " in format_advisories_summary(advisories)

    def test_escapes_mrkdwn_in_summary_and_repo(self) -> None:
        from nf_core_bot.security.advisories import format_advisories_summary

        advisories = [
            SecurityAdvisory(
                "rnaseq",
                "GHSA-a",
                "leak> <https://evil.example.com|click>",
                "triage",
                "high",
                "2026-08-01",
                "https://x",
            )
        ]
        summary = format_advisories_summary(advisories)
        assert "<https://evil.example.com|click>" not in summary
        assert "leak&gt; &lt;https://evil.example.com|click&gt;" in summary
