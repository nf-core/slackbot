"""Tests for the auto-trigger listener."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from nf_core_bot.checks.github import IssueWithComments
from nf_core_bot.db import proposals as db_proposals
from nf_core_bot.proposals import listener

ISSUE_URL = "https://github.com/nf-core/proposals/issues/148"


@pytest.fixture(autouse=True)
def _reset_self_ids() -> None:
    listener._self_ids.clear()
    listener._self_ids_resolved = False


def _client() -> AsyncMock:
    client = AsyncMock()
    client.auth_test.return_value = {"user_id": "UBOT", "bot_id": "BBOT"}
    return client


def _event(**kw: object) -> dict:
    e: dict = {"channel": "C_NEWPIPE", "ts": "123.45", "user": "UHUMAN", "text": f"New pipeline {ISSUE_URL}"}
    e.update(kw)
    return e


def _issue(labels: tuple[str, ...] = ("new-pipeline",)) -> IssueWithComments:
    return IssueWithComments(148, "New pipeline: foo", ISSUE_URL, "alice", "open", list(labels), "body", [])


def _patches(**overrides: object):
    defaults = dict(
        resolve_channel_id=AsyncMock(return_value="C_NEWPIPE"),
        get_issue_with_comments=AsyncMock(return_value=_issue()),
        generate_review_body=AsyncMock(return_value="REVIEW"),
        core_team_mention=AsyncMock(return_value="<!subteam^S1>"),
        post_review=AsyncMock(return_value="999.0"),
    )
    defaults.update(overrides)
    return patch.multiple("nf_core_bot.proposals.listener", **defaults)


# ── should_consider (cheap synchronous gate used before spawning) ────


class TestShouldConsider:
    def test_accepts_proposal_post(self) -> None:
        assert listener.should_consider(_event()) is True

    def test_rejects_no_url(self) -> None:
        assert listener.should_consider(_event(text="just chatting")) is False

    def test_rejects_thread_reply(self) -> None:
        assert listener.should_consider(_event(thread_ts="100.0")) is False

    def test_rejects_edit_subtype(self) -> None:
        assert listener.should_consider(_event(subtype="message_changed")) is False

    def test_rejects_when_disabled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("PROPOSALS_REVIEW_ENABLED", "false")
        assert listener.should_consider(_event()) is False


# ── Filtering (no DynamoDB needed — returns before claim) ────────────


class TestFilters:
    async def test_wrong_channel(self) -> None:
        post = AsyncMock()
        with _patches(resolve_channel_id=AsyncMock(return_value="C_OTHER"), post_review=post):
            await listener.handle_proposal_message(_event(), _client())
        post.assert_not_awaited()

    async def test_threaded_reply_skipped(self) -> None:
        post = AsyncMock()
        with _patches(post_review=post):
            await listener.handle_proposal_message(_event(thread_ts="100.0"), _client())
        post.assert_not_awaited()

    async def test_edit_subtype_skipped(self) -> None:
        post = AsyncMock()
        with _patches(post_review=post):
            await listener.handle_proposal_message(_event(subtype="message_changed"), _client())
        post.assert_not_awaited()

    async def test_no_issue_number_skipped(self) -> None:
        post = AsyncMock()
        with _patches(post_review=post):
            await listener.handle_proposal_message(_event(text="just chatting"), _client())
        post.assert_not_awaited()

    async def test_own_message_skipped(self) -> None:
        post = AsyncMock()
        client = _client()
        with _patches(post_review=post):
            await listener.handle_proposal_message(_event(user="UBOT"), client)
        post.assert_not_awaited()

    async def test_disabled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("PROPOSALS_REVIEW_ENABLED", "false")
        post = AsyncMock()
        with _patches(post_review=post):
            await listener.handle_proposal_message(_event(), _client())
        post.assert_not_awaited()


# ── Review flow (needs the mocked DynamoDB table) ────────────────────


class TestReviewFlow:
    async def test_happy_path_posts_and_records(self, ddb_table: object) -> None:
        post = AsyncMock(return_value="999.0")
        with _patches(post_review=post):
            await listener.handle_proposal_message(_event(), _client())
        post.assert_awaited_once()
        record = await db_proposals.get_review_record(148)
        assert record is not None
        assert record["status"] == "posted"

    async def test_dedup_skips_second(self, ddb_table: object) -> None:
        await db_proposals.claim_review(148)  # someone already claimed it
        post = AsyncMock()
        with _patches(post_review=post):
            await listener.handle_proposal_message(_event(), _client())
        post.assert_not_awaited()

    async def test_wrong_label_releases_claim(self, ddb_table: object) -> None:
        post = AsyncMock()
        with _patches(get_issue_with_comments=AsyncMock(return_value=_issue(labels=("bug",))), post_review=post):
            await listener.handle_proposal_message(_event(), _client())
        post.assert_not_awaited()
        # Claim released so a later correctly-labelled trigger can run.
        assert await db_proposals.get_review_record(148) is None
