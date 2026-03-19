"""Tests for the DynamoDB on-call data-access layer."""

from __future__ import annotations

import pytest

# ---------------------------------------------------------------------------
# Roster CRUD
# ---------------------------------------------------------------------------


class TestPutRosterEntry:
    async def test_creates_entry(self, ddb_table) -> None:
        from nf_core_bot.db.oncall import get_roster_entry, put_roster_entry

        await put_roster_entry("2026-04-06", "U111")
        item = await get_roster_entry("2026-04-06")
        assert item is not None
        assert item["assigned_user_id"] == "U111"
        assert item["status"] == "scheduled"
        assert item["week_start"] == "2026-04-06"
        assert "created_at" in item

    async def test_duplicate_raises(self, ddb_table) -> None:
        from nf_core_bot.db.oncall import put_roster_entry

        await put_roster_entry("2026-04-06", "U111")
        with pytest.raises(ValueError, match="already exists"):
            await put_roster_entry("2026-04-06", "U222")

    async def test_custom_status(self, ddb_table) -> None:
        from nf_core_bot.db.oncall import get_roster_entry, put_roster_entry

        await put_roster_entry("2026-04-13", "U111", status="swapped")
        item = await get_roster_entry("2026-04-13")
        assert item is not None
        assert item["status"] == "swapped"


class TestGetRosterEntry:
    async def test_returns_none_when_missing(self, ddb_table) -> None:
        from nf_core_bot.db.oncall import get_roster_entry

        assert await get_roster_entry("2099-01-01") is None


class TestUpdateRosterAssignment:
    async def test_updates_existing_entry(self, ddb_table) -> None:
        from nf_core_bot.db.oncall import get_roster_entry, put_roster_entry, update_roster_assignment

        await put_roster_entry("2026-04-06", "U111")
        await update_roster_assignment("2026-04-06", "U222", "swapped")

        item = await get_roster_entry("2026-04-06")
        assert item is not None
        assert item["assigned_user_id"] == "U222"
        assert item["status"] == "swapped"
        assert "updated_at" in item

    async def test_missing_entry_raises(self, ddb_table) -> None:
        from nf_core_bot.db.oncall import update_roster_assignment

        with pytest.raises(ValueError, match="does not exist"):
            await update_roster_assignment("2099-01-01", "U111", "scheduled")


class TestListRoster:
    async def test_returns_all_sorted(self, ddb_table) -> None:
        from nf_core_bot.db.oncall import list_roster, put_roster_entry

        await put_roster_entry("2026-04-20", "U333")
        await put_roster_entry("2026-04-06", "U111")
        await put_roster_entry("2026-04-13", "U222")

        items = await list_roster()
        assert len(items) == 3
        assert [i["week_start"] for i in items] == ["2026-04-06", "2026-04-13", "2026-04-20"]

    async def test_from_date_filters(self, ddb_table) -> None:
        from nf_core_bot.db.oncall import list_roster, put_roster_entry

        await put_roster_entry("2026-04-06", "U111")
        await put_roster_entry("2026-04-13", "U222")
        await put_roster_entry("2026-04-20", "U333")

        items = await list_roster(from_date="2026-04-13")
        assert len(items) == 2
        assert items[0]["week_start"] == "2026-04-13"

    async def test_empty_table(self, ddb_table) -> None:
        from nf_core_bot.db.oncall import list_roster

        assert await list_roster() == []


class TestDeleteRosterEntry:
    async def test_deletes_existing(self, ddb_table) -> None:
        from nf_core_bot.db.oncall import delete_roster_entry, get_roster_entry, put_roster_entry

        await put_roster_entry("2026-04-06", "U111")
        await delete_roster_entry("2026-04-06")
        assert await get_roster_entry("2026-04-06") is None

    async def test_delete_nonexistent_does_not_raise(self, ddb_table) -> None:
        from nf_core_bot.db.oncall import delete_roster_entry

        # DynamoDB delete_item is idempotent
        await delete_roster_entry("2099-01-01")


# ---------------------------------------------------------------------------
# Round-robin state
# ---------------------------------------------------------------------------


class TestRoundRobinState:
    async def test_default_state_when_empty(self, ddb_table) -> None:
        from nf_core_bot.db.oncall import get_round_robin_state

        state = await get_round_robin_state()
        assert state == {"last_assigned": {}, "queue_front": []}

    async def test_save_and_retrieve(self, ddb_table) -> None:
        from nf_core_bot.db.oncall import get_round_robin_state, save_round_robin_state

        state = {
            "last_assigned": {"U111": "2026-04-06", "U222": "2026-04-13"},
            "queue_front": ["U333"],
        }
        await save_round_robin_state(state)

        loaded = await get_round_robin_state()
        assert loaded["last_assigned"] == {"U111": "2026-04-06", "U222": "2026-04-13"}
        assert loaded["queue_front"] == ["U333"]

    async def test_overwrite(self, ddb_table) -> None:
        from nf_core_bot.db.oncall import get_round_robin_state, save_round_robin_state

        await save_round_robin_state({"last_assigned": {"U111": "2026-01-01"}, "queue_front": []})
        await save_round_robin_state({"last_assigned": {"U222": "2026-02-02"}, "queue_front": ["U333"]})

        loaded = await get_round_robin_state()
        assert "U111" not in loaded["last_assigned"]
        assert loaded["last_assigned"]["U222"] == "2026-02-02"


