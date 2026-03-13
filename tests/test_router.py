"""Smoke tests for the command router."""

from __future__ import annotations

from nf_core_bot.commands.router import _parse_subcommand


def test_parse_empty_text() -> None:
    assert _parse_subcommand("") == ("help", [])


def test_parse_help() -> None:
    assert _parse_subcommand("help") == ("help", [])


def test_parse_hackathon_subcommand() -> None:
    assert _parse_subcommand("hackathon register") == ("hackathon", ["register"])


def test_parse_hackathon_admin_multi_args() -> None:
    assert _parse_subcommand("hackathon admin add-site") == ("hackathon", ["admin", "add-site"])


def test_parse_strips_whitespace() -> None:
    assert _parse_subcommand("  hackathon  attendees  ") == ("hackathon", ["attendees"])
