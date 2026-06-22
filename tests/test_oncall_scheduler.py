"""Tests for the on-call background scheduler."""

from __future__ import annotations

import datetime
from unittest.mock import AsyncMock, patch

import pytest


@pytest.fixture
def client() -> AsyncMock:
    # Clear the timezone cache and channel-ID cache so tests are isolated
    import nf_core_bot.scheduler.oncall_jobs as jobs

    jobs._tz_cache.clear()
    jobs._channel_id = None

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
    @patch("nf_core_bot.scheduler.oncall_jobs.resolve_channel_id", new_callable=AsyncMock, return_value="C_LINK")
    @patch("nf_core_bot.scheduler.oncall_jobs.list_open_proposals", new_callable=AsyncMock, return_value=[])
    @patch("nf_core_bot.scheduler.oncall_jobs._resolve_channel_id", new_callable=AsyncMock, return_value="C_CORE")
    @patch("nf_core_bot.scheduler.oncall_jobs.list_roster", new_callable=AsyncMock)
    async def test_monday_announcement(
        self, mock_roster, _mock_ch, mock_proposals, _mock_link, ddb_table, client
    ) -> None:
        from nf_core_bot.checks.github import Proposal
        from nf_core_bot.db.oncall import get_reminder_tracking
        from nf_core_bot.scheduler.oncall_jobs import TARGET_HOUR_UTC, _process_reminders

        mock_roster.return_value = [
            {"week_start": "2026-04-06", "assigned_user_id": "U111", "status": "scheduled"},
        ]
        mock_proposals.return_value = [
            Proposal(title="cfmultiomics", url="https://github.com/nf-core/proposals/issues/144", section="pipeline"),
        ]
        # chat_postMessage must return a ts so the thread replies can be anchored.
        client.chat_postMessage.return_value = {"ts": "1700000000.000100"}

        # Simulate Monday Apr 6 at 08:00 UTC
        now = datetime.datetime(2026, 4, 6, TARGET_HOUR_UTC, 0, tzinfo=datetime.UTC)
        with patch("nf_core_bot.scheduler.oncall_jobs.datetime") as mock_dt:
            mock_dt.date.today.return_value = datetime.date(2026, 4, 6)
            mock_dt.date.fromisoformat = datetime.date.fromisoformat
            mock_dt.timedelta = datetime.timedelta
            mock_dt.timezone = datetime.timezone
            mock_dt.UTC = datetime.UTC
            mock_dt.datetime = datetime.datetime
            await _process_reminders(client, now)

        channel_calls = [c for c in client.chat_postMessage.call_args_list if c.kwargs.get("channel") == "C_CORE"]

        # The announcement itself is the only top-level (non-threaded) post.
        announcements = [c for c in channel_calls if not c.kwargs.get("thread_ts")]
        assert len(announcements) == 1
        assert "<@U111>" in announcements[0].kwargs["text"]

        # Three thread replies anchored to the announcement ts:
        # responsibilities + proposals + docs.
        replies = [c for c in channel_calls if c.kwargs.get("thread_ts") == "1700000000.000100"]
        assert len(replies) == 3
        assert "Start of week responsibilities" in replies[0].kwargs["text"]
        # Channel references render as clickable <#ID> links.
        assert "<#C_LINK>" in replies[0].kwargs["text"]
        assert "Open pipeline proposals" in replies[1].kwargs["text"]
        assert "issues/144|cfmultiomics" in replies[1].kwargs["text"]
        assert "Docs:" in replies[2].kwargs["text"]

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

    async def test_nz_user_gets_correct_week_dm(self, ddb_table, client) -> None:
        """Regression: NZ user (UTC+12) at 8am Monday local (Sunday 20:00 UTC)
        should receive a DM for the Monday-starting week, not the previous week."""
        from nf_core_bot.db.oncall import get_reminder_tracking
        from nf_core_bot.scheduler.oncall_jobs import _process_reminders

        # NZ timezone: UTC+12
        client.users_info.return_value = {"user": {"tz_offset": 43200}}

        # Roster: previous week (March 30) and current week (April 6)
        with patch("nf_core_bot.scheduler.oncall_jobs.list_roster", new_callable=AsyncMock) as mock_roster_fn:
            mock_roster_fn.return_value = [
                {"week_start": "2026-03-30", "assigned_user_id": "U_OTHER", "status": "completed"},
                {"week_start": "2026-04-06", "assigned_user_id": "U_NZ", "status": "scheduled"},
            ]

            # Sunday 20:00 UTC = Monday 08:00 NZ
            now = datetime.datetime(2026, 4, 5, 20, 0, tzinfo=datetime.UTC)
            with patch("nf_core_bot.scheduler.oncall_jobs.datetime") as mock_dt:
                mock_dt.date.today.return_value = datetime.date(2026, 4, 5)  # UTC: Sunday
                mock_dt.date.fromisoformat = datetime.date.fromisoformat
                mock_dt.timedelta = datetime.timedelta
                mock_dt.timezone = datetime.timezone
                mock_dt.UTC = datetime.UTC
                mock_dt.datetime = datetime.datetime
                await _process_reminders(client, now)

        # Should have sent a DM to NZ user for the April 6 week
        calls = client.chat_postMessage.call_args_list
        dm_calls = [c for c in calls if c.kwargs.get("channel") == "U_NZ"]
        assert len(dm_calls) == 1
        assert "on call this week" in dm_calls[0].kwargs["text"]

        # Tracking should show local date (2026-04-06), not UTC date (2026-04-05)
        tracking = await get_reminder_tracking("2026-04-06")
        assert "2026-04-06" in tracking.get("daily_sent", [])

    async def test_no_dm_on_weekends(self, ddb_table, client) -> None:
        """Daily reminders should only be sent Mon–Fri, not on weekends."""
        from nf_core_bot.scheduler.oncall_jobs import _process_reminders

        # Default tz_offset=0 (UTC)
        client.users_info.return_value = {"user": {"tz_offset": 0}}

        with patch("nf_core_bot.scheduler.oncall_jobs.list_roster", new_callable=AsyncMock) as mock_roster_fn:
            mock_roster_fn.return_value = [
                {"week_start": "2026-04-06", "assigned_user_id": "U_ONCALL", "status": "scheduled"},
            ]

            # Saturday April 11, 2026 at 08:00 UTC (weekday=5)
            now = datetime.datetime(2026, 4, 11, 8, 0, tzinfo=datetime.UTC)
            with patch("nf_core_bot.scheduler.oncall_jobs.datetime") as mock_dt:
                mock_dt.date.today.return_value = datetime.date(2026, 4, 11)
                mock_dt.date.fromisoformat = datetime.date.fromisoformat
                mock_dt.timedelta = datetime.timedelta
                mock_dt.timezone = datetime.timezone
                mock_dt.UTC = datetime.UTC
                mock_dt.datetime = datetime.datetime
                await _process_reminders(client, now)

        # No daily DM should have been sent on Saturday
        dm_calls = [c for c in client.chat_postMessage.call_args_list if c.kwargs.get("channel") == "U_ONCALL"]
        assert len(dm_calls) == 0

    async def test_no_dm_on_sunday(self, ddb_table, client) -> None:
        """Sunday should also be skipped for daily reminders."""
        from nf_core_bot.scheduler.oncall_jobs import _process_reminders

        client.users_info.return_value = {"user": {"tz_offset": 0}}

        with patch("nf_core_bot.scheduler.oncall_jobs.list_roster", new_callable=AsyncMock) as mock_roster_fn:
            mock_roster_fn.return_value = [
                {"week_start": "2026-04-06", "assigned_user_id": "U_ONCALL", "status": "scheduled"},
            ]

            # Sunday April 12, 2026 at 08:00 UTC (weekday=6)
            now = datetime.datetime(2026, 4, 12, 8, 0, tzinfo=datetime.UTC)
            with patch("nf_core_bot.scheduler.oncall_jobs.datetime") as mock_dt:
                mock_dt.date.today.return_value = datetime.date(2026, 4, 12)
                mock_dt.date.fromisoformat = datetime.date.fromisoformat
                mock_dt.timedelta = datetime.timedelta
                mock_dt.timezone = datetime.timezone
                mock_dt.UTC = datetime.UTC
                mock_dt.datetime = datetime.datetime
                await _process_reminders(client, now)

        dm_calls = [c for c in client.chat_postMessage.call_args_list if c.kwargs.get("channel") == "U_ONCALL"]
        assert len(dm_calls) == 0


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
# _format_proposals_digest
# ---------------------------------------------------------------------------


