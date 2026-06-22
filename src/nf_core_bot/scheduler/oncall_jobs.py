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
from nf_core_bot.calendar.generator import safe_regenerate_calendars
from nf_core_bot.checks.github import PROPOSAL_SECTIONS, Proposal, list_open_proposals
from nf_core_bot.commands.oncall.helpers import current_week_start, format_week_range, monday_of_week
from nf_core_bot.db.oncall import (
    delete_roster_entry,
    get_all_unavailable_users,
    get_reminder_tracking,
    get_roster_entry,
    get_round_robin_state,
    list_roster,
    put_roster_entry,
    save_reminder_tracking,
    save_round_robin_state,
    update_roster_assignment,
)
from nf_core_bot.permissions.checks import refresh_core_team
from nf_core_bot.proposals.slack_utils import resolve_channel_id

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

# Maximum proposals listed per section in the announcement thread before a
# "(N more)" bullet is shown instead.
MAX_PROPOSALS_PER_SECTION = 5

# Channel names referenced in the start-of-week responsibilities reminder.
# Rendered as clickable Slack channel links where the ID can be resolved.
_RELEASE_REVIEW_CHANNEL = "release-review-trading"
_REQUEST_CORE_CHANNEL = "request-core"
_GITHUB_INVITATIONS_CHANNEL = "github-invitations"

# Docs link posted as the final thread reply under the weekly on-call
# announcement.
ONCALL_DOCS = "Docs: https://nf-co.re/docs/community/governance/core-team#complete-on-call-duties"

# Display heading for each proposal section, keyed by Proposal.section.
# Each heading names the action the on-call person should take.
_PROPOSAL_SECTION_HEADINGS = {
    "accepted": "*✅ Accepted pipelines — ready to set up:*",
    "rejected": "*🚫 Rejected pipelines — please close:*",
    "pipeline": "*💬 Open pipeline proposals — please continue facilitating discussion:*",
    "rfc": "*💬 Open RFC proposals — please continue facilitating discussion:*",
}


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


async def run_oncall_scheduler(client: AsyncWebClient) -> None:
    """Long-running loop that drives all on-call scheduled jobs.

    *client* is the Slack ``AsyncWebClient`` used to send messages and
    look up user profiles.
    """
    logger.info("on-call scheduler started")
    await sync_oncall_topic(client)
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
        await safe_regenerate_calendars(client)
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

        # Quick date check: skip entries that cannot trigger any action today.
        # The daily-reminder block uses the user's local date (which can be up
        # to ±1 day from UTC), so we widen the window by 1 day on each side to
        # avoid prematurely skipping entries for users far ahead/behind UTC.
        is_announcement_day = today == week_date
        is_week_before_day = today == one_week_before
        is_near_week = (week_date - datetime.timedelta(days=1)) <= today <= (week_end + datetime.timedelta(days=1))
        if not (is_week_before_day or is_near_week):
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

        # --- Daily reminder during on-call week (Mon–Fri, 8am user tz) ---
        # Use the user's local date for the week-range check so that
        # users in timezones far ahead of or behind UTC aren't matched
        # against the wrong week.
        if is_near_week:
            user_local_dt = await _get_user_local_datetime(client, user_id, now_utc)
            user_local_date = user_local_dt.date()
            user_in_week = week_date <= user_local_date <= week_end

            # Only send Mon–Fri (weekday 0–4); skip weekends.
            is_weekday = user_local_date.weekday() < 5

            if user_in_week and is_weekday and user_local_dt.hour == 8:
                local_date_str = user_local_date.isoformat()
                daily_sent: list[str] = tracking.get("daily_sent", [])
                if local_date_str not in daily_sent:
                    if user_local_date == week_date:
                        msg = (
                            ":saluting_face: Heads up — you're on call this week!"
                            " Thanks for keeping the community running."
                        )
                    else:
                        msg = ":saluting_face: Reminder: you're on call today. Thanks for being there!"
                    await client.chat_postMessage(channel=user_id, text=msg)
                    daily_sent.append(local_date_str)
                    tracking["daily_sent"] = daily_sent
                    await save_reminder_tracking(week_start, tracking)


# ---------------------------------------------------------------------------
# Channel-ID resolution (cached for process lifetime)
# ---------------------------------------------------------------------------

_channel_id: str | None = None
_channel_id_lock: asyncio.Lock | None = None


