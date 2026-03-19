"""Tests for the on-call background scheduler."""

from __future__ import annotations

import datetime
from unittest.mock import AsyncMock, patch

import pytest


@pytest.fixture
def client() -> AsyncMock:
    # Clear the timezone cache so tests are isolated
    from nf_core_bot.scheduler.oncall_jobs import _tz_cache

    _tz_cache.clear()

    mock = AsyncMock()
    # Default users_info response for timezone lookups
    mock.users_info.return_value = {"user": {"tz_offset": 0}}
    return mock


# ---------------------------------------------------------------------------
# _pick_next_person
# ---------------------------------------------------------------------------


class TestPickNextPerson:
    async def test_picks_never_assigned_first(self, ddb_table) -> None:
        from nf_core_bot.scheduler.oncall_jobs import _pick_next_person

        members = {"U111", "U222", "U333"}
        roster: list[dict] = []
        rr_state = {"last_assigned": {"U111": "2026-03-01", "U222": "2026-02-01"}, "queue_front": []}

        result = await _pick_next_person(members, roster, rr_state, "2026-04-06")
        # U333 has never been assigned
        assert result == "U333"

    async def test_picks_longest_ago(self, ddb_table) -> None:
        from nf_core_bot.scheduler.oncall_jobs import _pick_next_person

        members = {"U111", "U222", "U333"}
        roster: list[dict] = []
        rr_state = {
            "last_assigned": {"U111": "2026-03-01", "U222": "2026-01-01", "U333": "2026-02-01"},
            "queue_front": [],
        }

        result = await _pick_next_person(members, roster, rr_state, "2026-04-06")
        assert result == "U222"  # oldest assignment

    async def test_queue_front_has_priority(self, ddb_table) -> None:
        from nf_core_bot.scheduler.oncall_jobs import _pick_next_person

        members = {"U111", "U222", "U333"}
        roster: list[dict] = []
        rr_state = {
            "last_assigned": {"U111": "2026-03-01", "U222": "2026-01-01", "U333": "2026-02-01"},
            "queue_front": ["U333"],
        }

        # U333 is in queue_front so gets picked despite U222 being older
        result = await _pick_next_person(members, roster, rr_state, "2026-04-06")
        assert result == "U333"

    async def test_skips_assigned_users(self, ddb_table) -> None:
        from nf_core_bot.scheduler.oncall_jobs import _pick_next_person

        members = {"U111", "U222", "U333"}
        roster = [{"assigned_user_id": "U222", "week_start": "2026-04-06"}]
        rr_state = {"last_assigned": {}, "queue_front": []}

        result = await _pick_next_person(members, roster, rr_state, "2026-04-13")
        assert result in {"U111", "U333"}
        assert result != "U222"

    async def test_skips_unavailable_users(self, ddb_table) -> None:
        from nf_core_bot.db.oncall import add_unavailability
        from nf_core_bot.scheduler.oncall_jobs import _pick_next_person

        await add_unavailability("U111", "2026-04-06", "2026-04-12")

        members = {"U111", "U222"}
        roster: list[dict] = []
        rr_state = {"last_assigned": {}, "queue_front": []}

        result = await _pick_next_person(members, roster, rr_state, "2026-04-06")
        assert result == "U222"

    async def test_returns_none_when_no_candidates(self, ddb_table) -> None:
        from nf_core_bot.db.oncall import add_unavailability
        from nf_core_bot.scheduler.oncall_jobs import _pick_next_person

        await add_unavailability("U111", "2026-04-06", "2026-04-12")

        members = {"U111"}
        roster: list[dict] = []
        rr_state = {"last_assigned": {}, "queue_front": []}

        result = await _pick_next_person(members, roster, rr_state, "2026-04-06")
        assert result is None


# ---------------------------------------------------------------------------
# _maybe_extend_roster
# ---------------------------------------------------------------------------


