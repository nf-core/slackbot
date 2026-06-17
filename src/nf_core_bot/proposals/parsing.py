"""Extract an nf-core/proposals issue number from a Slack message."""

from __future__ import annotations

import json
import re
from typing import Any

# Matches the issue URL the GitHub→Slack integration posts, e.g.
# https://github.com/nf-core/proposals/issues/148
_ISSUE_RE = re.compile(r"github\.com/nf-core/proposals/issues/(\d+)", re.IGNORECASE)


def extract_proposal_number(text: str) -> int | None:
    """Return the first nf-core/proposals issue number in *text*, or None."""
    match = _ISSUE_RE.search(text or "")
    return int(match.group(1)) if match else None


def message_searchable_text(message: dict[str, Any]) -> str:
    """Flatten a Slack message (text + attachments + blocks) into one string.

    The GitHub integration puts the issue link in attachment fields or block
    elements rather than the top-level ``text``, so we serialise everything.
    """
    parts: list[str] = [str(message.get("text") or "")]
    for att in message.get("attachments") or []:
        for key in ("title", "title_link", "text", "fallback", "pretext", "from_url"):
            value = att.get(key)
            if value:
                parts.append(str(value))
    blocks = message.get("blocks")
    if blocks:
        parts.append(json.dumps(blocks))
    return "\n".join(parts)