# ---------------------------------------------------------------------------
# Unavailability
# ---------------------------------------------------------------------------


class TestUnavailability:
    async def test_add_and_list(self, ddb_table) -> None:
        from nf_core_bot.db.oncall import add_unavailability, list_unavailability

        await add_unavailability("U111", "2026-04-06", "2026-04-12")
        await add_unavailability("U111", "2026-05-01", "2026-05-15")

        entries = await list_unavailability("U111")
        assert len(entries) == 2
        dates = {(e["start_date"], e["end_date"]) for e in entries}
        assert ("2026-04-06", "2026-04-12") in dates
        assert ("2026-05-01", "2026-05-15") in dates

    async def test_list_empty(self, ddb_table) -> None:
        from nf_core_bot.db.oncall import list_unavailability

        assert await list_unavailability("U999") == []

    async def test_remove(self, ddb_table) -> None:
        from nf_core_bot.db.oncall import add_unavailability, list_unavailability, remove_unavailability

        await add_unavailability("U111", "2026-04-06", "2026-04-12")
        await remove_unavailability("U111", "2026-04-06", "2026-04-12")
        assert await list_unavailability("U111") == []


class TestIsUserUnavailable:
    async def test_unavailable_when_range_overlaps(self, ddb_table) -> None:
        from nf_core_bot.db.oncall import add_unavailability, is_user_unavailable

        # Unavailable Apr 8–10; week of Apr 6–12 overlaps
        await add_unavailability("U111", "2026-04-08", "2026-04-10")
        assert await is_user_unavailable("U111", "2026-04-06") is True

    async def test_available_when_no_overlap(self, ddb_table) -> None:
        from nf_core_bot.db.oncall import add_unavailability, is_user_unavailable

        # Unavailable Apr 1–5; week of Apr 6–12 does not overlap
        await add_unavailability("U111", "2026-04-01", "2026-04-05")
        assert await is_user_unavailable("U111", "2026-04-06") is False

    async def test_available_when_no_entries(self, ddb_table) -> None:
        from nf_core_bot.db.oncall import is_user_unavailable

        assert await is_user_unavailable("U999", "2026-04-06") is False

    async def test_unavailable_when_range_covers_entire_week(self, ddb_table) -> None:
        from nf_core_bot.db.oncall import add_unavailability, is_user_unavailable

        await add_unavailability("U111", "2026-04-01", "2026-04-30")
        assert await is_user_unavailable("U111", "2026-04-06") is True

    async def test_unavailable_when_range_starts_on_last_day(self, ddb_table) -> None:
        from nf_core_bot.db.oncall import add_unavailability, is_user_unavailable

        # Unavailable starts Sun Apr 12, which is the last day of the Apr 6 week
        await add_unavailability("U111", "2026-04-12", "2026-04-15")
        assert await is_user_unavailable("U111", "2026-04-06") is True


class TestGetAllUnavailableUsers:
    async def test_finds_multiple_users(self, ddb_table) -> None:
        from nf_core_bot.db.oncall import add_unavailability, get_all_unavailable_users

        await add_unavailability("U111", "2026-04-06", "2026-04-12")
        await add_unavailability("U222", "2026-04-08", "2026-04-10")
        await add_unavailability("U333", "2026-05-01", "2026-05-07")  # different week

        unavail = await get_all_unavailable_users("2026-04-06")
        assert unavail == {"U111", "U222"}

    async def test_empty_when_none_unavailable(self, ddb_table) -> None:
        from nf_core_bot.db.oncall import get_all_unavailable_users

        assert await get_all_unavailable_users("2026-04-06") == set()


# ---------------------------------------------------------------------------
# Reminder tracking
# ---------------------------------------------------------------------------


class TestReminderTracking:
    async def test_default_tracking(self, ddb_table) -> None:
        from nf_core_bot.db.oncall import get_reminder_tracking

        tracking = await get_reminder_tracking("2026-04-06")
        assert tracking == {
            "assignment_sent": False,
            "week_before_sent": False,
            "daily_sent": [],
            "announcement_sent": False,
        }

    async def test_save_and_retrieve(self, ddb_table) -> None:
        from nf_core_bot.db.oncall import get_reminder_tracking, save_reminder_tracking

        data = {
            "assignment_sent": True,
            "week_before_sent": True,
            "daily_sent": ["2026-04-06", "2026-04-07"],
            "announcement_sent": True,
        }
        await save_reminder_tracking("2026-04-06", data)

        loaded = await get_reminder_tracking("2026-04-06")
        assert loaded["assignment_sent"] is True
        assert loaded["week_before_sent"] is True
        assert loaded["daily_sent"] == ["2026-04-06", "2026-04-07"]
        assert loaded["announcement_sent"] is True