class TestMaybeExtendRoster:
    @patch("nf_core_bot.scheduler.oncall_jobs.refresh_core_team", new_callable=AsyncMock)
    async def test_creates_schedule(self, mock_refresh, ddb_table, client) -> None:
        from nf_core_bot.db.oncall import list_roster
        from nf_core_bot.scheduler.oncall_jobs import _maybe_extend_roster

        mock_refresh.return_value = {"U111", "U222", "U333"}

        with patch("nf_core_bot.scheduler.oncall_jobs.datetime") as mock_dt:
            mock_dt.date.today.return_value = datetime.date(2026, 4, 6)
            mock_dt.timedelta = datetime.timedelta
            mock_dt.UTC = datetime.UTC
            mock_dt.datetime = datetime.datetime
            await _maybe_extend_roster(client)

        roster = await list_roster()
        assert len(roster) == 8
        # All 3 members should appear in the schedule
        assigned = {e["assigned_user_id"] for e in roster}
        assert assigned == {"U111", "U222", "U333"}

    @patch("nf_core_bot.scheduler.oncall_jobs.refresh_core_team", new_callable=AsyncMock)
    async def test_does_not_double_schedule(self, mock_refresh, ddb_table, client) -> None:
        from nf_core_bot.db.oncall import list_roster, put_roster_entry
        from nf_core_bot.scheduler.oncall_jobs import _maybe_extend_roster

        mock_refresh.return_value = {"U111", "U222"}

        # Pre-create some entries
        await put_roster_entry("2026-04-06", "U111")
        await put_roster_entry("2026-04-13", "U222")

        with patch("nf_core_bot.scheduler.oncall_jobs.datetime") as mock_dt:
            mock_dt.date.today.return_value = datetime.date(2026, 4, 6)
            mock_dt.timedelta = datetime.timedelta
            mock_dt.UTC = datetime.UTC
            mock_dt.datetime = datetime.datetime
            await _maybe_extend_roster(client)

        roster = await list_roster()
        assert len(roster) == 8
        # The pre-existing entries should not be overwritten
        assert roster[0]["assigned_user_id"] == "U111"
        assert roster[1]["assigned_user_id"] == "U222"

    @patch("nf_core_bot.scheduler.oncall_jobs.refresh_core_team", new_callable=AsyncMock)
    async def test_reassigns_departed_members(self, mock_refresh, ddb_table, client) -> None:
        from nf_core_bot.db.oncall import get_roster_entry, put_roster_entry
        from nf_core_bot.scheduler.oncall_jobs import _maybe_extend_roster

        # U999 is assigned but no longer in core-team
        await put_roster_entry("2026-04-06", "U999")
        mock_refresh.return_value = {"U111", "U222"}

        with patch("nf_core_bot.scheduler.oncall_jobs.datetime") as mock_dt:
            mock_dt.date.today.return_value = datetime.date(2026, 4, 6)
            mock_dt.timedelta = datetime.timedelta
            mock_dt.UTC = datetime.UTC
            mock_dt.datetime = datetime.datetime
            await _maybe_extend_roster(client)

        entry = await get_roster_entry("2026-04-06")
        assert entry is not None
        assert entry["assigned_user_id"] in {"U111", "U222"}

    @patch("nf_core_bot.scheduler.oncall_jobs.refresh_core_team", new_callable=AsyncMock)
    async def test_warns_when_no_members(self, mock_refresh, ddb_table, client) -> None:
        from nf_core_bot.db.oncall import list_roster
        from nf_core_bot.scheduler.oncall_jobs import _maybe_extend_roster

        mock_refresh.return_value = set()

        with patch("nf_core_bot.scheduler.oncall_jobs.datetime") as mock_dt:
            mock_dt.date.today.return_value = datetime.date(2026, 4, 6)
            mock_dt.timedelta = datetime.timedelta
            mock_dt.UTC = datetime.UTC
            mock_dt.datetime = datetime.datetime
            await _maybe_extend_roster(client)

        # Should not create any entries
        roster = await list_roster()
        assert len(roster) == 0

    @patch("nf_core_bot.scheduler.oncall_jobs.refresh_core_team", new_callable=AsyncMock)
    async def test_sends_assignment_dm(self, mock_refresh, ddb_table, client) -> None:
        from nf_core_bot.scheduler.oncall_jobs import _maybe_extend_roster

        mock_refresh.return_value = {"U111"}

        with patch("nf_core_bot.scheduler.oncall_jobs.datetime") as mock_dt:
            mock_dt.date.today.return_value = datetime.date(2026, 4, 6)
            mock_dt.timedelta = datetime.timedelta
            mock_dt.UTC = datetime.UTC
            mock_dt.datetime = datetime.datetime
            await _maybe_extend_roster(client)

        # Should have sent DMs for new assignments
        assert client.chat_postMessage.await_count >= 1
        # Check at least one message mentions on-call
        msgs = [call.kwargs.get("text", "") for call in client.chat_postMessage.call_args_list]
        assert any("on call" in m.lower() for m in msgs)


