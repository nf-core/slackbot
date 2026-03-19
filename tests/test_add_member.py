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


def _make_client() -> AsyncMock:
    """Build an ``AsyncWebClient`` mock whose ``conversations_open`` returns a DM channel."""
    client = AsyncMock()
    client.conversations_open.return_value = {"channel": {"id": "D_DM"}}
    return client


def _channel_messages(client: AsyncMock, channel: str = "C_CHAN") -> list[str]:
    """Return all ``chat_postMessage`` texts sent to *channel* (excludes DMs)."""
    texts: list[str] = []
    for call in client.chat_postMessage.call_args_list:
        ch = call.kwargs.get("channel", call.args[0] if call.args else "")
        if ch == channel:
            texts.append(call.kwargs.get("text", ""))
    return texts


def _dm_messages(client: AsyncMock) -> list[str]:
    """Return all ``chat_postMessage`` texts sent to the DM channel."""
    return _channel_messages(client, "D_DM")


# ── Permission check ─────────────────────────────────────────────────


class TestPermissionGate:
    @patch("nf_core_bot.commands.github.add_member.is_core_team", return_value=False)
    async def test_non_core_team_denied(self, _mock_perm: AsyncMock) -> None:
        ack = AsyncMock()
        respond = AsyncMock()
        client = _make_client()

        await handle_add_member(ack, respond, client, "U_USER", _command(), ["octocat"])

        ack.assert_awaited_once()
        respond.assert_awaited_once()
        assert "restricted" in respond.call_args[0][0].lower()


# ── Bare GitHub username argument ────────────────────────────────────


class TestBareUsername:
    @patch("nf_core_bot.commands.github.add_member.is_core_team", return_value=True)
    @patch("nf_core_bot.commands.github.invite_flow.invite_to_org")
    @patch("nf_core_bot.commands.github.invite_flow.add_to_team")
    async def test_valid_username_invites(self, mock_team: AsyncMock, mock_org: AsyncMock, _perm: AsyncMock) -> None:
        mock_org.return_value = GitHubResult(ok=True, message="pending")
        mock_team.return_value = GitHubResult(ok=True, message="active")

        ack = AsyncMock()
        respond = AsyncMock()
        client = _make_client()

        await handle_add_member(ack, respond, client, "U_ADMIN", _command(), ["octocat"])

        mock_org.assert_awaited_once_with("octocat")
        mock_team.assert_awaited_once_with("octocat")

        # Channel reply should contain the welcome greeting
        chan_texts = _channel_messages(client)
        assert any("welcome" in t.lower() for t in chan_texts)
        assert any("nf-core/invitation" in t for t in chan_texts)
        assert any("<@U_ADMIN>" in t for t in chan_texts)

        # Caller should also get a DM confirmation
        dm_texts = _dm_messages(client)
        assert any("octocat" in t for t in dm_texts)

    @patch("nf_core_bot.commands.github.add_member.is_core_team", return_value=True)
    async def test_invalid_username_rejected(self, _perm: AsyncMock) -> None:
        ack = AsyncMock()
        respond = AsyncMock()
        client = _make_client()

        await handle_add_member(ack, respond, client, "U_ADMIN", _command(), ["I don't know"])

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
        client = _make_client()

        with (
            patch("nf_core_bot.commands.github.invite_flow.invite_to_org") as mock_org,
            patch("nf_core_bot.commands.github.invite_flow.add_to_team") as mock_team,
        ):
            mock_org.return_value = GitHubResult(ok=True, message="ok")
            mock_team.return_value = GitHubResult(ok=True, message="ok")

            await handle_add_member(ack, respond, client, "U_ADMIN", _command(), ["https://github.com/octocat"])

            mock_org.assert_awaited_once_with("octocat")


# ── Slack mention argument ───────────────────────────────────────────


