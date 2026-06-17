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


class TestRenderBlocks:
    def test_structure_with_mention(self) -> None:
        blocks, fallback = review.render_blocks(_issue(), "THE REVIEW", "<!subteam^S1>")
        # Header section carries the mention + linked title.
        assert blocks[0]["type"] == "section"
        assert "<!subteam^S1>" in blocks[0]["text"]["text"]
        assert "#148" in blocks[0]["text"]["text"]
        # Body goes in a markdown block (proper bullet/nesting rendering).
        md = [b for b in blocks if b["type"] == "markdown"]
        assert md and "THE REVIEW" in md[0]["text"]
        assert "#148" in fallback

    def test_no_mention(self) -> None:
        blocks, _ = review.render_blocks(_issue(), "THE REVIEW", "")
        assert "subteam" not in blocks[0]["text"]["text"]


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
            got_issue, blocks, fallback = await review.build_review_message(148, "<!subteam^S1>")
        assert got_issue is issue
        assert blocks is not None
        assert any(b["type"] == "markdown" and "REVIEW BODY" in b["text"] for b in blocks)
        assert fallback is not None and "#148" in fallback

    async def test_missing_issue(self) -> None:
        with patch.object(review, "get_issue_with_comments", new=AsyncMock(return_value=None)):
            got_issue, blocks, fallback = await review.build_review_message(999, "")
        assert got_issue is None
        assert blocks is None
        assert fallback is None