# ---------------------------------------------------------------------------
# Reminders
# ---------------------------------------------------------------------------


class TestProcessReminders:
    @patch("nf_core_bot.scheduler.oncall_jobs.list_roster", new_callable=AsyncMock)
    async def test_monday_announcement(self, mock_roster, ddb_table, client) -> None:
        from nf_core_bot.db.oncall import get_reminder_tracking
        from nf_core_bot.scheduler.oncall_jobs import TARGET_HOUR_UTC, _process_reminders

        mock_roster.return_value = [
            {"week_start": "2026-04-06", "assigned_user_id": "U111", "status": "scheduled"},
        ]

        # Simulate Monday Apr 6 at 08:00 UTC
        now = datetime.datetime(2026, 4, 6, TARGET_HOUR_UTC, 0, tzinfo=datetime.UTC)
        with patch("nf_core_bot.scheduler.oncall_jobs.datetime") as mock_dt:
            mock_dt.date.today.return_value = datetime.date(2026, 4, 6)
            mock_dt.date.fromisoformat = datetime.date.fromisoformat
            mock_dt.timedelta = datetime.timedelta
            mock_dt.timezone = datetime.timezone
            mock_dt.UTC = datetime.UTC
            await _process_reminders(client, now)

        # Should have posted to #core
        channel_calls = [c for c in client.chat_postMessage.call_args_list if c.kwargs.get("channel") == "core"]
        assert len(channel_calls) == 1
        assert "<@U111>" in channel_calls[0].kwargs["text"]

        # Tracking should be updated
        tracking = await get_reminder_tracking("2026-04-06")
        assert tracking["announcement_sent"] is True

    @patch("nf_core_bot.scheduler.oncall_jobs.list_roster", new_callable=AsyncMock)
    async def test_week_before_reminder(self, mock_roster, ddb_table, client) -> None:
        from nf_core_bot.db.oncall import get_reminder_tracking
        from nf_core_bot.scheduler.oncall_jobs import TARGET_HOUR_UTC, _process_reminders

        mock_roster.return_value = [
            {"week_start": "2026-04-13", "assigned_user_id": "U111", "status": "scheduled"},
        ]

        # Simulate Monday Apr 6 (one week before Apr 13)
        now = datetime.datetime(2026, 4, 6, TARGET_HOUR_UTC, 0, tzinfo=datetime.UTC)
        with patch("nf_core_bot.scheduler.oncall_jobs.datetime") as mock_dt:
            mock_dt.date.today.return_value = datetime.date(2026, 4, 6)
            mock_dt.date.fromisoformat = datetime.date.fromisoformat
            mock_dt.timedelta = datetime.timedelta
            mock_dt.timezone = datetime.timezone
            mock_dt.UTC = datetime.UTC
            await _process_reminders(client, now)

        # Should DM the user
        dm_calls = [c for c in client.chat_postMessage.call_args_list if c.kwargs.get("channel") == "U111"]
        assert len(dm_calls) == 1
        assert "next week" in dm_calls[0].kwargs["text"].lower()

        tracking = await get_reminder_tracking("2026-04-13")
        assert tracking["week_before_sent"] is True

    @patch("nf_core_bot.scheduler.oncall_jobs.list_roster", new_callable=AsyncMock)
    async def test_daily_reminder_user_timezone(self, mock_roster, ddb_table, client) -> None:
        from nf_core_bot.db.oncall import get_reminder_tracking
        from nf_core_bot.scheduler.oncall_jobs import _process_reminders

        mock_roster.return_value = [
            {"week_start": "2026-04-06", "assigned_user_id": "U111", "status": "scheduled"},
        ]

        # User is at UTC+2 (e.g. CET summer). It's 06:00 UTC = 08:00 local.
        client.users_info.return_value = {"user": {"tz_offset": 7200}}

        now = datetime.datetime(2026, 4, 7, 6, 0, tzinfo=datetime.UTC)  # Tuesday 06:00 UTC
        with patch("nf_core_bot.scheduler.oncall_jobs.datetime") as mock_dt:
            mock_dt.date.today.return_value = datetime.date(2026, 4, 7)
            mock_dt.date.fromisoformat = datetime.date.fromisoformat
            mock_dt.timedelta = datetime.timedelta
            mock_dt.timezone = datetime.timezone
            mock_dt.UTC = datetime.UTC
            mock_dt.datetime = datetime.datetime
            await _process_reminders(client, now)

        dm_calls = [c for c in client.chat_postMessage.call_args_list if c.kwargs.get("channel") == "U111"]
        assert len(dm_calls) == 1
        assert "on call" in dm_calls[0].kwargs["text"].lower()

        tracking = await get_reminder_tracking("2026-04-06")
        assert "2026-04-07" in tracking["daily_sent"]

    @patch("nf_core_bot.scheduler.oncall_jobs.list_roster", new_callable=AsyncMock)
    async def test_daily_reminder_not_sent_twice(self, mock_roster, ddb_table, client) -> None:
        from nf_core_bot.db.oncall import save_reminder_tracking
        from nf_core_bot.scheduler.oncall_jobs import _process_reminders

        mock_roster.return_value = [
            {"week_start": "2026-04-06", "assigned_user_id": "U111", "status": "scheduled"},
        ]

        # Mark today's reminder as already sent
        await save_reminder_tracking(
            "2026-04-06",
            {
                "assignment_sent": True,
                "week_before_sent": True,
                "daily_sent": ["2026-04-07"],
                "announcement_sent": True,
            },
        )

        now = datetime.datetime(2026, 4, 7, 8, 0, tzinfo=datetime.UTC)
        with patch("nf_core_bot.scheduler.oncall_jobs.datetime") as mock_dt:
            mock_dt.date.today.return_value = datetime.date(2026, 4, 7)
            mock_dt.date.fromisoformat = datetime.date.fromisoformat
            mock_dt.timedelta = datetime.timedelta
            mock_dt.timezone = datetime.timezone
            mock_dt.UTC = datetime.UTC
            mock_dt.datetime = datetime.datetime
            await _process_reminders(client, now)

        # No new DMs should have been sent
        client.chat_postMessage.assert_not_awaited()

    @patch("nf_core_bot.scheduler.oncall_jobs.list_roster", new_callable=AsyncMock)
    async def test_skips_unassigned_weeks(self, mock_roster, ddb_table, client) -> None:
        from nf_core_bot.scheduler.oncall_jobs import _process_reminders

        mock_roster.return_value = [
            {"week_start": "2026-04-06", "assigned_user_id": "", "status": "scheduled"},
        ]

        now = datetime.datetime(2026, 4, 6, 8, 0, tzinfo=datetime.UTC)
        with patch("nf_core_bot.scheduler.oncall_jobs.datetime") as mock_dt:
            mock_dt.date.today.return_value = datetime.date(2026, 4, 6)
            mock_dt.date.fromisoformat = datetime.date.fromisoformat
            mock_dt.timedelta = datetime.timedelta
            mock_dt.timezone = datetime.timezone
            mock_dt.UTC = datetime.UTC
            await _process_reminders(client, now)

        client.chat_postMessage.assert_not_awaited()


# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------


class TestCleanupOldEntries:
    async def test_removes_old_entries(self, ddb_table) -> None:
        from nf_core_bot.db.oncall import list_roster, put_roster_entry
        from nf_core_bot.scheduler.oncall_jobs import _cleanup_old_entries

        # Create entries spanning old and recent
        await put_roster_entry("2026-01-05", "U111")  # very old
        await put_roster_entry("2026-02-02", "U222")  # old
        await put_roster_entry("2026-04-06", "U333")  # recent

        with patch("nf_core_bot.scheduler.oncall_jobs.datetime") as mock_dt:
            mock_dt.date.today.return_value = datetime.date(2026, 4, 6)
            mock_dt.timedelta = datetime.timedelta
            await _cleanup_old_entries()

        roster = await list_roster()
        weeks = [e["week_start"] for e in roster]
        assert "2026-01-05" not in weeks
        assert "2026-02-02" not in weeks
        assert "2026-04-06" in weeks

    async def test_no_entries_to_clean(self, ddb_table) -> None:
        from nf_core_bot.db.oncall import list_roster, put_roster_entry
        from nf_core_bot.scheduler.oncall_jobs import _cleanup_old_entries

        await put_roster_entry("2026-04-06", "U111")

        with patch("nf_core_bot.scheduler.oncall_jobs.datetime") as mock_dt:
            mock_dt.date.today.return_value = datetime.date(2026, 4, 6)
            mock_dt.timedelta = datetime.timedelta
            await _cleanup_old_entries()

        roster = await list_roster()
        assert len(roster) == 1