class TestFormatProposalsDigest:
    def _proposals(self, section: str, n: int) -> list:
        from nf_core_bot.checks.github import Proposal

        return [
            Proposal(title=f"{section}-{i}", url=f"https://example.com/{section}/{i}", section=section)
            for i in range(n)
        ]

    def test_returns_none_when_empty(self) -> None:
        from nf_core_bot.scheduler.oncall_jobs import _format_proposals_digest

        assert _format_proposals_digest([]) is None

    def test_omits_empty_sections_and_orders(self) -> None:
        from nf_core_bot.scheduler.oncall_jobs import _format_proposals_digest

        # Only accepted + rfc present; pipeline/rejected omitted entirely.
        proposals = self._proposals("rfc", 1) + self._proposals("accepted", 1)
        message = _format_proposals_digest(proposals)
        assert message is not None
        assert "Open pipeline proposals" not in message
        assert "please close" not in message
        # Accepted section renders before the RFC section.
        assert message.index("ready to set up") < message.index("Open RFC proposals")

    def test_truncates_with_more_bullet(self) -> None:
        from nf_core_bot.scheduler.oncall_jobs import MAX_PROPOSALS_PER_SECTION, _format_proposals_digest

        message = _format_proposals_digest(self._proposals("pipeline", MAX_PROPOSALS_PER_SECTION + 3))
        assert message is not None
        assert message.count("- <") == MAX_PROPOSALS_PER_SECTION
        assert "- (3 more)" in message

    def test_renders_slack_links(self) -> None:
        from nf_core_bot.scheduler.oncall_jobs import _format_proposals_digest

        message = _format_proposals_digest(self._proposals("pipeline", 1))
        assert "- <https://example.com/pipeline/0|pipeline-0>" in message


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


