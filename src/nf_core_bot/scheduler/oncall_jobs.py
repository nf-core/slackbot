"""Background jobs for on-call rotation management.

Launched as an ``asyncio.Task`` from ``app.py`` at startup.  The main loop
wakes every 60 seconds and checks whether any scheduled job needs to run.
"""

from __future__ import annotations

import asyncio
import contextlib
import datetime
import logging
from typing import TYPE_CHECKING, Any

from nf_core_bot import config
from nf_core_bot.commands.oncall.helpers import format_week_range, monday_of_week
from nf_core_bot.db.oncall import (
    delete_roster_entry,
    get_all_unavailable_users,
    get_reminder_tracking,
    get_round_robin_state,
    list_roster,
    put_roster_entry,
    save_reminder_tracking,
    save_round_robin_state,
    update_roster_assignment,
)
from nf_core_bot.permissions.checks import refresh_core_team

if TYPE_CHECKING:
    from slack_sdk.web.async_client import AsyncWebClient

logger = logging.getLogger(__name__)

# How many weeks ahead the schedule should extend.
SCHEDULE_WEEKS_AHEAD = 8

# How many weeks in the past to keep before cleanup.
CLEANUP_KEEP_WEEKS = 4

# Interval between scheduler loop iterations (seconds).
LOOP_INTERVAL = 60

# Target hour (UTC) for weekly announcements, roster extension, and
# the one-week-ahead reminder.  Daily on-call reminders use the user's
# own Slack timezone instead.
TARGET_HOUR_UTC = 8


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


async def run_oncall_scheduler(client: AsyncWebClient) -> None:
    """Long-running loop that drives all on-call scheduled jobs.

    *client* is the Slack ``AsyncWebClient`` used to send messages and
    look up user profiles.
    """
    logger.info("on-call scheduler started")
    while True:
        try:
            await _tick(client)
        except Exception:
            logger.exception("on-call scheduler tick failed")
        await asyncio.sleep(LOOP_INTERVAL)


# ---------------------------------------------------------------------------
# Scheduler tick — runs every LOOP_INTERVAL seconds
# ---------------------------------------------------------------------------

# Tracks the last Monday date on which the weekly jobs actually ran,
# preventing them from firing more than once per week.
_last_weekly_run: str | None = None


async def _tick(client: AsyncWebClient) -> None:
    """Single iteration of the scheduler loop."""
    global _last_weekly_run  # noqa: PLW0603

    now_utc = datetime.datetime.now(datetime.UTC)
    today_str = now_utc.date().isoformat()

    # ── Weekly jobs (once per Monday at TARGET_HOUR_UTC) ─────────────
    today = now_utc.date()
    is_monday_morning = now_utc.weekday() == 0 and now_utc.hour == TARGET_HOUR_UTC
    if is_monday_morning and _last_weekly_run != today_str:
        await _maybe_extend_roster(client, today)
        await _cleanup_old_entries(today)
        _last_weekly_run = today_str

    # ── Reminders ────────────────────────────────────────────────────
    await _process_reminders(client, now_utc)


# ---------------------------------------------------------------------------
# Roster extension
# ---------------------------------------------------------------------------


