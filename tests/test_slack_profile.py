"""Tests for nf_core_bot.checks.slack_profile."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from nf_core_bot.checks.slack_profile import (
    _resolve_github_field_id,
    get_github_username,
    normalise_github_username,
)

# ── normalise_github_username ────────────────────────────────────────


class TestNormaliseGithubUsername:
    """Pure-function tests for normalise_github_username."""

    # --- Valid inputs ---

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("octocat", "octocat"),
            ("Octocat", "Octocat"),
            ("a", "a"),
            ("a1", "a1"),
            ("octo-cat", "octo-cat"),
            ("a" * 39, "a" * 39),
        ],
    )
    def test_bare_usernames(self, raw: str, expected: str) -> None:
        assert normalise_github_username(raw) == expected

    @pytest.mark.parametrize(
        "raw",
        [
            "https://github.com/octocat",
            "http://github.com/octocat",
            "github.com/octocat",
        ],
    )
    def test_url_forms(self, raw: str) -> None:
        assert normalise_github_username(raw) == "octocat"

    def test_url_with_trailing_slash(self) -> None:
        assert normalise_github_username("https://github.com/octocat/") == "octocat"

    def test_url_with_repo_path(self) -> None:
        # Should capture the username (first path segment), not the repo
        assert normalise_github_username("https://github.com/octocat/my-repo") == "octocat"

    def test_at_prefix(self) -> None:
        assert normalise_github_username("@octocat") == "octocat"

    def test_whitespace_stripping(self) -> None:
        assert normalise_github_username("  octocat  ") == "octocat"

    # --- Leading/trailing noise stripping ---

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("@jpaquay", "jpaquay"),  # real-world: @ prefix
            ("/santiagotariza", "santiagotariza"),  # real-world: leading slash
            ("\\octocat", "octocat"),  # leading backslash
            (".octocat", "octocat"),  # leading dot
            ("//octocat", "octocat"),  # double leading slash
            ("@/octocat", "octocat"),  # mixed leading noise
            ("/@octocat", "octocat"),  # mixed leading noise reversed
            ("@@octocat", "octocat"),  # double @
            ("octocat.", "octocat"),  # trailing dot
            ("octocat/", "octocat"),  # trailing slash
            ("octocat//", "octocat"),  # double trailing slash
            ("/octocat/", "octocat"),  # both sides
        ],
    )
    def test_leading_trailing_noise(self, raw: str, expected: str) -> None:
        """Non-alphanumeric characters around the username are stripped."""
        assert normalise_github_username(raw) == expected

    def test_url_with_trailing_dot(self) -> None:
        """github.com/octocat. (from sentence punctuation) extracts correctly."""
        assert normalise_github_username("https://github.com/octocat.") == "octocat"

    # --- Real-world inputs from past requests ---

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("@jpaquay", "jpaquay"),
            ("https://github.com/atakmty", "atakmty"),
            ("/santiagotariza", "santiagotariza"),
        ],
    )
    def test_real_world_valid(self, raw: str, expected: str) -> None:
        """Real inputs that users have submitted — should resolve cleanly."""
        assert normalise_github_username(raw) == expected

    @pytest.mark.parametrize(
        "raw",
        [
            "I don't know",
            ".",
        ],
    )
    def test_real_world_invalid(self, raw: str) -> None:
        """Real inputs that are not valid usernames — should return None."""
        assert normalise_github_username(raw) is None

    # --- Invalid inputs ---

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("-octocat", "octocat"),  # leading hyphen stripped
            ("octocat-", "octocat"),  # trailing hyphen stripped
            ("--octocat--", "octocat"),  # both sides stripped
        ],
    )
    def test_hyphen_noise_stripped(self, raw: str, expected: str) -> None:
        """Leading/trailing hyphens are treated as noise and stripped."""
        assert normalise_github_username(raw) == expected

    @pytest.mark.parametrize(
        "raw",
        [
            "",
            "   ",
            "-",  # only a hyphen
            "---",  # only hyphens
            "a" * 40,  # too long
            "octo_cat",  # underscore in middle
            "octo.cat",  # dot in middle
            "octo cat",  # space in middle
        ],
    )
    def test_invalid_usernames(self, raw: str) -> None:
        assert normalise_github_username(raw) is None

    def test_url_with_underscore_rejects(self) -> None:
        """URL extraction now falls through to validation, catching invalid chars."""
        assert normalise_github_username("https://github.com/some_user") is None

    def test_url_with_reserved_path(self) -> None:
        """github.com/settings extracts 'settings' — valid as a username pattern."""
        # 'settings' passes the regex (it's alphanumeric), but it's a GitHub
        # reserved name. We don't enforce reserved-name checks here.
        assert normalise_github_username("https://github.com/settings") == "settings"


# ── _resolve_github_field_id ─────────────────────────────────────────


class TestResolveGithubFieldId:
    """Tests for the cached field-ID discovery."""

    @pytest.fixture(autouse=True)
    def _reset_cache(self) -> None:
        """Clear module-level cache before each test."""
        import nf_core_bot.checks.slack_profile as mod

        mod._github_field_id = None
        mod._github_field_resolved = False
        mod._github_field_lock = None

    async def test_discovers_field_id(self) -> None:
        client = AsyncMock()
        client.api_call.return_value = {
            "profile": {
                "fields": [
                    {"id": "Xf123", "label": "GitHub Username"},
                    {"id": "Xf456", "label": "Twitter"},
                ]
            }
        }

        result = await _resolve_github_field_id(client)
        assert result == "Xf123"
        client.api_call.assert_awaited_once_with("team.profile.get")

    async def test_returns_none_when_no_github_field(self) -> None:
        client = AsyncMock()
        client.api_call.return_value = {"profile": {"fields": [{"id": "Xf456", "label": "Twitter"}]}}

        result = await _resolve_github_field_id(client)
        assert result is None

    async def test_caches_after_success(self) -> None:
        client = AsyncMock()
        client.api_call.return_value = {"profile": {"fields": [{"id": "Xf123", "label": "GitHub"}]}}

        await _resolve_github_field_id(client)
        await _resolve_github_field_id(client)

        # Only called once — second call hits cache
        assert client.api_call.await_count == 1

    async def test_retries_after_failure(self) -> None:
        """A transient API failure should NOT permanently cache ``None``."""
        client = AsyncMock()
        client.api_call.side_effect = [
            RuntimeError("network blip"),
            {"profile": {"fields": [{"id": "Xf123", "label": "GitHub"}]}},
        ]

        # First call fails
        result1 = await _resolve_github_field_id(client)
        assert result1 is None

        # Second call should retry and succeed
        result2 = await _resolve_github_field_id(client)
        assert result2 == "Xf123"
        assert client.api_call.await_count == 2


# ── get_github_username ──────────────────────────────────────────────


class TestGetGithubUsername:
    """Tests for the full profile → username pipeline."""

    @pytest.fixture(autouse=True)
    def _reset_cache(self) -> None:
        import nf_core_bot.checks.slack_profile as mod

        mod._github_field_id = None
        mod._github_field_resolved = False
        mod._github_field_lock = None

    async def test_returns_normalised_username(self) -> None:
        client = AsyncMock()
        client.api_call.return_value = {"profile": {"fields": [{"id": "Xf123", "label": "GitHub"}]}}
        client.users_profile_get.return_value = {
            "profile": {
                "fields": {
                    "Xf123": {"value": "https://github.com/octocat"},
                }
            }
        }

        result = await get_github_username(client, "U_TARGET")
        assert result == "octocat"

    async def test_returns_none_when_field_empty(self) -> None:
        client = AsyncMock()
        client.api_call.return_value = {"profile": {"fields": [{"id": "Xf123", "label": "GitHub"}]}}
        client.users_profile_get.return_value = {"profile": {"fields": {"Xf123": {"value": ""}}}}

        result = await get_github_username(client, "U_TARGET")
        assert result is None

    async def test_returns_none_when_no_field_id(self) -> None:
        client = AsyncMock()
        client.api_call.return_value = {"profile": {"fields": []}}

        result = await get_github_username(client, "U_TARGET")
        assert result is None
        # Should never even call users_profile_get
        client.users_profile_get.assert_not_awaited()

    async def test_returns_none_when_profile_api_fails(self) -> None:
        client = AsyncMock()
        client.api_call.return_value = {"profile": {"fields": [{"id": "Xf123", "label": "GitHub"}]}}
        client.users_profile_get.side_effect = RuntimeError("API error")

        result = await get_github_username(client, "U_TARGET")
        assert result is None

    async def test_handles_null_fields_dict(self) -> None:
        """Slack returns ``null`` for users with no custom fields."""
        client = AsyncMock()
        client.api_call.return_value = {"profile": {"fields": [{"id": "Xf123", "label": "GitHub"}]}}
        client.users_profile_get.return_value = {"profile": {"fields": None}}

        result = await get_github_username(client, "U_TARGET")
        assert result is None
