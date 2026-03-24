"""Tests for on-call calendar iCal generation, S3 upload, and command handler."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def slack_client() -> AsyncMock:
    """Slack client mock that can resolve user names."""
    client = AsyncMock()
    client.users_info.return_value = {
        "user": {"profile": {"display_name": "Alice", "real_name": "Alice Smith"}},
    }
    client.conversations_open.return_value = {"channel": {"id": "D_DM"}}
    return client


@pytest.fixture
def _clear_name_cache() -> None:
    """Clear the display-name cache between tests."""
    from nf_core_bot.calendar import generator

    generator._name_cache.clear()


# ---------------------------------------------------------------------------
# iCal generation tests
# ---------------------------------------------------------------------------


class TestCalendarGeneration:
    """Tests for iCal feed generation."""

    @pytest.mark.usefixtures("_clear_name_cache")
    async def test_global_calendar_empty_roster(self, ddb_table: Any, slack_client: AsyncMock) -> None:
        """Global calendar with no roster entries produces valid but empty iCal."""
        from nf_core_bot.calendar.generator import generate_global_calendar

        ical_bytes = await generate_global_calendar(slack_client)
        text = ical_bytes.decode()

        assert "BEGIN:VCALENDAR" in text
        assert "nf-core on-call" in text
        assert "BEGIN:VEVENT" not in text

    @pytest.mark.usefixtures("_clear_name_cache")
    async def test_global_calendar_with_entries(self, ddb_table: Any, slack_client: AsyncMock) -> None:
        """Global calendar includes events for each roster entry."""
        from nf_core_bot.db.oncall import put_roster_entry

        await put_roster_entry("2026-04-06", "U_ALICE")
        await put_roster_entry("2026-04-13", "U_BOB")

        # Bob gets a different name
        async def _users_info(user: str) -> dict[str, Any]:
            names = {"U_ALICE": "Alice", "U_BOB": "Bob"}
            return {"user": {"profile": {"display_name": names.get(user, user)}}}

        slack_client.users_info.side_effect = _users_info

        from nf_core_bot.calendar.generator import generate_global_calendar

        ical_bytes = await generate_global_calendar(slack_client)
        text = ical_bytes.decode()

        assert "nf-core on-call: Alice" in text
        assert "nf-core on-call: Bob" in text
        assert text.count("BEGIN:VEVENT") == 2

    @pytest.mark.usefixtures("_clear_name_cache")
    async def test_global_calendar_skips_unassigned_week(self, ddb_table: Any, slack_client: AsyncMock) -> None:
        """Unassigned weeks produce no calendar event."""
        from nf_core_bot.db.oncall import put_roster_entry

        await put_roster_entry("2026-04-06", "")

        from nf_core_bot.calendar.generator import generate_global_calendar

        ical_bytes = await generate_global_calendar(slack_client)
        text = ical_bytes.decode()

        assert "BEGIN:VEVENT" not in text

    @pytest.mark.usefixtures("_clear_name_cache")
    async def test_personal_calendar_filters_to_user(self, ddb_table: Any, slack_client: AsyncMock) -> None:
        """Personal calendar only includes the specified user's weeks."""
        from nf_core_bot.db.oncall import put_roster_entry

        await put_roster_entry("2026-04-06", "U_ALICE")
        await put_roster_entry("2026-04-13", "U_BOB")
        await put_roster_entry("2026-04-20", "U_ALICE")

        from nf_core_bot.calendar.generator import generate_personal_calendar

        ical_bytes = await generate_personal_calendar(slack_client, "U_ALICE")
        text = ical_bytes.decode()

        assert text.count("BEGIN:VEVENT") == 2
        assert "nf-core on-call: Alice" in text

    @pytest.mark.usefixtures("_clear_name_cache")
    async def test_personal_calendar_empty_for_unassigned_user(self, ddb_table: Any, slack_client: AsyncMock) -> None:
        """Personal calendar for a user with no weeks has no events."""
        from nf_core_bot.db.oncall import put_roster_entry

        await put_roster_entry("2026-04-06", "U_ALICE")

        from nf_core_bot.calendar.generator import generate_personal_calendar

        ical_bytes = await generate_personal_calendar(slack_client, "U_NOBODY")
        text = ical_bytes.decode()

        assert "BEGIN:VEVENT" not in text

    @pytest.mark.usefixtures("_clear_name_cache")
    async def test_events_span_full_week(self, ddb_table: Any, slack_client: AsyncMock) -> None:
        """Each event starts on Monday and ends the following Monday (exclusive)."""
        from nf_core_bot.db.oncall import put_roster_entry

        await put_roster_entry("2026-04-06", "U_ALICE")

        from nf_core_bot.calendar.generator import generate_global_calendar

        ical_bytes = await generate_global_calendar(slack_client)
        text = ical_bytes.decode()

        # All-day events use DATE format: DTSTART;VALUE=DATE:20260406
        assert "20260406" in text  # start
        assert "20260413" in text  # end (exclusive = next Monday)

    @pytest.mark.usefixtures("_clear_name_cache")
    async def test_display_name_fallback(self, ddb_table: Any, slack_client: AsyncMock) -> None:
        """If users_info fails, falls back to user ID."""
        from nf_core_bot.db.oncall import put_roster_entry

        await put_roster_entry("2026-04-06", "U_UNKNOWN")
        slack_client.users_info.side_effect = Exception("API error")

        from nf_core_bot.calendar.generator import generate_global_calendar

        ical_bytes = await generate_global_calendar(slack_client)
        text = ical_bytes.decode()

        assert "nf-core on-call: U_UNKNOWN" in text