async def _maybe_extend_roster(client: AsyncWebClient, today: datetime.date | None = None) -> None:
    """Ensure the schedule extends ~SCHEDULE_WEEKS_AHEAD into the future.

    Also handles members who left ``@core-team`` by reassigning their
    future weeks.
    """
    if today is None:
        today = datetime.date.today()
    this_monday = monday_of_week(today)

    members = await refresh_core_team(client, config.CORE_TEAM_USERGROUP_HANDLE or "core-team")
    if not members:
        logger.warning("Could not fetch @core-team members — skipping roster extension")
        return

    roster = await list_roster(from_date=this_monday.isoformat())
    rr_state = await get_round_robin_state()

    # --- Reassign weeks for people who left core-team ---
    for entry in roster:
        uid = entry.get("assigned_user_id")
        if uid and uid not in members and entry["status"] == "scheduled":
            week = entry["week_start"]
            replacement = await _pick_next_person(members, roster, rr_state, week)
            if replacement:
                await update_roster_assignment(week, replacement, "scheduled")
                entry["assigned_user_id"] = replacement
                rr_state["last_assigned"][replacement] = week
                logger.info("Reassigned week %s from departed %s to %s", week, uid, replacement)
            else:
                await update_roster_assignment(week, "", "scheduled")
                entry["assigned_user_id"] = ""
                logger.warning("No replacement for week %s after %s departed", week, uid)

    # --- Extend schedule ---
    existing_weeks = {e["week_start"] for e in roster}
    target_monday = this_monday + datetime.timedelta(weeks=SCHEDULE_WEEKS_AHEAD)

    week_cursor = this_monday
    while week_cursor < target_monday:
        week_str = week_cursor.isoformat()
        if week_str not in existing_weeks:
            assignee = await _pick_next_person(members, roster, rr_state, week_str)
            if assignee:
                await put_roster_entry(week_str, assignee)
                rr_state["last_assigned"][assignee] = week_str
                # Add a synthetic entry so subsequent iterations see it
                roster.append({"week_start": week_str, "assigned_user_id": assignee, "status": "scheduled"})
                logger.info("Scheduled %s for week %s", assignee, week_str)

                # Send assignment DM
                tracking = await get_reminder_tracking(week_str)
                if not tracking["assignment_sent"]:
                    await _send_assignment_dm(client, assignee, week_str)
                    tracking["assignment_sent"] = True
                    await save_reminder_tracking(week_str, tracking)
            else:
                # Nobody available — create entry with empty assignment
                with contextlib.suppress(ValueError):
                    await put_roster_entry(week_str, "")
                roster.append({"week_start": week_str, "assigned_user_id": "", "status": "scheduled"})
                logger.warning("No one available for week %s — left unassigned", week_str)
                await _warn_unassigned(client, week_str)
        week_cursor += datetime.timedelta(weeks=1)

    # Remove departed users from queue_front
    rr_state["queue_front"] = [u for u in rr_state.get("queue_front", []) if u in members]

    await save_round_robin_state(rr_state)


async def _pick_next_person(
    members: set[str],
    roster: list[dict[str, Any]],
    rr_state: dict[str, Any],
    week_start: str,
) -> str | None:
    """Select the next person for *week_start* using the round-robin algorithm.

    Priority order:
    1. People in ``queue_front`` (who previously skipped).
    2. People who have gone longest without being on-call.
    3. People who have never been on-call.

    Excludes anyone already assigned in the current roster window or
    unavailable for the target week.
    """
    assigned_users = {e["assigned_user_id"] for e in roster if e.get("assigned_user_id")}
    unavailable = await get_all_unavailable_users(week_start)
    candidates = members - assigned_users - unavailable

    if not candidates:
        # All members are already in the schedule — allow re-picking
        # (round-robin naturally cycles through the pool).
        candidates = members - unavailable
        if not candidates:
            return None

    queue_front: list[str] = rr_state.get("queue_front", [])
    last_assigned: dict[str, str] = rr_state.get("last_assigned", {})

    # 1. Try queue_front (people who skipped)
    for uid in queue_front:
        if uid in candidates:
            queue_front.remove(uid)
            return uid

    # 2. Sort by last-assigned date ascending (oldest first, never-assigned first)
    def _sort_key(uid: str) -> str:
        return last_assigned.get(uid, "0000-00-00")

    ordered = sorted(candidates, key=_sort_key)
    return ordered[0] if ordered else None


# ---------------------------------------------------------------------------
# Reminders
# ---------------------------------------------------------------------------


