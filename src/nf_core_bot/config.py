"""Centralised configuration loaded from environment variables.

Values are read lazily on first access so that tests can monkeypatch env
vars before the module is imported.
"""

from __future__ import annotations

import os

# ── Defaults (used when the env var is unset) ───────────────────────

_DEFAULTS: dict[str, str | None] = {
    # Slack — required (no default)
    "SLACK_BOT_TOKEN": None,
    "SLACK_SIGNING_SECRET": None,
    "SLACK_APP_TOKEN": None,
    # GitHub
    "GITHUB_TOKEN": None,
    "GITHUB_ORG": "nf-core",
    # DynamoDB
    "DYNAMODB_TABLE": "nf-core-bot",
    "DYNAMODB_ENDPOINT": None,  # None → real AWS
    "AWS_REGION": "eu-west-1",
    # Permissions
    "CORE_TEAM_USERGROUP_HANDLE": "core-team",
}

_REQUIRED: frozenset[str] = frozenset(["SLACK_BOT_TOKEN", "SLACK_SIGNING_SECRET", "SLACK_APP_TOKEN", "GITHUB_TOKEN"])


def _get(name: str) -> str | None:
    """Resolve a config value from the environment, falling back to defaults."""
    value = os.environ.get(name)
    if value:
        return value
    default = _DEFAULTS.get(name)
    if default is not None:
        return default
    if name in _REQUIRED:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return None


def __getattr__(name: str) -> str | None:
    """Module-level ``__getattr__`` — makes config values importable as attributes.

    Usage::

        from nf_core_bot.config import SLACK_BOT_TOKEN
    """
    if name in _DEFAULTS:
        return _get(name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
