"""Tests for proposal-review orchestration (context, template, skill loading)."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from nf_core_bot.checks.github import IssueComment, IssueWithComments
from nf_core_bot.proposals import review


def _issue(labels: tuple[str, ...] = ("new-pipeline",)) -> IssueWithComments:
    return IssueWithComments(
        number=148,
        title="New pipeline: foo",
        url="https://github.com/nf-core/proposals/issues/148",
        author="alice",
        state="open",
        labels=list(labels),
        body="The body text",
        comments=[IssueComment(author="bob", created_at="2026-01-01", body="A useful comment")],
    )


class TestContext:
    def test_includes_body_and_comments(self) -> None:
        ctx = review.build_proposal_context(_issue())
        assert "The body text" in ctx
        assert "A useful comment" in ctx
        assert "@bob" in ctx
        assert "#148" in ctx


class TestRender:
    def test_with_mention(self) -> None:
        msg = review.render_message(_issue(), "THE REVIEW", "<!subteam^S1>")
        assert "<!subteam^S1>" in msg
        assert "THE REVIEW" in msg
        assert "#148" in msg

    def test_without_mention_no_stray_blank(self) -> None:
        msg = review.render_message(_issue(), "THE REVIEW", "")
        assert "THE REVIEW" in msg
        assert "\n\n\n" not in msg


class TestSkillPrompt:
    def test_skill_dir_substituted(self) -> None:
        review._skill_prompt.cache_clear()
        prompt = review._skill_prompt()
        assert "<skill-dir>" not in prompt
        assert "scripts/fetch_proposal.sh" in prompt


class TestBuildReviewMessage:
    async def test_happy_path(self) -> None:
        issue = _issue()
        with (
            patch.object(review, "get_issue_with_comments", new=AsyncMock(return_value=issue)),
            patch.object(review, "run_review_agent", new=AsyncMock(return_value="REVIEW BODY")),
        ):
            got_issue, text = await review.build_review_message(148, "<!subteam^S1>")
        assert got_issue is issue
        assert text is not None and "REVIEW BODY" in text

    async def test_missing_issue(self) -> None:
        with patch.object(review, "get_issue_with_comments", new=AsyncMock(return_value=None)):
            got_issue, text = await review.build_review_message(999, "")
        assert got_issue is None
        assert text is None
