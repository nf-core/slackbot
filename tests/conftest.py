"""Shared test fixtures — mocked DynamoDB, Slack client stubs."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, patch

import pytest
from moto import mock_aws

from nf_core_bot.checks.github import GitHubResult

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Iterator


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


@pytest.fixture
async def ddb_table() -> AsyncIterator[Any]:
    """Create a mocked DynamoDB table for testing."""
    with mock_aws():
        from nf_core_bot.db import client as db_client

        db_client._table = None
        db_client.init(table_name="test-table", endpoint_url=None, region="us-east-1")
        yield db_client.get_table()
        db_client._table = None


@pytest.fixture(autouse=True)
def _user_exists() -> Iterator[AsyncMock]:
    """Default the GitHub user-existence check to "exists" for every test.

    The invite flow calls ``check_user_exists`` before inviting; tests that
    care about the "user not found" path override this mock's return value.
    """
    with patch(
        "nf_core_bot.commands.github.invite_flow.check_user_exists",
        return_value=GitHubResult(ok=True, message="exists"),
    ) as mock:
        yield mock
