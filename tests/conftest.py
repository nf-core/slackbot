"""Shared test fixtures — mocked DynamoDB, Slack client stubs."""

from __future__ import annotations

import os

import pytest


@pytest.fixture(autouse=True)
def _env_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure required env vars are set for every test."""
    defaults = {
        "SLACK_BOT_TOKEN": "xoxb-test-token",
        "SLACK_SIGNING_SECRET": "test-signing-secret",
        "SLACK_APP_TOKEN": "xapp-test-app-token",
        "GITHUB_TOKEN": "ghp_test-token",
        "GITHUB_ORG": "nf-core",
        "DYNAMODB_TABLE": "nf-core-bot-test",
        "DYNAMODB_ENDPOINT": "http://localhost:8000",
        "AWS_REGION": "us-east-1",
        "CORE_TEAM_USERGROUP_HANDLE": "core-team",
    }
    for key, value in defaults.items():
        monkeypatch.setenv(key, os.environ.get(key, value))
