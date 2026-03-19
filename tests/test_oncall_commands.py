"""Tests for on-call slash-command handlers."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest


@pytest.fixture
def respond() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def client() -> AsyncMock:
    return AsyncMock()


# ---------------------------------------------------------------------------
# on-call list
# ---------------------------------------------------------------------------


class TestOncallList:
    async def test_empty_schedule(self, ddb_table, respond) -> None:
        from nf_core_bot.commands.oncall.list_cmd import handle_oncall_list

        await handle_oncall_list(respond)

        respond.assert_awaited_once()
        assert "No on-call schedule" in respond.call_args[1]["text"]

    async def test_shows_schedule(self, ddb_table, respond) -> None:
        from nf_core_bot.commands.oncall.list_cmd import handle_oncall_list
        from nf_core_bot.db.oncall import put_roster_entry

        await put_roster_entry("2026-04-06", "U111")
        await put_roster_entry("2026-04-13", "U222")

        with patch("nf_core_bot.commands.oncall.list_cmd.current_week_start", return_value="2026-04-01"):
            await handle_oncall_list(respond)

        text = respond.call_args[1]["text"]
        assert "<@U111>" in text
        assert "<@U222>" in text
        assert "Apr 6" in text

    async def test_shows_swapped_status(self, ddb_table, respond) -> None:
        from nf_core_bot.commands.oncall.list_cmd import handle_oncall_list
        from nf_core_bot.db.oncall import put_roster_entry

        await put_roster_entry("2026-04-06", "U111", status="swapped")

        with patch("nf_core_bot.commands.oncall.list_cmd.current_week_start", return_value="2026-04-01"):
            await handle_oncall_list(respond)

        text = respond.call_args[1]["text"]
        assert "swapped" in text


# ---------------------------------------------------------------------------
# on-call me
# ---------------------------------------------------------------------------


class TestOncallMe:
    async def test_no_assignments(self, ddb_table, respond) -> None:
        from nf_core_bot.commands.oncall.me import handle_oncall_me

        with patch("nf_core_bot.commands.oncall.me.current_week_start", return_value="2026-04-01"):
            await handle_oncall_me(respond, "U999")

        assert "no upcoming" in respond.call_args[1]["text"].lower()

    async def test_shows_own_weeks(self, ddb_table, respond) -> None:
        from nf_core_bot.commands.oncall.me import handle_oncall_me
        from nf_core_bot.db.oncall import put_roster_entry

        await put_roster_entry("2026-04-06", "U111")
        await put_roster_entry("2026-04-13", "U222")
        await put_roster_entry("2026-04-20", "U111")

        with patch("nf_core_bot.commands.oncall.me.current_week_start", return_value="2026-04-01"):
            await handle_oncall_me(respond, "U111")

        text = respond.call_args[1]["text"]
        assert "Apr 6" in text
        assert "Apr 20" in text
        # U222's week should not appear
        assert "Apr 13" not in text


# ---------------------------------------------------------------------------
# on-call switch
# ---------------------------------------------------------------------------


class TestOncallSwitch:
    async def test_no_schedule(self, ddb_table, respond, client) -> None:
        from nf_core_bot.commands.oncall.switch import handle_oncall_switch

        with patch("nf_core_bot.commands.oncall.switch.current_week_start", return_value="2026-04-01"):
            await handle_oncall_switch(respond, client, "U111", [])

        assert "No on-call schedule" in respond.call_args[1]["text"]

    async def test_caller_not_assigned(self, ddb_table, respond, client) -> None:
        from nf_core_bot.commands.oncall.switch import handle_oncall_switch
        from nf_core_bot.db.oncall import put_roster_entry

        await put_roster_entry("2026-04-06", "U222")

        with patch("nf_core_bot.commands.oncall.switch.current_week_start", return_value="2026-04-01"):
            await handle_oncall_switch(respond, client, "U999", [])

        assert "don't have an upcoming" in respond.call_args[1]["text"]

    async def test_swap_with_next_week(self, ddb_table, respond, client) -> None:
        from nf_core_bot.commands.oncall.switch import handle_oncall_switch
        from nf_core_bot.db.oncall import get_roster_entry, put_roster_entry

        await put_roster_entry("2026-04-06", "U111")
        await put_roster_entry("2026-04-13", "U222")

        with patch("nf_core_bot.commands.oncall.switch.current_week_start", return_value="2026-04-01"):
            await handle_oncall_switch(respond, client, "U111", [])

        # Verify the swap happened
        entry1 = await get_roster_entry("2026-04-06")
        entry2 = await get_roster_entry("2026-04-13")
        assert entry1 is not None
        assert entry2 is not None
        assert entry1["assigned_user_id"] == "U222"
        assert entry2["assigned_user_id"] == "U111"

        # Both should be DM'd
        assert client.chat_postMessage.await_count == 2

    async def test_swap_with_specific_date(self, ddb_table, respond, client) -> None:
        from nf_core_bot.commands.oncall.switch import handle_oncall_switch
        from nf_core_bot.db.oncall import get_roster_entry, put_roster_entry

        await put_roster_entry("2026-04-06", "U111")
        await put_roster_entry("2026-04-13", "U222")
        await put_roster_entry("2026-04-20", "U333")

        # Swap U111's week with the week containing Apr 22 (which is in the Apr 20 week)
        with patch("nf_core_bot.commands.oncall.switch.current_week_start", return_value="2026-04-01"):
            await handle_oncall_switch(respond, client, "U111", ["2026-04-22"])

        entry1 = await get_roster_entry("2026-04-06")
        entry3 = await get_roster_entry("2026-04-20")
        assert entry1 is not None
        assert entry3 is not None
        assert entry1["assigned_user_id"] == "U333"
        assert entry3["assigned_user_id"] == "U111"

    async def test_swap_with_self_rejected(self, ddb_table, respond, client) -> None:
        from nf_core_bot.commands.oncall.switch import handle_oncall_switch
        from nf_core_bot.db.oncall import put_roster_entry

        await put_roster_entry("2026-04-06", "U111")
        await put_roster_entry("2026-04-13", "U111")

        with patch("nf_core_bot.commands.oncall.switch.current_week_start", return_value="2026-04-01"):
            await handle_oncall_switch(respond, client, "U111", [])

        assert "can't swap with yourself" in respond.call_args[1]["text"].lower()

    async def test_invalid_date(self, ddb_table, respond, client) -> None:
        from nf_core_bot.commands.oncall.switch import handle_oncall_switch
        from nf_core_bot.db.oncall import put_roster_entry

        await put_roster_entry("2026-04-06", "U111")

        with patch("nf_core_bot.commands.oncall.switch.current_week_start", return_value="2026-04-01"):
            await handle_oncall_switch(respond, client, "U111", ["not-a-date"])

        assert "not a valid date" in respond.call_args[1]["text"].lower()

    async def test_no_week_after(self, ddb_table, respond, client) -> None:
        from nf_core_bot.commands.oncall.switch import handle_oncall_switch
        from nf_core_bot.db.oncall import put_roster_entry

        # Only one week in the schedule
        await put_roster_entry("2026-04-06", "U111")

        with patch("nf_core_bot.commands.oncall.switch.current_week_start", return_value="2026-04-01"):
            await handle_oncall_switch(respond, client, "U111", [])

        assert "no week after" in respond.call_args[1]["text"].lower()


# ---------------------------------------------------------------------------
# on-call skip
# ---------------------------------------------------------------------------


class TestOncallSkip:
    async def test_no_schedule(self, ddb_table, respond, client) -> None:
        from nf_core_bot.commands.oncall.skip import handle_oncall_skip

        with patch("nf_core_bot.commands.oncall.skip.current_week_start", return_value="2026-04-01"):
            await handle_oncall_skip(respond, client, "U111")

        assert "No on-call schedule" in respond.call_args[1]["text"]

    async def test_caller_not_assigned(self, ddb_table, respond, client) -> None:
        from nf_core_bot.commands.oncall.skip import handle_oncall_skip
        from nf_core_bot.db.oncall import put_roster_entry

        await put_roster_entry("2026-04-06", "U222")

        with patch("nf_core_bot.commands.oncall.skip.current_week_start", return_value="2026-04-01"):
            await handle_oncall_skip(respond, client, "U999")

        assert "don't have an upcoming" in respond.call_args[1]["text"]

    @patch("nf_core_bot.commands.oncall.skip.refresh_core_team", new_callable=AsyncMock)
    async def test_successful_skip(self, mock_refresh, ddb_table, respond, client) -> None:
        from nf_core_bot.commands.oncall.skip import handle_oncall_skip
        from nf_core_bot.db.oncall import get_roster_entry, get_round_robin_state, put_roster_entry

        mock_refresh.return_value = {"U111", "U222", "U333"}

        await put_roster_entry("2026-04-06", "U111")
        await put_roster_entry("2026-04-13", "U222")

        with patch("nf_core_bot.commands.oncall.skip.current_week_start", return_value="2026-04-01"):
            await handle_oncall_skip(respond, client, "U111")

        # U333 should be assigned (only unassigned member)
        entry = await get_roster_entry("2026-04-06")
        assert entry is not None
        assert entry["assigned_user_id"] == "U333"
        assert entry["status"] == "skipped"

        # U111 should be in queue_front
        state = await get_round_robin_state()
        assert "U111" in state["queue_front"]

        # Both parties should be DM'd
        assert client.chat_postMessage.await_count == 2

    @patch("nf_core_bot.commands.oncall.skip.refresh_core_team", new_callable=AsyncMock)
    async def test_no_replacement_available(self, mock_refresh, ddb_table, respond, client) -> None:
        from nf_core_bot.commands.oncall.skip import handle_oncall_skip
        from nf_core_bot.db.oncall import put_roster_entry

        # All core-team members are assigned
        mock_refresh.return_value = {"U111", "U222"}

        await put_roster_entry("2026-04-06", "U111")
        await put_roster_entry("2026-04-13", "U222")

        with patch("nf_core_bot.commands.oncall.skip.current_week_start", return_value="2026-04-01"):
            await handle_oncall_skip(respond, client, "U111")

        assert "no one is available" in respond.call_args[1]["text"].lower()

    @patch("nf_core_bot.commands.oncall.skip.refresh_core_team", new_callable=AsyncMock)
    async def test_skip_respects_queue_front(self, mock_refresh, ddb_table, respond, client) -> None:
        from nf_core_bot.commands.oncall.skip import handle_oncall_skip
        from nf_core_bot.db.oncall import get_roster_entry, put_roster_entry, save_round_robin_state

        mock_refresh.return_value = {"U111", "U222", "U333", "U444"}

        # U333 previously skipped and is in queue_front
        await save_round_robin_state(
            {"last_assigned": {"U333": "2026-03-01", "U444": "2026-01-01"}, "queue_front": ["U333"]}
        )

        await put_roster_entry("2026-04-06", "U111")
        await put_roster_entry("2026-04-13", "U222")

        with patch("nf_core_bot.commands.oncall.skip.current_week_start", return_value="2026-04-01"):
            await handle_oncall_skip(respond, client, "U111")

        # U333 should be picked (queue_front priority) even though U444 was assigned longer ago
        entry = await get_roster_entry("2026-04-06")
        assert entry is not None
        assert entry["assigned_user_id"] == "U333"


# ---------------------------------------------------------------------------
# on-call unavailable
# ---------------------------------------------------------------------------


class TestOncallUnavailable:
    async def test_missing_args(self, ddb_table, respond, client) -> None:
        from nf_core_bot.commands.oncall.unavailable import handle_oncall_unavailable

        await handle_oncall_unavailable(respond, client, "U111", [])
        assert "Usage" in respond.call_args[1]["text"]

    async def test_invalid_dates(self, ddb_table, respond, client) -> None:
        from nf_core_bot.commands.oncall.unavailable import handle_oncall_unavailable

        await handle_oncall_unavailable(respond, client, "U111", ["bad", "dates"])
        assert "not a valid date" in respond.call_args[1]["text"].lower()

    async def test_end_before_start(self, ddb_table, respond, client) -> None:
        from nf_core_bot.commands.oncall.unavailable import handle_oncall_unavailable

        await handle_oncall_unavailable(respond, client, "U111", ["2026-04-20", "2026-04-06"])
        assert "on or after" in respond.call_args[1]["text"].lower()

    async def test_past_dates_rejected(self, ddb_table, respond, client) -> None:
        from nf_core_bot.commands.oncall.unavailable import handle_oncall_unavailable

        await handle_oncall_unavailable(respond, client, "U111", ["2020-01-01", "2020-01-15"])
        assert "past" in respond.call_args[1]["text"].lower()

    async def test_stores_unavailability(self, ddb_table, respond, client) -> None:
        from nf_core_bot.commands.oncall.unavailable import handle_oncall_unavailable
        from nf_core_bot.db.oncall import list_unavailability

        with patch("nf_core_bot.commands.oncall.unavailable.current_week_start", return_value="2026-04-01"):
            await handle_oncall_unavailable(respond, client, "U111", ["2026-05-01", "2026-05-15"])

        entries = await list_unavailability("U111")
        assert len(entries) == 1
        assert entries[0]["start_date"] == "2026-05-01"
        assert entries[0]["end_date"] == "2026-05-15"

        assert "unavailable" in respond.call_args[1]["text"].lower()

    @patch("nf_core_bot.commands.oncall.unavailable.find_skip_replacement", new_callable=AsyncMock)
    async def test_auto_skips_overlapping_assignment(self, mock_find, ddb_table, respond, client) -> None:
        from nf_core_bot.commands.oncall.unavailable import handle_oncall_unavailable
        from nf_core_bot.db.oncall import get_roster_entry, put_roster_entry

        mock_find.return_value = "U333"

        await put_roster_entry("2026-04-06", "U111")

        with patch("nf_core_bot.commands.oncall.unavailable.current_week_start", return_value="2026-04-01"):
            await handle_oncall_unavailable(respond, client, "U111", ["2026-04-05", "2026-04-12"])

        # The overlapping week should be reassigned
        entry = await get_roster_entry("2026-04-06")
        assert entry is not None
        assert entry["assigned_user_id"] == "U333"
        assert entry["status"] == "skipped"

    @patch("nf_core_bot.commands.oncall.unavailable.find_skip_replacement", new_callable=AsyncMock)
    async def test_warns_when_no_replacement(self, mock_find, ddb_table, respond, client) -> None:
        from nf_core_bot.commands.oncall.unavailable import handle_oncall_unavailable
        from nf_core_bot.db.oncall import put_roster_entry

        mock_find.return_value = None

        await put_roster_entry("2026-04-06", "U111")

        with patch("nf_core_bot.commands.oncall.unavailable.current_week_start", return_value="2026-04-01"):
            await handle_oncall_unavailable(respond, client, "U111", ["2026-04-05", "2026-04-12"])

        text = respond.call_args[1]["text"]
        assert "no replacement" in text.lower()


# ---------------------------------------------------------------------------
# on-call reboot
# ---------------------------------------------------------------------------


class TestOncallReboot:
    @patch("nf_core_bot.commands.oncall.reboot._maybe_extend_roster", new_callable=AsyncMock)
    async def test_wipes_and_rebuilds(self, mock_extend, ddb_table, respond, client) -> None:
        from nf_core_bot.commands.oncall.reboot import handle_oncall_reboot
        from nf_core_bot.db.oncall import get_round_robin_state, list_roster, put_roster_entry, save_round_robin_state

        # Seed existing data
        await put_roster_entry("2026-04-06", "U111")
        await put_roster_entry("2026-04-13", "U222")
        await save_round_robin_state({"last_assigned": {"U111": "2026-04-06"}, "queue_front": ["U333"]})

        await handle_oncall_reboot(respond, client, "U111")

        # Old entries should be gone
        roster = await list_roster()
        assert len(roster) == 0  # extend is mocked, so nothing created

        # Round-robin should be reset
        state = await get_round_robin_state()
        assert state == {"last_assigned": {}, "queue_front": []}

        # _maybe_extend_roster should have been called
        mock_extend.assert_awaited_once_with(client)

        # User should get confirmation
        text = respond.call_args[1]["text"]
        assert "rebooted" in text.lower()
        assert "Deleted 2" in text

    @patch("nf_core_bot.commands.oncall.reboot._maybe_extend_roster", new_callable=AsyncMock)
    async def test_reboot_with_empty_schedule(self, mock_extend, ddb_table, respond, client) -> None:
        from nf_core_bot.commands.oncall.reboot import handle_oncall_reboot

        await handle_oncall_reboot(respond, client, "U111")

        mock_extend.assert_awaited_once()
        text = respond.call_args[1]["text"]
        assert "Deleted 0" in text


# ---------------------------------------------------------------------------
# Router integration
# ---------------------------------------------------------------------------


class TestOncallRouterIntegration:
    """Verify /nf-core on-call routes to the correct handler.

    All on-call commands require ``@core-team`` membership; the router
    calls ``is_core_team`` before dispatching. We mock it to return True
    for these tests.
    """

    @pytest.fixture(autouse=True)
    def _mock_core_team(self, monkeypatch) -> None:
        """All router tests assume the caller is a core-team member."""
        from nf_core_bot.commands import router as router_mod

        monkeypatch.setattr(router_mod, "is_core_team", AsyncMock(return_value=True))

    @pytest.fixture
    def ack(self) -> AsyncMock:
        return AsyncMock()

    async def test_oncall_list_routes(self, monkeypatch, ack, respond, client) -> None:
        from nf_core_bot.commands import router as router_mod
        from nf_core_bot.commands.router import dispatch

        mock = AsyncMock()
        monkeypatch.setitem(router_mod._ONCALL_DISPATCH, "list", mock)

        command = {"text": "on-call list", "user_id": "U111", "trigger_id": "T111"}
        await dispatch(ack, respond, client, command)

        mock.assert_awaited_once()
        args = mock.call_args[0]
        assert len(args) == 1  # (respond,)

    async def test_oncall_me_routes(self, monkeypatch, ack, respond, client) -> None:
        from nf_core_bot.commands import router as router_mod
        from nf_core_bot.commands.router import dispatch

        mock = AsyncMock()
        monkeypatch.setitem(router_mod._ONCALL_DISPATCH, "me", mock)

        command = {"text": "on-call me", "user_id": "U111", "trigger_id": "T111"}
        await dispatch(ack, respond, client, command)

        mock.assert_awaited_once()
        args = mock.call_args[0]
        assert len(args) == 2  # (respond, user_id)

    async def test_oncall_switch_routes(self, monkeypatch, ack, respond, client) -> None:
        from nf_core_bot.commands import router as router_mod
        from nf_core_bot.commands.router import dispatch

        mock = AsyncMock()
        monkeypatch.setitem(router_mod._ONCALL_DISPATCH, "switch", mock)

        command = {"text": "on-call switch 2026-04-20", "user_id": "U111", "trigger_id": "T111"}
        await dispatch(ack, respond, client, command)

        mock.assert_awaited_once()
        args = mock.call_args[0]
        assert len(args) == 4  # (respond, client, user_id, rest)
        assert args[3] == ["2026-04-20"]

    async def test_oncall_skip_routes(self, monkeypatch, ack, respond, client) -> None:
        from nf_core_bot.commands import router as router_mod
        from nf_core_bot.commands.router import dispatch

        mock = AsyncMock()
        monkeypatch.setitem(router_mod._ONCALL_DISPATCH, "skip", mock)

        command = {"text": "on-call skip", "user_id": "U111", "trigger_id": "T111"}
        await dispatch(ack, respond, client, command)

        mock.assert_awaited_once()
        args = mock.call_args[0]
        assert len(args) == 3  # (respond, client, user_id)

    async def test_oncall_reboot_routes(self, monkeypatch, ack, respond, client) -> None:
        from nf_core_bot.commands import router as router_mod
        from nf_core_bot.commands.router import dispatch

        mock = AsyncMock()
        monkeypatch.setitem(router_mod._ONCALL_DISPATCH, "reboot", mock)

        command = {"text": "on-call reboot", "user_id": "U111", "trigger_id": "T111"}
        await dispatch(ack, respond, client, command)

        mock.assert_awaited_once()
        args = mock.call_args[0]
        assert len(args) == 3  # (respond, client, user_id)

    async def test_oncall_unavailable_routes(self, monkeypatch, ack, respond, client) -> None:
        from nf_core_bot.commands import router as router_mod
        from nf_core_bot.commands.router import dispatch

        mock = AsyncMock()
        monkeypatch.setitem(router_mod._ONCALL_DISPATCH, "unavailable", mock)

        command = {"text": "on-call unavailable 2026-04-01 2026-04-15", "user_id": "U111", "trigger_id": "T111"}
        await dispatch(ack, respond, client, command)

        mock.assert_awaited_once()
        args = mock.call_args[0]
        assert len(args) == 4  # (respond, client, user_id, rest)
        assert args[3] == ["2026-04-01", "2026-04-15"]

    async def test_oncall_help_routes(self, monkeypatch, ack, respond, client) -> None:
        from nf_core_bot.commands import router as router_mod
        from nf_core_bot.commands.router import dispatch

        mock = AsyncMock()
        monkeypatch.setattr(router_mod, "handle_oncall_help", mock)

        command = {"text": "on-call help", "user_id": "U111", "trigger_id": "T111"}
        await dispatch(ack, respond, client, command)

        mock.assert_awaited_once()

    async def test_oncall_unknown_subcommand(self, ack, respond, client) -> None:
        from nf_core_bot.commands.router import dispatch

        command = {"text": "on-call bogus", "user_id": "U111", "trigger_id": "T111"}
        await dispatch(ack, respond, client, command)

        ack.assert_awaited_once()
        assert "Unknown on-call command" in respond.call_args[0][0]

    async def test_non_core_team_rejected(self, monkeypatch, respond, client) -> None:
        """Non-core-team members should be rejected by the router."""
        from nf_core_bot.commands import router as router_mod
        from nf_core_bot.commands.router import dispatch

        # Override the autouse mock to return False
        monkeypatch.setattr(router_mod, "is_core_team", AsyncMock(return_value=False))

        ack = AsyncMock()
        command = {"text": "on-call list", "user_id": "U999", "trigger_id": "T111"}
        await dispatch(ack, respond, client, command)

        ack.assert_awaited_once()
        assert "restricted" in respond.call_args[0][0].lower()
