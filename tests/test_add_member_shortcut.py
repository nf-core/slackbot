"""Tests for nf_core_bot.commands.github.add_member_shortcut."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from nf_core_bot.checks.github import GitHubResult
from nf_core_bot.commands.github.add_member_shortcut import (
    _extract_github_handle_from_text,
    _extract_requester_from_text,
    handle_add_member_shortcut,
)
from tests.helpers import channel_messages, dm_messages, make_slack_client


def _shortcut(
    caller: str = "U_ADMIN",
    target: str = "U_TARGET",
    channel: str = "C_CHAN",
    message_ts: str = "111.222",
    thread_ts: str = "",
) -> dict:  # type: ignore[type-arg]
    """Build a minimal Slack message shortcut payload."""
    msg: dict[str, str] = {"user": target, "ts": message_ts}
    if thread_ts:
        msg["thread_ts"] = thread_ts
    return {
        "user": {"id": caller},
        "channel": {"id": channel},
        "message_ts": message_ts,
        "message": msg,
    }


# ── Permission check ─────────────────────────────────────────────────


class TestPermissionGate:
    @patch("nf_core_bot.commands.github.add_member_shortcut.is_core_team", return_value=False)
    async def test_non_core_team_denied(self, _perm: AsyncMock) -> None:
        ack = AsyncMock()
        client = make_slack_client()

        await handle_add_member_shortcut(ack, _shortcut(), client)

        ack.assert_awaited_once()
        client.chat_postEphemeral.assert_awaited_once()
        text = client.chat_postEphemeral.call_args.kwargs["text"]
        assert "restricted" in text.lower()
        # Should NOT proceed to GitHub calls
        _chan = channel_messages(client)
        assert not _chan


# ── GitHub username resolution ───────────────────────────────────────


class TestGithubUsernameResolution:
    @patch("nf_core_bot.commands.github.add_member_shortcut.is_core_team", return_value=True)
    @patch("nf_core_bot.commands.github.add_member_shortcut.get_github_username", return_value=None)
    async def test_missing_github_warns(self, _ghuser: AsyncMock, _perm: AsyncMock) -> None:
        ack = AsyncMock()
        client = make_slack_client()

        await handle_add_member_shortcut(ack, _shortcut(), client)

        chan_texts = channel_messages(client)
        assert any("GitHub username" in t for t in chan_texts)
        assert any("<@U_TARGET>" in t for t in chan_texts)

    @patch("nf_core_bot.commands.github.add_member_shortcut.is_core_team", return_value=True)
    @patch("nf_core_bot.commands.github.add_member_shortcut.get_github_username", return_value="octocat")
    @patch("nf_core_bot.commands.github.invite_flow.invite_to_org")
    @patch("nf_core_bot.commands.github.invite_flow.add_to_team")
    async def test_success_invites_and_adds(
        self, mock_team: AsyncMock, mock_org: AsyncMock, _ghuser: AsyncMock, _perm: AsyncMock
    ) -> None:
        mock_org.return_value = GitHubResult(ok=True, message="pending")
        mock_team.return_value = GitHubResult(ok=True, message="active")

        ack = AsyncMock()
        client = make_slack_client()

        await handle_add_member_shortcut(ack, _shortcut(), client)

        mock_org.assert_awaited_once_with("octocat")
        mock_team.assert_awaited_once_with("octocat")

        # Channel reply should be a welcome with invite link
        chan_texts = channel_messages(client)
        assert any("welcome" in t.lower() for t in chan_texts)
        assert any("nf-core/invitation" in t for t in chan_texts)
        assert any("<@U_TARGET>" in t for t in chan_texts)  # greeting addresses the message author
        assert any("<@U_ADMIN>" in t for t in chan_texts)  # mentions who triggered it

        # Caller should also get a DM confirmation
        dm_texts = dm_messages(client)
        assert any("octocat" in t for t in dm_texts)


# ── Thread reply placement ───────────────────────────────────────────


class TestThreadReply:
    @patch("nf_core_bot.commands.github.add_member_shortcut.is_core_team", return_value=True)
    @patch("nf_core_bot.commands.github.add_member_shortcut.get_github_username", return_value="octocat")
    @patch("nf_core_bot.commands.github.invite_flow.invite_to_org")
    @patch("nf_core_bot.commands.github.invite_flow.add_to_team")
    async def test_replies_in_thread_when_in_thread(
        self, mock_team: AsyncMock, mock_org: AsyncMock, _ghuser: AsyncMock, _perm: AsyncMock
    ) -> None:
        mock_org.return_value = GitHubResult(ok=True, message="ok")
        mock_team.return_value = GitHubResult(ok=True, message="ok")

        ack = AsyncMock()
        client = make_slack_client()

        sc = _shortcut(message_ts="222.333", thread_ts="111.000")
        await handle_add_member_shortcut(ack, sc, client)

        # The greeting (channel reply) should be in the parent thread, not the message itself
        chan_calls = [c for c in client.chat_postMessage.call_args_list if c.kwargs.get("channel") == "C_CHAN"]
        greeting_call = [c for c in chan_calls if "welcome" in c.kwargs.get("text", "").lower()]
        assert greeting_call
        assert greeting_call[0].kwargs["thread_ts"] == "111.000"

    @patch("nf_core_bot.commands.github.add_member_shortcut.is_core_team", return_value=True)
    @patch("nf_core_bot.commands.github.add_member_shortcut.get_github_username", return_value="octocat")
    @patch("nf_core_bot.commands.github.invite_flow.invite_to_org")
    @patch("nf_core_bot.commands.github.invite_flow.add_to_team")
    async def test_replies_to_message_when_not_in_thread(
        self, mock_team: AsyncMock, mock_org: AsyncMock, _ghuser: AsyncMock, _perm: AsyncMock
    ) -> None:
        mock_org.return_value = GitHubResult(ok=True, message="ok")
        mock_team.return_value = GitHubResult(ok=True, message="ok")

        ack = AsyncMock()
        client = make_slack_client()

        sc = _shortcut(message_ts="222.333")
        await handle_add_member_shortcut(ack, sc, client)

        # The greeting should reply to the message itself (creating a thread)
        chan_calls = [c for c in client.chat_postMessage.call_args_list if c.kwargs.get("channel") == "C_CHAN"]
        greeting_call = [c for c in chan_calls if "welcome" in c.kwargs.get("text", "").lower()]
        assert greeting_call
        assert greeting_call[0].kwargs["thread_ts"] == "222.333"


# ── Workflow / bot message handling ───────────────────────────────────


def _workflow_shortcut(
    message_text: str,
    caller: str = "U_ADMIN",
    channel: str = "C_CHAN",
    message_ts: str = "111.222",
) -> dict:  # type: ignore[type-arg]
    """Build a shortcut payload for a workflow/bot message (no 'user' field)."""
    return {
        "user": {"id": caller},
        "channel": {"id": channel},
        "message": {"bot_id": "B123", "ts": message_ts, "text": message_text},
    }


class TestExtractGithubHandle:
    """Unit tests for _extract_github_handle_from_text."""

    def test_standard_workflow_format(self) -> None:
        text = "By <@U123> at March 13th, 2026\n*Which is your GitHub handle?*\nMuteebaAzhar"
        assert _extract_github_handle_from_text(text) == "MuteebaAzhar"

    def test_without_bold(self) -> None:
        text = "Which is your GitHub handle?\noctocat"
        assert _extract_github_handle_from_text(text) == "octocat"

    def test_with_question_mark(self) -> None:
        text = "Which is your GitHub handle?\noctocat"
        assert _extract_github_handle_from_text(text) == "octocat"

    def test_just_github_handle(self) -> None:
        text = "GitHub handle?\nocto-cat"
        assert _extract_github_handle_from_text(text) == "octo-cat"

    def test_with_extra_whitespace(self) -> None:
        text = "*Which is your GitHub handle?*\n  octocat  "
        assert _extract_github_handle_from_text(text) == "octocat"

    def test_invalid_handle_rejected(self) -> None:
        text = "Which is your GitHub handle?\nhttps://github.com/some_user"
        # URL with underscore — normalise_github_username rejects underscores
        assert _extract_github_handle_from_text(text) is None

    def test_url_handle_extracted(self) -> None:
        text = "Which is your GitHub handle?\nhttps://github.com/octocat"
        assert _extract_github_handle_from_text(text) == "octocat"

    def test_no_match_returns_none(self) -> None:
        text = "Just a normal message with no GitHub handle question"
        assert _extract_github_handle_from_text(text) is None

    def test_empty_answer_returns_none(self) -> None:
        text = "Which is your GitHub handle?\n"
        assert _extract_github_handle_from_text(text) is None


class TestExtractRequester:
    """Unit tests for _extract_requester_from_text."""

    def test_standard_workflow_format(self) -> None:
        text = "By <@U01234ABC> at March 13th, 2026\n*Which is your GitHub handle?*\noctocat"
        assert _extract_requester_from_text(text) == "U01234ABC"

    def test_with_display_name(self) -> None:
        text = "By <@U01234ABC|muteeba> at March 13th, 2026"
        assert _extract_requester_from_text(text) == "U01234ABC"

    def test_no_match(self) -> None:
        text = "Just a random message"
        assert _extract_requester_from_text(text) is None


class TestWorkflowMessage:
    @patch("nf_core_bot.commands.github.add_member_shortcut.is_core_team", return_value=True)
    @patch("nf_core_bot.commands.github.invite_flow.invite_to_org")
    @patch("nf_core_bot.commands.github.invite_flow.add_to_team")
    async def test_workflow_message_extracts_handle(
        self, mock_team: AsyncMock, mock_org: AsyncMock, _perm: AsyncMock
    ) -> None:
        mock_org.return_value = GitHubResult(ok=True, message="ok")
        mock_team.return_value = GitHubResult(ok=True, message="ok")

        ack = AsyncMock()
        client = make_slack_client()

        sc = _workflow_shortcut("By <@U0REQUESTER> at March 13th, 2026\n*Which is your GitHub handle?*\nMuteebaAzhar")
        await handle_add_member_shortcut(ack, sc, client)

        mock_org.assert_awaited_once_with("MuteebaAzhar")
        mock_team.assert_awaited_once_with("MuteebaAzhar")

        # Channel reply should mention the requester and the caller
        chan_texts = channel_messages(client)
        assert any("<@U0REQUESTER>" in t for t in chan_texts)  # greeting addresses workflow requester
        assert any("<@U_ADMIN>" in t for t in chan_texts)  # mentions who triggered it
        assert any("nf-core/invitation" in t for t in chan_texts)

        # DM confirmation should be sent
        dm_texts = dm_messages(client)
        assert any("MuteebaAzhar" in t for t in dm_texts)

    @patch("nf_core_bot.commands.github.add_member_shortcut.is_core_team", return_value=True)
    async def test_workflow_message_no_handle_shows_error(self, _perm: AsyncMock) -> None:
        ack = AsyncMock()
        client = make_slack_client()

        sc = _workflow_shortcut("Just a random bot message")
        await handle_add_member_shortcut(ack, sc, client)

        client.chat_postEphemeral.assert_awaited()
        text = client.chat_postEphemeral.call_args.kwargs["text"]
        assert "Couldn't find a GitHub username" in text


# ── GitHub API error handling ────────────────────────────────────────


class TestGitHubApiErrors:
    @patch("nf_core_bot.commands.github.add_member_shortcut.is_core_team", return_value=True)
    @patch("nf_core_bot.commands.github.add_member_shortcut.get_github_username", return_value="octocat")
    @patch("nf_core_bot.commands.github.invite_flow.invite_to_org")
    async def test_org_invite_network_error(self, mock_org: AsyncMock, _ghuser: AsyncMock, _perm: AsyncMock) -> None:
        mock_org.side_effect = RuntimeError("connection refused")

        ack = AsyncMock()
        client = make_slack_client()

        await handle_add_member_shortcut(ack, _shortcut(), client)

        chan_texts = channel_messages(client)
        # Channel reply may or may not work — check DM too
        dm_texts = dm_messages(client)
        all_texts = chan_texts + dm_texts
        assert any("Failed to reach the GitHub API" in t for t in all_texts)

    @patch("nf_core_bot.commands.github.add_member_shortcut.is_core_team", return_value=True)
    @patch("nf_core_bot.commands.github.add_member_shortcut.get_github_username", return_value="octocat")
    @patch("nf_core_bot.commands.github.invite_flow.invite_to_org")
    async def test_org_invite_api_failure(self, mock_org: AsyncMock, _ghuser: AsyncMock, _perm: AsyncMock) -> None:
        mock_org.return_value = GitHubResult(ok=False, message="422 — Validation failed")

        ack = AsyncMock()
        client = make_slack_client()

        await handle_add_member_shortcut(ack, _shortcut(), client)

        chan_texts = channel_messages(client)
        dm_texts = dm_messages(client)
        all_texts = chan_texts + dm_texts
        assert any("Failed to invite" in t for t in all_texts)

    @patch("nf_core_bot.commands.github.add_member_shortcut.is_core_team", return_value=True)
    @patch("nf_core_bot.commands.github.add_member_shortcut.get_github_username", return_value="octocat")
    @patch("nf_core_bot.commands.github.invite_flow.invite_to_org")
    @patch("nf_core_bot.commands.github.invite_flow.add_to_team")
    async def test_team_add_network_error(
        self, mock_team: AsyncMock, mock_org: AsyncMock, _ghuser: AsyncMock, _perm: AsyncMock
    ) -> None:
        mock_org.return_value = GitHubResult(ok=True, message="ok")
        mock_team.side_effect = RuntimeError("timeout")

        ack = AsyncMock()
        client = make_slack_client()

        await handle_add_member_shortcut(ack, _shortcut(), client)

        chan_texts = channel_messages(client)
        dm_texts = dm_messages(client)
        all_texts = chan_texts + dm_texts
        assert any("failed to reach the GitHub API" in t for t in all_texts)


# ── DM failsafe ──────────────────────────────────────────────────────


class TestDmFailsafe:
    @patch("nf_core_bot.commands.github.add_member_shortcut.is_core_team", return_value=True)
    @patch("nf_core_bot.commands.github.add_member_shortcut.get_github_username", return_value="octocat")
    @patch("nf_core_bot.commands.github.invite_flow.invite_to_org")
    @patch("nf_core_bot.commands.github.invite_flow.add_to_team")
    async def test_dm_sent_on_success(
        self, mock_team: AsyncMock, mock_org: AsyncMock, _ghuser: AsyncMock, _perm: AsyncMock
    ) -> None:
        """Caller always receives a DM confirmation on success."""
        mock_org.return_value = GitHubResult(ok=True, message="ok")
        mock_team.return_value = GitHubResult(ok=True, message="ok")

        ack = AsyncMock()
        client = make_slack_client()

        await handle_add_member_shortcut(ack, _shortcut(), client)

        client.conversations_open.assert_awaited()
        dm_texts = dm_messages(client)
        assert any("octocat" in t and "invited" in t for t in dm_texts)

    @patch("nf_core_bot.commands.github.add_member_shortcut.is_core_team", return_value=True)
    @patch("nf_core_bot.commands.github.add_member_shortcut.get_github_username", return_value="octocat")
    @patch("nf_core_bot.commands.github.invite_flow.invite_to_org")
    @patch("nf_core_bot.commands.github.invite_flow.add_to_team")
    async def test_channel_reply_failure_falls_back_to_dm(
        self, mock_team: AsyncMock, mock_org: AsyncMock, _ghuser: AsyncMock, _perm: AsyncMock
    ) -> None:
        """When channel reply fails, caller still gets the DM."""
        mock_org.return_value = GitHubResult(ok=True, message="ok")
        mock_team.return_value = GitHubResult(ok=True, message="ok")

        ack = AsyncMock()
        client = make_slack_client()

        # First chat_postMessage (channel reply) fails, subsequent ones (DMs) succeed
        call_count = 0

        async def _side_effect(**kwargs: str) -> dict:  # type: ignore[type-arg]
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("channel_not_found")
            return {"ok": True}

        client.chat_postMessage.side_effect = _side_effect

        await handle_add_member_shortcut(ack, _shortcut(), client)

        # DM should still be sent
        client.conversations_open.assert_awaited()
        assert call_count >= 2