class TestSlackMention:
    @patch("nf_core_bot.commands.github.add_member.is_core_team", return_value=True)
    @patch("nf_core_bot.commands.github.add_member.get_github_username", return_value="octocat")
    @patch("nf_core_bot.commands.github.invite_flow.invite_to_org")
    @patch("nf_core_bot.commands.github.invite_flow.add_to_team")
    async def test_mention_resolves_github_username(
        self, mock_team: AsyncMock, mock_org: AsyncMock, mock_ghuser: AsyncMock, _perm: AsyncMock
    ) -> None:
        mock_org.return_value = GitHubResult(ok=True, message="ok")
        mock_team.return_value = GitHubResult(ok=True, message="ok")

        ack = AsyncMock()
        respond = AsyncMock()
        client = _make_client()

        await handle_add_member(ack, respond, client, "U_ADMIN", _command(), ["<@U01234TARGET>"])

        mock_ghuser.assert_awaited_once_with(client, "U01234TARGET")
        mock_org.assert_awaited_once_with("octocat")

        # Channel reply should greet the target user
        chan_texts = _channel_messages(client)
        assert any("<@U01234TARGET>" in t for t in chan_texts)
        assert any("<@U_ADMIN>" in t for t in chan_texts)

        # DM confirmation should be sent
        dm_texts = _dm_messages(client)
        assert any("octocat" in t for t in dm_texts)

    @patch("nf_core_bot.commands.github.add_member.is_core_team", return_value=True)
    @patch("nf_core_bot.commands.github.add_member.get_github_username", return_value=None)
    async def test_mention_missing_github_warns(self, _mock_ghuser: AsyncMock, _perm: AsyncMock) -> None:
        ack = AsyncMock()
        respond = AsyncMock()
        client = _make_client()

        await handle_add_member(ack, respond, client, "U_ADMIN", _command(thread_ts="123"), ["<@U01234TARGET>"])

        # Should post a warning about missing GitHub username
        client.chat_postMessage.assert_awaited()
        chan_texts = _channel_messages(client)
        assert any("GitHub username" in t for t in chan_texts)


# ── No-argument usage ────────────────────────────────────────────────


class TestNoArgs:
    @patch("nf_core_bot.commands.github.add_member.is_core_team", return_value=True)
    async def test_no_args_shows_usage(self, _perm: AsyncMock) -> None:
        ack = AsyncMock()
        respond = AsyncMock()
        client = _make_client()

        await handle_add_member(ack, respond, client, "U_ADMIN", _command(), [])

        respond_calls = respond.call_args_list
        assert any("Usage:" in str(c) for c in respond_calls)


# ── GitHub API error handling ────────────────────────────────────────