async def _process_reminders(client: AsyncWebClient, now_utc: datetime.datetime) -> None:
    """Check and send any pending reminders."""
    today = now_utc.date()
    this_monday = monday_of_week(today)
    roster = await list_roster(from_date=this_monday.isoformat())

    for entry in roster:
        user_id = entry.get("assigned_user_id")
        if not user_id:
            continue

        week_start = entry["week_start"]
        week_date = datetime.date.fromisoformat(week_start)
        one_week_before = week_date - datetime.timedelta(weeks=1)
        week_end = week_date + datetime.timedelta(days=6)

        # Quick date check: skip entries that cannot trigger any action today
        is_announcement_day = today == week_date
        is_week_before_day = today == one_week_before
        is_during_week = week_date <= today <= week_end
        if not (is_announcement_day or is_week_before_day or is_during_week):
            continue

        tracking = await get_reminder_tracking(week_start)

        # --- Monday channel announcement (day of on-call week start) ---
        if is_announcement_day and now_utc.hour == TARGET_HOUR_UTC and not tracking["announcement_sent"]:
            await _send_channel_announcement(client, user_id, week_start)
            tracking["announcement_sent"] = True
            await save_reminder_tracking(week_start, tracking)

        # --- 1-week-before reminder ---
        if is_week_before_day and now_utc.hour == TARGET_HOUR_UTC and not tracking["week_before_sent"]:
            week_range = format_week_range(week_start)
            await client.chat_postMessage(
                channel=user_id,
                text=(
                    f":calendar: Heads up — you're on call next week (*{week_range}*). "
                    f"Use `/nf-core on-call switch` if you need to change this."
                ),
            )
            tracking["week_before_sent"] = True
            await save_reminder_tracking(week_start, tracking)

        # --- Daily reminder during on-call week (Mon–Sun, 8am user tz) ---
        if is_during_week:
            today_str = today.isoformat()
            daily_sent: list[str] = tracking.get("daily_sent", [])
            if today_str not in daily_sent and await _is_user_local_morning(client, user_id, now_utc):
                if today == week_date:
                    msg = (
                        ":saluting_face: Heads up — you're on call this week! Thanks for keeping the community running."
                    )
                else:
                    msg = ":saluting_face: Reminder: you're on call today. Thanks for being there!"
                await client.chat_postMessage(channel=user_id, text=msg)
                daily_sent.append(today_str)
                tracking["daily_sent"] = daily_sent
                await save_reminder_tracking(week_start, tracking)


_tz_cache: dict[str, tuple[int, float]] = {}  # user_id → (tz_offset, fetched_at)
_TZ_CACHE_TTL = 86400.0  # 24 hours


async def _is_user_local_morning(
    client: AsyncWebClient,
    user_id: str,
    now_utc: datetime.datetime,
) -> bool:
    """Return True if it is 08:00 in the user's Slack timezone."""
    now_ts = now_utc.timestamp()
    cached = _tz_cache.get(user_id)
    if cached and (now_ts - cached[1]) < _TZ_CACHE_TTL:
        tz_offset = cached[0]
    else:
        try:
            resp = await client.users_info(user=user_id)
            tz_offset = resp["user"].get("tz_offset", 0)  # seconds east of UTC
        except Exception:
            tz_offset = 0
        _tz_cache[user_id] = (tz_offset, now_ts)

    user_tz = datetime.timezone(datetime.timedelta(seconds=tz_offset))
    user_local = now_utc.astimezone(user_tz)
    return user_local.hour == 8


async def _send_assignment_dm(client: AsyncWebClient, user_id: str, week_start: str) -> None:
    """DM a user that they have been scheduled for on-call."""
    week_range = format_week_range(week_start)
    await client.chat_postMessage(
        channel=user_id,
        text=(
            f":calendar: You're on call the week of *{week_range}*. "
            f"Use `/nf-core on-call switch` if you need to change this."
        ),
    )


async def _send_channel_announcement(
    client: AsyncWebClient,
    user_id: str,
    week_start: str,
) -> None:
    """Post to #core announcing who is on call this week."""
    week_range = format_week_range(week_start)
    try:
        await client.chat_postMessage(
            channel="core",
            text=f":mega: <@{user_id}> is on call this week (*{week_range}*).",
        )
    except Exception:
        logger.exception("Failed to post on-call announcement to #core")


async def _warn_unassigned(client: AsyncWebClient, week_start: str) -> None:
    """Warn #core that a week has no one assigned."""
    week_range = format_week_range(week_start)
    try:
        await client.chat_postMessage(
            channel="core",
            text=(
                f":warning: The on-call week of *{week_range}* has no one assigned. "
                f"Everyone is marked as unavailable. Please coordinate manually."
            ),
        )
    except Exception:
        logger.exception("Failed to post unassigned-week warning to #core")


# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------


async def _cleanup_old_entries(today: datetime.date | None = None) -> None:
    """Remove roster entries older than CLEANUP_KEEP_WEEKS weeks."""
    if today is None:
        today = datetime.date.today()
    cutoff = monday_of_week(today) - datetime.timedelta(weeks=CLEANUP_KEEP_WEEKS)
    cutoff_str = cutoff.isoformat()

    roster = await list_roster()
    for entry in roster:
        if entry["week_start"] < cutoff_str:
            await delete_roster_entry(entry["week_start"])
            logger.info("Cleaned up old roster entry for week %s", entry["week_start"])
