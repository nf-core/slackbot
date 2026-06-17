"""Tests for proposal issue-number extraction from Slack messages."""

from __future__ import annotations

from nf_core_bot.proposals.parsing import extract_proposal_number, message_searchable_text


class TestExtract:
    def test_plain_url(self) -> None:
        assert extract_proposal_number("see https://github.com/nf-core/proposals/issues/148 please") == 148

    def test_no_match(self) -> None:
        assert extract_proposal_number("nothing here") is None
        assert extract_proposal_number("") is None

    def test_other_repo_ignored(self) -> None:
        assert extract_proposal_number("https://github.com/nf-core/sarek/issues/5") is None


class TestSearchableText:
    def test_includes_attachments(self) -> None:
        msg = {
            "text": "",
            "attachments": [{"title": "New pipeline", "title_link": "https://github.com/nf-core/proposals/issues/77"}],
        }
        assert extract_proposal_number(message_searchable_text(msg)) == 77

    def test_includes_blocks(self) -> None:
        msg = {
            "text": "",
            "blocks": [
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": "<https://github.com/nf-core/proposals/issues/99|x>"},
                }
            ],
        }
        assert extract_proposal_number(message_searchable_text(msg)) == 99
