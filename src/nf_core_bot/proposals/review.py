"""Orchestrate a single proposal review: fetch → run skill → render Slack blocks."""

from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path
from typing import Any

from nf_core_bot.checks.github import IssueWithComments, get_issue_with_comments
from nf_core_bot.proposals.bedrock import run_review_agent
from nf_core_bot.proposals.slack_utils import build_review_blocks

logger = logging.getLogger(__name__)

_SKILL_DIR = Path(__file__).parent / "skills" / "nfcore-proposal-review"
_SKILL_PATH = _SKILL_DIR / "SKILL.md"
_TEMPLATE_PATH = Path(__file__).parent / "templates" / "review.md"


@lru_cache(maxsize=1)
def _skill_prompt() -> str:
    # The skill references its scripts as `<skill-dir>/scripts/…`; substitute the
    # real absolute path so the model emits commands the tool runner can execute.
    text = _SKILL_PATH.read_text(encoding="utf-8")
    return text.replace("<skill-dir>", str(_SKILL_DIR.resolve()))


@lru_cache(maxsize=1)
def _template() -> str:
    return _TEMPLATE_PATH.read_text(encoding="utf-8")


def build_proposal_context(issue: IssueWithComments) -> str:
    """Render the full issue + comments into the user message for the model."""
    lines = [
        f"# Proposal #{issue.number}: {issue.title}",
        f"URL: {issue.url}",
        f"Author: @{issue.author}",
        f"State: {issue.state}",
        f"Labels: {', '.join(issue.labels) or '(none)'}",
        "",
        "## Proposal body",
        "",
        issue.body.strip() or "(empty)",
        "",
    ]
    if issue.comments:
        lines.append(f"## Comments ({len(issue.comments)})")
        lines.append("")
        for c in issue.comments:
            lines.append(f"### @{c.author} ({c.created_at})")
            lines.append(c.body.strip() or "(empty)")
            lines.append("")
    else:
        lines.extend(["## Comments", "", "(none)", ""])

    lines.append(
        "Review this proposal now by following the skill. The issue body and all comments "
        "are above, so start from the tool/pipeline overlap research. Produce the review as "
        "concise standard Markdown exactly as described in the skill's runtime addendum."
    )
    return "\n".join(lines)


async def generate_review_body(issue: IssueWithComments) -> str:
    """Run the skill against *issue* and return Claude's review body (Markdown)."""
    context = build_proposal_context(issue)
    return await run_review_agent(_skill_prompt(), context)


def render_blocks(
    issue: IssueWithComments,
    review_body: str,
    core_team_mention: str = "",
) -> tuple[list[dict[str, Any]], str]:
    """Build the Slack Block Kit message + a plain-text fallback for *review_body*.

    The header (title link + ``core_team_mention``) and footer come from the
    tweakable ``templates/review.md``; the model's Markdown body goes in a
    ``markdown`` block so bullets/nesting/code render natively. *core_team_mention*
    is a ``<!subteam^ID>`` string for public posts, or empty to ping nobody.
    """
    head, _, foot = _template().partition("{review_body}")
    replacements = {
        "{core_team_mention}": core_team_mention,
        "{proposal_url}": issue.url,
        "{issue_number}": str(issue.number),
        "{proposal_title}": issue.title,
    }
    for token, value in replacements.items():
        head = head.replace(token, value)
        foot = foot.replace(token, value)
    blocks = build_review_blocks(head.strip(), review_body.strip(), foot.strip())
    fallback = f"New pipeline proposal review: #{issue.number}: {issue.title}"
    return blocks, fallback


async def build_review_message(
    number: int, core_team_mention: str = ""
) -> tuple[IssueWithComments | None, list[dict[str, Any]] | None, str | None]:
    """Fetch issue *number*, run the review, return ``(issue, blocks, fallback_text)``.

    Returns ``(None, None, None)`` if the issue can't be fetched.
    """
    issue = await get_issue_with_comments(number)
    if issue is None:
        return None, None, None
    body = await generate_review_body(issue)
    blocks, fallback = render_blocks(issue, body, core_team_mention)
    return issue, blocks, fallback
