"""Tests for nf_core_bot.commands.github.add_member."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from nf_core_bot.checks.github import GitHubResult
from nf_core_bot.commands.github.add_member import handle_add_member


def _command(channel: str = "C_CHAN", thread_ts: str = "") -> dict[str, str]:
    """Build a minimal Slack slash-command payload."""
    cmd: dict[str, str] = {"channel_id": channel}
    if thread_ts:
        cmd["thread_ts"] = thread_ts
    return cmd


# ── Permission check ─────────────────────────────────────────────────


class TestPermissionGate:
    @patch("nf_core_bot.commands.github.add_member.is_core_team", return_value=False)
    async def test_non_core_team_denied(self, _mock_perm: AsyncMock) -> None:
        ack = AsyncMock()
        respond = AsyncMock()
        client = AsyncMock()

        await handle_add_member(ack, respond, client, "U_USER", _command(), ["octocat"])

        ack.assert_awaited_once()
        respond.assert_awaited_once()
        assert "restricted" in respond.call_args[0][0].lower()


# ── Bare GitHub username argument ────────────────────────────────────


class TestBareUsername:
    @patch("nf_core_bot.commands.github.add_member.is_core_team", return_value=True)
    @patch("nf_core_bot.commands.github.add_member.invite_to_org")
    @patch("nf_core_bot.commands.github.add_member.add_to_team")
    async def test_valid_username_invites(self, mock_team: AsyncMock, mock_org: AsyncMock, _perm: AsyncMock) -> None:
        mock_org.return_value = GitHubResult(ok=True, message="pending")
        mock_team.return_value = GitHubResult(ok=True, message="active")

        ack = AsyncMock()
        respond = AsyncMock()
        client = AsyncMock()

        await handle_add_member(ack, respond, client, "U_ADMIN", _command(), ["octocat"])

        mock_org.assert_awaited_once_with("octocat")
        mock_team.assert_awaited_once_with("octocat")
        # Final thread reply should mention success
        client.chat_postMessage.assert_awaited()
        final_text = client.chat_postMessage.call_args.kwargs.get(
            "text", client.chat_postMessage.call_args[1].get("text", "")
        )
        assert "invite" in final_text.lower()
        assert "nf-core/invitation" in final_text

    @patch("nf_core_bot.commands.github.add_member.is_core_team", return_value=True)
    async def test_invalid_username_rejected(self, _perm: AsyncMock) -> None:
        ack = AsyncMock()
        respond = AsyncMock()
        client = AsyncMock()

        await handle_add_member(ack, respond, client, "U_ADMIN", _command(), ["not--valid!!"])

        # Should get ephemeral error about invalid username
        respond_calls = respond.call_args_list
        assert any("doesn't look like a valid GitHub username" in str(c) for c in respond_calls)
        # Should NOT have called invite_to_org
        client.chat_postMessage.assert_not_awaited()

    @patch("nf_core_bot.commands.github.add_member.is_core_team", return_value=True)
    async def test_url_as_username_normalised(self, _perm: AsyncMock) -> None:
        """Passing a full GitHub URL should extract and validate the username."""
        ack = AsyncMock()
        respond = AsyncMock()
        client = AsyncMock()

        with (
            patch("nf_core_bot.commands.github.add_member.invite_to_org") as mock_org,
            patch("nf_core_bot.commands.github.add_member.add_to_team") as mock_team,
        ):
            mock_org.return_value = GitHubResult(ok=True, message="ok")
            mock_team.return_value = GitHubResult(ok=True, message="ok")

            await handle_add_member(ack, respond, client, "U_ADMIN", _command(), ["https://github.com/octocat"])

            mock_org.assert_awaited_once_with("octocat")


# ── Slack mention argument ───────────────────────────────────────────


class TestSlackMention:
    @patch("nf_core_bot.commands.github.add_member.is_core_team", return_value=True)
    @patch("nf_core_bot.commands.github.add_member.get_github_username", return_value="octocat")
    @patch("nf_core_bot.commands.github.add_member.invite_to_org")
    @patch("nf_core_bot.commands.github.add_member.add_to_team")
    async def test_mention_resolves_github_username(
        self, mock_team: AsyncMock, mock_org: AsyncMock, mock_ghuser: AsyncMock, _perm: AsyncMock
    ) -> None:
        mock_org.return_value = GitHubResult(ok=True, message="ok")
        mock_team.return_value = GitHubResult(ok=True, message="ok")

        ack = AsyncMock()
        respond = AsyncMock()
        client = AsyncMock()

        await handle_add_member(ack, respond, client, "U_ADMIN", _command(), ["<@U01234TARGET>"])

        mock_ghuser.assert_awaited_once_with(client, "U01234TARGET")
        mock_org.assert_awaited_once_with("octocat")

    @patch("nf_core_bot.commands.github.add_member.is_core_team", return_value=True)
    @patch("nf_core_bot.commands.github.add_member.get_github_username", return_value=None)
    async def test_mention_missing_github_warns(self, _mock_ghuser: AsyncMock, _perm: AsyncMock) -> None:
        ack = AsyncMock()
        respond = AsyncMock()
        client = AsyncMock()

        await handle_add_member(ack, respond, client, "U_ADMIN", _command(thread_ts="123"), ["<@U01234TARGET>"])

        # Should post a warning about missing GitHub username
        client.chat_postMessage.assert_awaited()
        text = client.chat_postMessage.call_args.kwargs.get(
            "text", client.chat_postMessage.call_args[1].get("text", "")
        )
        assert "GitHub username" in text


# ── No-argument usage ────────────────────────────────────────────────


class TestNoArgs:
    @patch("nf_core_bot.commands.github.add_member.is_core_team", return_value=True)
    async def test_no_args_shows_usage(self, _perm: AsyncMock) -> None:
        ack = AsyncMock()
        respond = AsyncMock()
        client = AsyncMock()

        await handle_add_member(ack, respond, client, "U_ADMIN", _command(), [])

        respond_calls = respond.call_args_list
        assert any("Usage:" in str(c) for c in respond_calls)


# ── GitHub API error handling ────────────────────────────────────────


class TestGitHubApiErrors:
    @patch("nf_core_bot.commands.github.add_member.is_core_team", return_value=True)
    @patch("nf_core_bot.commands.github.add_member.invite_to_org")
    async def test_org_invite_network_error(self, mock_org: AsyncMock, _perm: AsyncMock) -> None:
        mock_org.side_effect = RuntimeError("connection refused")

        ack = AsyncMock()
        respond = AsyncMock()
        client = AsyncMock()

        await handle_add_member(ack, respond, client, "U_ADMIN", _command(), ["octocat"])

        client.chat_postMessage.assert_awaited()
        text = client.chat_postMessage.call_args.kwargs.get(
            "text", client.chat_postMessage.call_args[1].get("text", "")
        )
        assert "Failed to reach the GitHub API" in text

    @patch("nf_core_bot.commands.github.add_member.is_core_team", return_value=True)
    @patch("nf_core_bot.commands.github.add_member.invite_to_org")
    async def test_org_invite_api_failure(self, mock_org: AsyncMock, _perm: AsyncMock) -> None:
        mock_org.return_value = GitHubResult(ok=False, message="422 — Validation failed")

        ack = AsyncMock()
        respond = AsyncMock()
        client = AsyncMock()

        await handle_add_member(ack, respond, client, "U_ADMIN", _command(), ["octocat"])

        client.chat_postMessage.assert_awaited()
        text = client.chat_postMessage.call_args.kwargs.get(
            "text", client.chat_postMessage.call_args[1].get("text", "")
        )
        assert "Failed to invite" in text

    @patch("nf_core_bot.commands.github.add_member.is_core_team", return_value=True)
    @patch("nf_core_bot.commands.github.add_member.invite_to_org")
    @patch("nf_core_bot.commands.github.add_member.add_to_team")
    async def test_team_add_network_error(self, mock_team: AsyncMock, mock_org: AsyncMock, _perm: AsyncMock) -> None:
        mock_org.return_value = GitHubResult(ok=True, message="ok")
        mock_team.side_effect = RuntimeError("timeout")

        ack = AsyncMock()
        respond = AsyncMock()
        client = AsyncMock()

        await handle_add_member(ack, respond, client, "U_ADMIN", _command(), ["octocat"])

        client.chat_postMessage.assert_awaited()
        text = client.chat_postMessage.call_args.kwargs.get(
            "text", client.chat_postMessage.call_args[1].get("text", "")
        )
        assert "failed to reach the GitHub API" in text

    @patch("nf_core_bot.commands.github.add_member.is_core_team", return_value=True)
    @patch("nf_core_bot.commands.github.add_member.invite_to_org")
    @patch("nf_core_bot.commands.github.add_member.add_to_team")
    async def test_team_add_api_failure(self, mock_team: AsyncMock, mock_org: AsyncMock, _perm: AsyncMock) -> None:
        mock_org.return_value = GitHubResult(ok=True, message="ok")
        mock_team.return_value = GitHubResult(ok=False, message="403 — Forbidden")

        ack = AsyncMock()
        respond = AsyncMock()
        client = AsyncMock()

        await handle_add_member(ack, respond, client, "U_ADMIN", _command(), ["octocat"])

        client.chat_postMessage.assert_awaited()
        text = client.chat_postMessage.call_args.kwargs.get(
            "text", client.chat_postMessage.call_args[1].get("text", "")
        )
        assert "failed to add to the" in text