# ---------------------------------------------------------------------------
# S3 upload tests
# ---------------------------------------------------------------------------


class TestS3Upload:
    """Tests for S3 upload logic."""

    async def test_upload_skipped_when_bucket_not_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Upload is a no-op when CALENDAR_S3_BUCKET is not set."""
        monkeypatch.setenv("CALENDAR_S3_BUCKET", "")

        from nf_core_bot.calendar.generator import _upload_to_s3

        # Should not raise
        await _upload_to_s3("test/file.ics", b"data")

    async def test_upload_calls_s3_put_object(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Upload calls s3.put_object with correct parameters."""
        monkeypatch.setenv("CALENDAR_S3_BUCKET", "my-bucket")

        mock_s3 = MagicMock()
        with patch("nf_core_bot.calendar.generator._get_s3_client", return_value=mock_s3):
            from nf_core_bot.calendar.generator import _upload_to_s3

            await _upload_to_s3("tok/oncall-all.ics", b"ical-data")

        mock_s3.put_object.assert_called_once_with(
            Bucket="my-bucket",
            Key="tok/oncall-all.ics",
            Body=b"ical-data",
            ContentType="text/calendar; charset=utf-8",
            CacheControl="max-age=300",
        )


# ---------------------------------------------------------------------------
# Calendar URL tests
# ---------------------------------------------------------------------------