# ---------------------------------------------------------------------------
# Channel-ID resolution
# ---------------------------------------------------------------------------


class TestResolveChannelId:
    async def test_finds_channel_by_name(self, client) -> None:
        from nf_core_bot.scheduler.oncall_jobs import _resolve_channel_id

        client.conversations_list.return_value = {
            "channels": [
                {"name": "general", "id": "C_GENERAL"},
                {"name": "core", "id": "C_CORE"},
            ],
            "response_metadata": {"next_cursor": ""},
        }

        result = await _resolve_channel_id(client)
        assert result == "C_CORE"

    async def test_paginates(self, client) -> None:
        from nf_core_bot.scheduler.oncall_jobs import _resolve_channel_id

        # First page: no match, has cursor
        # Second page: match
        client.conversations_list.side_effect = [
            {
                "channels": [{"name": "general", "id": "C_GENERAL"}],
                "response_metadata": {"next_cursor": "page2"},
            },
            {
                "channels": [{"name": "core", "id": "C_CORE"}],
                "response_metadata": {"next_cursor": ""},
            },
        ]

        result = await _resolve_channel_id(client)
        assert result == "C_CORE"
        assert client.conversations_list.await_count == 2

    async def test_returns_none_when_not_found(self, client) -> None:
        from nf_core_bot.scheduler.oncall_jobs import _resolve_channel_id

        client.conversations_list.return_value = {
            "channels": [{"name": "general", "id": "C_GENERAL"}],
            "response_metadata": {"next_cursor": ""},
        }

        result = await _resolve_channel_id(client)
        assert result is None

    async def test_caches_result(self, client) -> None:
        from nf_core_bot.scheduler.oncall_jobs import _resolve_channel_id

        client.conversations_list.return_value = {
            "channels": [{"name": "core", "id": "C_CORE"}],
            "response_metadata": {"next_cursor": ""},
        }

        # Call twice — API should only be hit once
        result1 = await _resolve_channel_id(client)
        result2 = await _resolve_channel_id(client)
        assert result1 == result2 == "C_CORE"
        assert client.conversations_list.await_count == 1

    async def test_handles_api_error(self, client) -> None:
        from nf_core_bot.scheduler.oncall_jobs import _resolve_channel_id

        client.conversations_list.side_effect = Exception("Slack API error")

        result = await _resolve_channel_id(client)
        assert result is None


# ---------------------------------------------------------------------------
# sync_oncall_topic
# ---------------------------------------------------------------------------