# ---------------------------------------------------------------------------
# _is_user_local_morning
# ---------------------------------------------------------------------------


class TestIsUserLocalMorning:
    async def test_utc_user_at_8am(self, client) -> None:
        from nf_core_bot.scheduler.oncall_jobs import _is_user_local_morning

        client.users_info.return_value = {"user": {"tz_offset": 0}}
        now = datetime.datetime(2026, 4, 6, 8, 0, tzinfo=datetime.UTC)

        assert await _is_user_local_morning(client, "U111", now) is True

    async def test_utc_user_not_8am(self, client) -> None:
        from nf_core_bot.scheduler.oncall_jobs import _is_user_local_morning

        client.users_info.return_value = {"user": {"tz_offset": 0}}
        now = datetime.datetime(2026, 4, 6, 10, 0, tzinfo=datetime.UTC)

        assert await _is_user_local_morning(client, "U111", now) is False

    async def test_positive_offset(self, client) -> None:
        from nf_core_bot.scheduler.oncall_jobs import _is_user_local_morning

        # UTC+2: 06:00 UTC = 08:00 local
        client.users_info.return_value = {"user": {"tz_offset": 7200}}
        now = datetime.datetime(2026, 4, 6, 6, 0, tzinfo=datetime.UTC)

        assert await _is_user_local_morning(client, "U111", now) is True

    async def test_negative_offset(self, client) -> None:
        from nf_core_bot.scheduler.oncall_jobs import _is_user_local_morning

        # UTC-5: 13:00 UTC = 08:00 local
        client.users_info.return_value = {"user": {"tz_offset": -18000}}
        now = datetime.datetime(2026, 4, 6, 13, 0, tzinfo=datetime.UTC)

        assert await _is_user_local_morning(client, "U111", now) is True

    async def test_fallback_on_api_error(self, client) -> None:
        from nf_core_bot.scheduler.oncall_jobs import _is_user_local_morning

        client.users_info.side_effect = Exception("API error")
        now = datetime.datetime(2026, 4, 6, 8, 0, tzinfo=datetime.UTC)

        # Falls back to UTC
        assert await _is_user_local_morning(client, "U111", now) is True