def _get_channel_lock() -> asyncio.Lock:
    global _channel_id_lock  # noqa: PLW0603
    if _channel_id_lock is None:
        _channel_id_lock = asyncio.Lock()
    return _channel_id_lock


async def _resolve_channel_id(client: AsyncWebClient) -> str | None:
    """Look up the #core channel ID by name and cache it for the process lifetime.

    Paginates through ``conversations.list`` (public + private channels the bot
    is a member of) until a match on ``config.ONCALL_CHANNEL`` is found.
    Returns ``None`` if the channel cannot be found (the bot may not be a member).
    """
    global _channel_id  # noqa: PLW0603
    if _channel_id is not None:
        return _channel_id

    async with _get_channel_lock():
        # Double-check after acquiring lock
        if _channel_id is not None:
            return _channel_id

        target_name = config.ONCALL_CHANNEL or "core"
        cursor: str | None = None
        while True:
            kwargs: dict[str, Any] = {
                "types": "public_channel,private_channel",
                "exclude_archived": True,
                "limit": 200,
            }
            if cursor:
                kwargs["cursor"] = cursor

            try:
                resp = await client.conversations_list(**kwargs)
            except Exception:
                logger.exception("Failed to list conversations while resolving #%s channel ID", target_name)
                return None

            channels: list[dict[str, Any]] = resp.get("channels", [])
            for ch_dict in channels:
                if ch_dict.get("name") == target_name:
                    _channel_id = ch_dict["id"]
                    logger.info("Resolved #%s → %s", target_name, _channel_id)
                    return _channel_id

            meta: dict[str, Any] = resp.get("response_metadata", {})
            cursor = meta.get("next_cursor")
            if not cursor:
                break

        logger.warning("Could not find channel #%s — is the bot a member?", target_name)
        return None


# ---------------------------------------------------------------------------
# Timezone helpers
# ---------------------------------------------------------------------------

_tz_cache: dict[str, tuple[int, float]] = {}  # user_id → (tz_offset, fetched_at)
_TZ_CACHE_TTL = 86400.0  # 24 hours


async def _get_user_local_datetime(
    client: AsyncWebClient,
    user_id: str,
    now_utc: datetime.datetime,
) -> datetime.datetime:
    """Return *now_utc* converted to the user's Slack timezone."""
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
    return now_utc.astimezone(user_tz)


async def _is_user_local_morning(
    client: AsyncWebClient,
    user_id: str,
    now_utc: datetime.datetime,
) -> bool:
    """Return True if it is 08:00 in the user's Slack timezone."""
    user_local = await _get_user_local_datetime(client, user_id, now_utc)
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
    """Post to #core announcing who is on call this week.

    Follows up in-thread with the start-of-week responsibilities reminder
    and a digest of open proposals.
    """
    week_range = format_week_range(week_start)
    channel = await _resolve_channel_id(client)
    if channel is None:
        logger.error("Cannot post on-call announcement — #core channel not resolved")
        return
    try:
        resp = await client.chat_postMessage(
            channel=channel,
            text=f":mega: <@{user_id}> is on call this week (*{week_range}*).",
        )
    except Exception:
        logger.exception("Failed to post on-call announcement to #core")
    else:
        thread_ts = resp.get("ts") if resp else None
        if thread_ts:
            await _post_announcement_thread(client, channel, thread_ts)

    await sync_oncall_topic(client)


async def _channel_link(client: AsyncWebClient, name: str) -> str:
    """Return a clickable ``<#ID>`` channel link, falling back to ``#name`` text."""
    cid = await resolve_channel_id(client, name)
    return f"<#{cid}>" if cid else f"#{name}"


async def _build_responsibilities(client: AsyncWebClient) -> str:
    """Build the start-of-week responsibilities reminder.

    Channel references are rendered as clickable Slack channel links where the
    channel ID can be resolved; otherwise they fall back to plain ``#name`` text.
    """
    release_review = await _channel_link(client, _RELEASE_REVIEW_CHANNEL)
    request_core = await _channel_link(client, _REQUEST_CORE_CHANNEL)
    github_invitations = await _channel_link(client, _GITHUB_INVITATIONS_CHANNEL)
    return (
        "*Start of week responsibilities to do now:*\n"
        "- Check status and nudge ALL active proposals: https://github.com/nf-core/proposals\n"
        f"- Check stale requests in {release_review} and suggest swaps\n"
        "\n"
        "*Ongoing during the week:*\n"
        f"- Monitor {request_core}\n"
        f"- Monitor {github_invitations}"
    )