@patch("nf_core_bot.scheduler.oncall_jobs.current_week_start", return_value="2026-04-06")
@patch("nf_core_bot.scheduler.oncall_jobs._resolve_channel_id", new_callable=AsyncMock, return_value="C_CORE")
class TestSyncOncallTopic:
    async def test_sets_topic_when_different(self, _mock_ch, _mock_week, ddb_table, client) -> None:
        from nf_core_bot.db.oncall import put_roster_entry
        from nf_core_bot.scheduler.oncall_jobs import sync_oncall_topic

        await put_roster_entry("2026-04-06", "U111")
        client.conversations_info.return_value = {"channel": {"topic": {"value": "old topic"}}}

        await sync_oncall_topic(client)

        client.conversations_setTopic.assert_awaited_once_with(channel="C_CORE", topic="On call: <@U111>")

    async def test_skips_when_topic_matches(self, _mock_ch, _mock_week, ddb_table, client) -> None:
        from nf_core_bot.db.oncall import put_roster_entry
        from nf_core_bot.scheduler.oncall_jobs import sync_oncall_topic

        await put_roster_entry("2026-04-06", "U111")
        client.conversations_info.return_value = {"channel": {"topic": {"value": "On call: <@U111>"}}}

        await sync_oncall_topic(client)

        client.conversations_setTopic.assert_not_awaited()

    async def test_clears_topic_when_no_assignee(self, _mock_ch, _mock_week, ddb_table, client) -> None:
        from nf_core_bot.db.oncall import put_roster_entry
        from nf_core_bot.scheduler.oncall_jobs import sync_oncall_topic

        await put_roster_entry("2026-04-06", "")
        client.conversations_info.return_value = {"channel": {"topic": {"value": "On call: <@U_OLD>"}}}

        await sync_oncall_topic(client)

        client.conversations_setTopic.assert_awaited_once_with(channel="C_CORE", topic="")

    async def test_clears_topic_when_no_roster_entry(self, _mock_ch, _mock_week, ddb_table, client) -> None:
        from nf_core_bot.scheduler.oncall_jobs import sync_oncall_topic

        client.conversations_info.return_value = {"channel": {"topic": {"value": "On call: <@U_OLD>"}}}

        await sync_oncall_topic(client)

        client.conversations_setTopic.assert_awaited_once_with(channel="C_CORE", topic="")

    async def test_skips_when_topic_already_empty_and_unassigned(self, _mock_ch, _mock_week, ddb_table, client) -> None:
        from nf_core_bot.scheduler.oncall_jobs import sync_oncall_topic

        # No roster entry + topic already empty → no-op (don't spam channel)
        client.conversations_info.return_value = {"channel": {"topic": {"value": ""}}}

        await sync_oncall_topic(client)

        client.conversations_setTopic.assert_not_awaited()

    async def test_skips_set_when_info_fails(self, _mock_ch, _mock_week, ddb_table, client) -> None:
        from nf_core_bot.db.oncall import put_roster_entry
        from nf_core_bot.scheduler.oncall_jobs import sync_oncall_topic

        await put_roster_entry("2026-04-06", "U111")
        client.conversations_info.side_effect = Exception("missing scope")

        await sync_oncall_topic(client)

        client.conversations_setTopic.assert_not_awaited()

    async def test_swallows_set_topic_failure(self, _mock_ch, _mock_week, ddb_table, client) -> None:
        from nf_core_bot.db.oncall import put_roster_entry
        from nf_core_bot.scheduler.oncall_jobs import sync_oncall_topic

        await put_roster_entry("2026-04-06", "U111")
        client.conversations_info.return_value = {"channel": {"topic": {"value": ""}}}
        client.conversations_setTopic.side_effect = Exception("missing_scope")

        # Should not raise
        await sync_oncall_topic(client)

        client.conversations_setTopic.assert_awaited_once()


class TestSyncOncallTopicNoChannel:
    @patch("nf_core_bot.scheduler.oncall_jobs._resolve_channel_id", new_callable=AsyncMock, return_value=None)
    async def test_no_op_when_channel_not_resolved(self, _mock_ch, ddb_table, client) -> None:
        from nf_core_bot.scheduler.oncall_jobs import sync_oncall_topic

        await sync_oncall_topic(client)

        client.conversations_info.assert_not_awaited()
        client.conversations_setTopic.assert_not_awaited()
