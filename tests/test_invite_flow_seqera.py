"""Tests for the Seqera workspace step of nf_core_bot.commands.github.invite_flow."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, patch

import pytest

from nf_core_bot.checks.github import GitHubResult
from nf_core_bot.checks.seqera import SeqeraResult, SeqeraStatus
from nf_core_bot.commands.github.add_member_shortcut import (
    _extract_platform_email_from_text,
    handle_add_member_shortcut,
)
from nf_core_bot.commands.github.invite_flow import invite_and_greet
from tests.helpers import dm_messages, make_slack_client

if TYPE_CHECKING:
    from collections.abc import Iterator

_ADDED = SeqeraResult(SeqeraStatus.ADDED, "added to the workspace", "me@example.org")
_ALREADY = SeqeraResult(SeqeraStatus.ALREADY_PARTICIPANT, "already a participant", "me@example.org")
_NOT_CONFIGURED = SeqeraResult(SeqeraStatus.NOT_CONFIGURED, "not configured")
_NO_ACCOUNT = SeqeraResult(SeqeraStatus.NO_ACCOUNT, "no Seqera Platform account was found for `me@example.org`")


@pytest.fixture
def github_new_member() -> Iterator[None]:
    with (
        patch(
            "nf_core_bot.commands.github.invite_flow.check_org_membership",
            return_value=GitHubResult(ok=False, message="not a member"),
        ),
        patch("nf_core_bot.commands.github.invite_flow.invite_to_org", return_value=GitHubResult(ok=True, message="")),
        patch("nf_core_bot.commands.github.invite_flow.add_to_team", return_value=GitHubResult(ok=True, message="")),
        patch("nf_core_bot.commands.github.invite_flow.set_github_username"),
    ):
        yield


@pytest.fixture
def github_existing_member() -> Iterator[None]:
    with patch(
        "nf_core_bot.commands.github.invite_flow.check_org_membership",
        return_value=GitHubResult(ok=True, message="already a member"),
    ):
        yield


async def _run(seqera: SeqeraResult, greeting_user_id: str | None = "U_NEW") -> tuple[list[str], list[str], AsyncMock]:
    """Run the invite flow; return (channel replies, caller DMs, add_to_megatests mock)."""
    client = make_slack_client()
    replies: list[str] = []

    async def _reply(text: str) -> None:
        replies.append(text)

    with patch("nf_core_bot.commands.github.invite_flow.add_to_megatests", return_value=seqera) as mock_add:
        await invite_and_greet(
            "octocat",
            "U_ADMIN",
            _reply,
            greeting_user_id=greeting_user_id,
            client=client,
            seqera_email="me@example.org",
        )
    return replies, dm_messages(client), mock_add


class TestNewJoiner:
    async def test_welcome_mentions_megatests_access(self, github_new_member: None) -> None:
        replies, dms, mock_add = await _run(_ADDED)

        mock_add.assert_awaited_once()
        assert mock_add.await_args is not None
        assert mock_add.await_args.args[1:] == ("U_NEW", "octocat", "me@example.org")
        assert len(replies) == 1
        assert "nf-core/invitation" in replies[0]
        assert "read-only access to the nf-core megatests workspace" in replies[0]
        assert any("added to the Seqera megatests workspace as `me@example.org`" in d for d in dms)

    async def test_failure_explained_in_dm_not_welcome(self, github_new_member: None) -> None:
        replies, dms, _ = await _run(_NO_ACCOUNT)

        assert "megatests" not in replies[0]
        assert any("Couldn't add <@U_NEW>" in d and "no Seqera Platform account" in d for d in dms)

    async def test_not_configured_is_silent(self, github_new_member: None) -> None:
        replies, dms, _ = await _run(_NOT_CONFIGURED)

        assert "megatests" not in replies[0]
        assert dms
        assert not any("Seqera" in d for d in dms)

    async def test_no_slack_user_skips_seqera(self, github_new_member: None) -> None:
        replies, _, mock_add = await _run(_ADDED, greeting_user_id=None)

        mock_add.assert_not_awaited()
        assert "megatests" not in replies[0]


class TestExistingMember:
    async def test_added_says_so_publicly(self, github_existing_member: None) -> None:
        replies, dms, _ = await _run(_ADDED)

        assert len(replies) == 1
        assert "already a member of the nf-core GitHub org" in replies[0]
        assert "nothing to do" not in replies[0]
        assert "<@U_NEW> has been added to the nf-core megatests workspace" in replies[0]
        assert any("as `me@example.org`" in d for d in dms)

    async def test_already_participant(self, github_existing_member: None) -> None:
        replies, _, _ = await _run(_ALREADY)

        assert "already has access to the nf-core megatests workspace" in replies[0]
        assert "nothing to do" in replies[0]

    async def test_failure_does_not_claim_nothing_to_do(self, github_existing_member: None) -> None:
        replies, dms, _ = await _run(_NO_ACCOUNT)

        assert "nothing to do" not in replies[0]
        assert any("Couldn't add <@U_NEW>" in d for d in dms)

    async def test_not_configured_keeps_original_message(self, github_existing_member: None) -> None:
        replies, dms, _ = await _run(_NOT_CONFIGURED)

        assert replies == ["`octocat` is already a member of the nf-core GitHub org — nothing to do."]
        assert dms == []

    async def test_unexpected_exception_reported(self, github_existing_member: None) -> None:
        client = make_slack_client()
        replies: list[str] = []

        async def _reply(text: str) -> None:
            replies.append(text)

        with patch("nf_core_bot.commands.github.invite_flow.add_to_megatests", side_effect=ValueError("boom")):
            await invite_and_greet("octocat", "U_ADMIN", _reply, greeting_user_id="U_NEW", client=client)

        assert any("unexpected error (ValueError)" in d for d in dm_messages(client))


# ── Workflow form: optional Platform email ───────────────────────────


class TestExtractPlatformEmail:
    def test_mailto_link(self) -> None:
        text = (
            "By <@U1> at March 13th, 2026\n*Which is your GitHub handle?*\noctocat\n"
            "*Seqera Platform email (if different from your Slack email)*\n<mailto:me@x.org|me@x.org>"
        )
        assert _extract_platform_email_from_text(text) == "me@x.org"

    def test_plain_email(self) -> None:
        assert _extract_platform_email_from_text("*What email do you use for Platform?*\nme@x.org") == "me@x.org"

    def test_non_email_answer(self) -> None:
        assert _extract_platform_email_from_text("*Seqera Platform email*\nsame as Slack") is None

    def test_question_missing(self) -> None:
        assert _extract_platform_email_from_text("*Which is your GitHub handle?*\noctocat") is None


class TestShortcutPassesPlatformEmail:
    @patch("nf_core_bot.commands.github.add_member_shortcut.is_core_team", return_value=True)
    @patch("nf_core_bot.commands.github.add_member_shortcut.invite_and_greet")
    async def test_email_forwarded(self, mock_invite: AsyncMock, _perm: AsyncMock) -> None:
        text = (
            "By <@U0REQ> at March 13th, 2026\n*Which is your GitHub handle?*\noctocat\n"
            "*Seqera Platform email*\n<mailto:me@x.org|me@x.org>"
        )
        shortcut = {
            "user": {"id": "U_ADMIN"},
            "channel": {"id": "C_CHAN"},
            "message": {"bot_id": "B1", "ts": "1.2", "text": text},
        }

        await handle_add_member_shortcut(AsyncMock(), shortcut, make_slack_client())

        assert mock_invite.await_args is not None
        assert mock_invite.await_args.kwargs["greeting_user_id"] == "U0REQ"
        assert mock_invite.await_args.kwargs["seqera_email"] == "me@x.org"