async def _post_announcement_thread(client: AsyncWebClient, channel: str, thread_ts: str) -> None:
    """Post the responsibilities reminder, proposals digest, and docs link as thread replies.

    All three replies are best-effort and independent: a failure posting one does
    not prevent the others.
    """
    try:
        responsibilities = await _build_responsibilities(client)
        await client.chat_postMessage(
            channel=channel,
            thread_ts=thread_ts,
            text=responsibilities,
        )
    except Exception:
        logger.exception("Failed to post on-call responsibilities thread reply")

    try:
        proposals = await list_open_proposals()
        message = _format_proposals_digest(proposals)
        if message:
            await client.chat_postMessage(
                channel=channel,
                thread_ts=thread_ts,
                text=message,
            )
    except Exception:
        logger.exception("Failed to post on-call proposals thread reply")

    try:
        await client.chat_postMessage(
            channel=channel,
            thread_ts=thread_ts,
            text=ONCALL_DOCS,
        )
    except Exception:
        logger.exception("Failed to post on-call docs thread reply")


def _slack_link(url: str, text: str) -> str:
    """Render a Slack hyperlink, escaping the display text."""
    escaped = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return f"<{url}|{escaped}>"


def _format_proposals_digest(proposals: list[Proposal]) -> str | None:
    """Format categorised proposals into the thread-reply message text.

    Each section lists at most ``MAX_PROPOSALS_PER_SECTION`` issues (most
    recently updated first) with a trailing "(N more)" bullet when truncated.
    Empty sections are omitted; returns ``None`` if nothing to show.
    """
    blocks: list[str] = []
    for section in PROPOSAL_SECTIONS:
        items = [p for p in proposals if p.section == section]
        if not items:
            continue
        lines = [_PROPOSAL_SECTION_HEADINGS[section]]
        lines.extend(f"- {_slack_link(p.url, p.title)}" for p in items[:MAX_PROPOSALS_PER_SECTION])
        remainder = len(items) - MAX_PROPOSALS_PER_SECTION
        if remainder > 0:
            lines.append(f"- ({remainder} more)")
        blocks.append("\n".join(lines))

    if not blocks:
        return None
    return "\n\n".join(blocks)


# ---------------------------------------------------------------------------
# Channel topic sync
# ---------------------------------------------------------------------------


async def sync_oncall_topic(client: AsyncWebClient) -> None:
    """Update the #core channel topic to match this week's on-call assignee.

    No-op if the topic already matches — Slack posts a system message
    in the channel every time the topic is set, so we dedupe to avoid
    spamming #core on every scheduler restart or roster recheck.

    Best-effort: all exceptions are swallowed so callers (switch, reboot,
    weekly announcement) never fail because of a topic-update issue.
    """
    try:
        channel = await _resolve_channel_id(client)
        if channel is None:
            logger.warning("Cannot sync on-call topic — #core channel not resolved")
            return

        current_entry = await get_roster_entry(current_week_start())
        if current_entry and current_entry.get("assigned_user_id"):
            desired_topic = f"On call: <@{current_entry['assigned_user_id']}>"
        else:
            desired_topic = ""

        try:
            info = await client.conversations_info(channel=channel)
            channel_data: dict[str, Any] = info.get("channel") or {}
            topic_data: dict[str, Any] = channel_data.get("topic") or {}
            current_topic = topic_data.get("value") or ""
        except Exception:
            logger.exception("Failed to read current #core channel topic; skipping topic sync")
            return

        if current_topic == desired_topic:
            return

        await client.conversations_setTopic(channel=channel, topic=desired_topic)
        logger.info("Updated #core channel topic to %r", desired_topic)
    except Exception:
        logger.exception("Failed to sync #core channel topic")


async def _warn_unassigned(client: AsyncWebClient, week_start: str) -> None:
    """Warn #core that a week has no one assigned."""
    week_range = format_week_range(week_start)
    channel = await _resolve_channel_id(client)
    if channel is None:
        logger.error("Cannot post unassigned-week warning — #core channel not resolved")
        return
    try:
        await client.chat_postMessage(
            channel=channel,
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