class TestCalendarUrl:
    """Tests for URL generation."""

    def test_cloudfront_url(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """When CloudFront domain is set, URL uses it."""
        monkeypatch.setenv("CALENDAR_CLOUDFRONT_DOMAIN", "d1xyz.cloudfront.net")
        monkeypatch.setenv("CALENDAR_S3_BUCKET", "my-bucket")

        from nf_core_bot.calendar.generator import get_calendar_url

        url = get_calendar_url("tok123", "oncall-all.ics")
        assert url == "https://d1xyz.cloudfront.net/tok123/oncall-all.ics"

    def test_s3_only_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """When only S3 bucket is set (no CloudFront), URL returns None."""
        monkeypatch.setenv("CALENDAR_CLOUDFRONT_DOMAIN", "")
        monkeypatch.setenv("CALENDAR_S3_BUCKET", "my-bucket")

        from nf_core_bot.calendar.generator import get_calendar_url

        assert get_calendar_url("tok123", "oncall-all.ics") is None

    def test_no_url_when_unconfigured(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Returns None when neither CloudFront nor S3 is configured."""
        monkeypatch.setenv("CALENDAR_CLOUDFRONT_DOMAIN", "")
        monkeypatch.setenv("CALENDAR_S3_BUCKET", "")

        from nf_core_bot.calendar.generator import get_calendar_url

        assert get_calendar_url("tok123", "oncall-all.ics") is None


# ---------------------------------------------------------------------------
# DynamoDB calendar token tests
# ---------------------------------------------------------------------------


class TestCalendarToken:
    """Tests for calendar token management in DynamoDB."""

    async def test_get_token_returns_none_when_missing(self, ddb_table: Any) -> None:
        """get_calendar_token returns None when no token exists."""
        from nf_core_bot.db.oncall import get_calendar_token

        assert await get_calendar_token() is None

    async def test_get_or_create_creates_token(self, ddb_table: Any) -> None:
        """get_or_create_calendar_token creates and returns a token."""
        from nf_core_bot.db.oncall import get_calendar_token, get_or_create_calendar_token

        token = await get_or_create_calendar_token()
        assert token
        assert len(token) > 20

        # Subsequent call returns the same token
        token2 = await get_or_create_calendar_token()
        assert token2 == token

        # get also works
        token3 = await get_calendar_token()
        assert token3 == token

    async def test_token_is_stable(self, ddb_table: Any) -> None:
        """Multiple calls return the same token (not regenerated)."""
        from nf_core_bot.db.oncall import get_or_create_calendar_token

        tokens = [await get_or_create_calendar_token() for _ in range(3)]
        assert all(t == tokens[0] for t in tokens)


# ---------------------------------------------------------------------------
# Regenerate calendars integration test
# ---------------------------------------------------------------------------


class TestRegenerateCalendars:
    """Integration tests for the full regeneration pipeline."""

    @pytest.mark.usefixtures("_clear_name_cache")
    async def test_regenerate_skipped_when_no_bucket(
        self, ddb_table: Any, slack_client: AsyncMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """regenerate_calendars is a no-op when S3 is not configured."""
        monkeypatch.setenv("CALENDAR_S3_BUCKET", "")

        from nf_core_bot.calendar.generator import regenerate_calendars

        # Should not raise
        await regenerate_calendars(slack_client)

    @pytest.mark.usefixtures("_clear_name_cache")
    async def test_regenerate_skipped_when_no_token(
        self, ddb_table: Any, slack_client: AsyncMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """regenerate_calendars is a no-op when no token exists."""
        monkeypatch.setenv("CALENDAR_S3_BUCKET", "my-bucket")

        from nf_core_bot.calendar.generator import regenerate_calendars

        # No token has been created, so should skip
        await regenerate_calendars(slack_client)

    @pytest.mark.usefixtures("_clear_name_cache")
    async def test_regenerate_uploads_files(
        self, ddb_table: Any, slack_client: AsyncMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """regenerate_calendars uploads global + per-user calendar files."""
        monkeypatch.setenv("CALENDAR_S3_BUCKET", "my-bucket")

        from nf_core_bot.db.oncall import get_or_create_calendar_token, put_roster_entry

        token = await get_or_create_calendar_token()
        await put_roster_entry("2026-04-06", "U_ALICE")
        await put_roster_entry("2026-04-13", "U_BOB")

        uploaded: dict[str, bytes] = {}

        async def _mock_upload(key: str, body: bytes) -> None:
            uploaded[key] = body

        with patch("nf_core_bot.calendar.generator._upload_to_s3", side_effect=_mock_upload):
            from nf_core_bot.calendar.generator import regenerate_calendars

            await regenerate_calendars(slack_client)

        # Global + 2 personal feeds
        assert f"{token}/oncall-all.ics" in uploaded
        assert f"{token}/oncall-U_ALICE.ics" in uploaded
        assert f"{token}/oncall-U_BOB.ics" in uploaded
        assert len(uploaded) == 3


# ---------------------------------------------------------------------------
# Calendar command handler tests
# ---------------------------------------------------------------------------


class TestCalendarCommand:
    """Tests for the /nf-core on-call calendar command handler."""

    async def test_calendar_not_configured(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """When S3 bucket is not set, respond with a config error."""
        monkeypatch.setenv("CALENDAR_S3_BUCKET", "")
        respond = AsyncMock()
        client = AsyncMock()

        from nf_core_bot.commands.oncall.calendar_cmd import handle_oncall_calendar

        await handle_oncall_calendar(respond, client, "U_ALICE", ["all"])

        respond.assert_called_once()
        text = respond.call_args.args[0] if respond.call_args.args else respond.call_args.kwargs.get("text", "")
        assert "not configured" in text.lower()

    async def test_calendar_help_no_args(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """When no subcommand is given, show usage help."""
        monkeypatch.setenv("CALENDAR_S3_BUCKET", "my-bucket")
        respond = AsyncMock()
        client = AsyncMock()

        from nf_core_bot.commands.oncall.calendar_cmd import handle_oncall_calendar

        await handle_oncall_calendar(respond, client, "U_ALICE", [])

        respond.assert_called_once()
        text = respond.call_args.args[0] if respond.call_args.args else respond.call_args.kwargs.get("text", "")
        assert "usage" in text.lower()

    @pytest.mark.usefixtures("_clear_name_cache")
    async def test_calendar_all(self, ddb_table: Any, monkeypatch: pytest.MonkeyPatch, slack_client: AsyncMock) -> None:
        """calendar all returns a URL and subscribe instructions."""
        monkeypatch.setenv("CALENDAR_S3_BUCKET", "my-bucket")
        monkeypatch.setenv("CALENDAR_CLOUDFRONT_DOMAIN", "d1.cloudfront.net")
        respond = AsyncMock()

        with patch("nf_core_bot.commands.oncall.calendar_cmd.safe_regenerate_calendars", new_callable=AsyncMock):
            from nf_core_bot.commands.oncall.calendar_cmd import handle_oncall_calendar

            await handle_oncall_calendar(respond, slack_client, "U_ALICE", ["all"])

        respond.assert_called_once()
        text = respond.call_args.args[0] if respond.call_args.args else respond.call_args.kwargs.get("text", "")
        assert "oncall-all.ics" in text
        assert "Google Calendar" in text
        assert "d1.cloudfront.net" in text

    @pytest.mark.usefixtures("_clear_name_cache")
    async def test_calendar_me(self, ddb_table: Any, monkeypatch: pytest.MonkeyPatch, slack_client: AsyncMock) -> None:
        """calendar me returns a personal URL."""
        monkeypatch.setenv("CALENDAR_S3_BUCKET", "my-bucket")
        monkeypatch.setenv("CALENDAR_CLOUDFRONT_DOMAIN", "d1.cloudfront.net")
        respond = AsyncMock()

        with patch("nf_core_bot.commands.oncall.calendar_cmd.safe_regenerate_calendars", new_callable=AsyncMock):
            from nf_core_bot.commands.oncall.calendar_cmd import handle_oncall_calendar

            await handle_oncall_calendar(respond, slack_client, "U_ALICE", ["me"])

        respond.assert_called_once()
        text = respond.call_args.args[0] if respond.call_args.args else respond.call_args.kwargs.get("text", "")
        assert "oncall-U_ALICE.ics" in text
        assert "Google Calendar" in text

    async def test_calendar_unknown_subcommand(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Unknown subcommand shows usage help."""
        monkeypatch.setenv("CALENDAR_S3_BUCKET", "my-bucket")
        respond = AsyncMock()
        client = AsyncMock()

        from nf_core_bot.commands.oncall.calendar_cmd import handle_oncall_calendar

        await handle_oncall_calendar(respond, client, "U_ALICE", ["foobar"])

        respond.assert_called_once()
        text = respond.call_args.args[0] if respond.call_args.args else respond.call_args.kwargs.get("text", "")
        assert "usage" in text.lower()


# ---------------------------------------------------------------------------
# Router integration test for calendar dispatch
# ---------------------------------------------------------------------------


class TestCalendarRouterIntegration:
    """Verify the calendar command is correctly routed."""

    async def test_calendar_dispatched_with_correct_args(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Router calls handle_oncall_calendar with (respond, client, user_id, rest)."""
        from nf_core_bot.commands import router as router_mod

        handler_mock = AsyncMock()
        monkeypatch.setitem(router_mod._ONCALL_DISPATCH, "calendar", handler_mock)
        monkeypatch.setattr(router_mod, "is_core_team", AsyncMock(return_value=True))

        ack = AsyncMock()
        respond = AsyncMock()
        client = AsyncMock()

        await router_mod._route_oncall(
            ack=ack,
            respond=respond,
            client=client,
            user_id="U123",
            tokens=["calendar", "all"],
        )

        handler_mock.assert_called_once_with(respond, client, "U123", ["all"])