class TestGitHubApiErrors:
    @patch("nf_core_bot.commands.github.add_member.is_core_team", return_value=True)
    @patch("nf_core_bot.commands.github.invite_flow.invite_to_org")
    async def test_org_invite_network_error(self, mock_org: AsyncMock, _perm: AsyncMock) -> None:
        mock_org.side_effect = RuntimeError("connection refused")

        ack = AsyncMock()
        respond = AsyncMock()
        client = _make_client()

        await handle_add_member(ack, respond, client, "U_ADMIN", _command(), ["octocat"])

        chan_texts = _channel_messages(client)
        assert any("Failed to reach the GitHub API" in t for t in chan_texts)

    @patch("nf_core_bot.commands.github.add_member.is_core_team", return_value=True)
    @patch("nf_core_bot.commands.github.invite_flow.invite_to_org")
    async def test_org_invite_api_failure(self, mock_org: AsyncMock, _perm: AsyncMock) -> None:
        mock_org.return_value = GitHubResult(ok=False, message="422 — Validation failed")

        ack = AsyncMock()
        respond = AsyncMock()
        client = _make_client()

        await handle_add_member(ack, respond, client, "U_ADMIN", _command(), ["octocat"])

        chan_texts = _channel_messages(client)
        assert any("Failed to invite" in t for t in chan_texts)

    @patch("nf_core_bot.commands.github.add_member.is_core_team", return_value=True)
    @patch("nf_core_bot.commands.github.invite_flow.invite_to_org")
    @patch("nf_core_bot.commands.github.invite_flow.add_to_team")
    async def test_team_add_network_error(self, mock_team: AsyncMock, mock_org: AsyncMock, _perm: AsyncMock) -> None:
        mock_org.return_value = GitHubResult(ok=True, message="ok")
        mock_team.side_effect = RuntimeError("timeout")

        ack = AsyncMock()
        respond = AsyncMock()
        client = _make_client()

        await handle_add_member(ack, respond, client, "U_ADMIN", _command(), ["octocat"])

        chan_texts = _channel_messages(client)
        assert any("failed to reach the GitHub API" in t for t in chan_texts)

    @patch("nf_core_bot.commands.github.add_member.is_core_team", return_value=True)
    @patch("nf_core_bot.commands.github.invite_flow.invite_to_org")
    @patch("nf_core_bot.commands.github.invite_flow.add_to_team")
    async def test_team_add_api_failure(self, mock_team: AsyncMock, mock_org: AsyncMock, _perm: AsyncMock) -> None:
        mock_org.return_value = GitHubResult(ok=True, message="ok")
        mock_team.return_value = GitHubResult(ok=False, message="403 — Forbidden")

        ack = AsyncMock()
        respond = AsyncMock()
        client = _make_client()

        await handle_add_member(ack, respond, client, "U_ADMIN", _command(), ["octocat"])

        chan_texts = _channel_messages(client)
        assert any("failed to add to the" in t for t in chan_texts)


# ── DM failsafe ──────────────────────────────────────────────────────


class TestDmFailsafe:
    @patch("nf_core_bot.commands.github.add_member.is_core_team", return_value=True)
    @patch("nf_core_bot.commands.github.invite_flow.invite_to_org")
    @patch("nf_core_bot.commands.github.invite_flow.add_to_team")
    async def test_dm_sent_on_success(self, mock_team: AsyncMock, mock_org: AsyncMock, _perm: AsyncMock) -> None:
        """Caller always receives a DM confirmation on success."""
        mock_org.return_value = GitHubResult(ok=True, message="ok")
        mock_team.return_value = GitHubResult(ok=True, message="ok")

        ack = AsyncMock()
        respond = AsyncMock()
        client = _make_client()

        await handle_add_member(ack, respond, client, "U_ADMIN", _command(), ["octocat"])

        client.conversations_open.assert_awaited()
        dm_texts = _dm_messages(client)
        assert any("octocat" in t and "invited" in t for t in dm_texts)

    @patch("nf_core_bot.commands.github.add_member.is_core_team", return_value=True)
    @patch("nf_core_bot.commands.github.invite_flow.invite_to_org")
    @patch("nf_core_bot.commands.github.invite_flow.add_to_team")
    async def test_dm_fallback_when_channel_reply_fails(
        self, mock_team: AsyncMock, mock_org: AsyncMock, _perm: AsyncMock
    ) -> None:
        """When channel reply fails, caller gets the message via DM instead."""
        mock_org.return_value = GitHubResult(ok=True, message="ok")
        mock_team.return_value = GitHubResult(ok=True, message="ok")

        ack = AsyncMock()
        respond = AsyncMock()
        client = _make_client()

        # First chat_postMessage (channel reply) fails, subsequent ones (DMs) succeed
        call_count = 0

        async def _side_effect(**kwargs: str) -> dict:  # type: ignore[type-arg]
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("channel_not_found")
            return {"ok": True}

        client.chat_postMessage.side_effect = _side_effect

        await handle_add_member(ack, respond, client, "U_ADMIN", _command(), ["octocat"])

        # DM should still be sent
        client.conversations_open.assert_awaited()
        assert call_count >= 2  # channel reply failed + DM sent
