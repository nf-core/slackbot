"""Generate iCal feeds for on-call rosters and upload to S3.

Two feed types are produced:

* **Global** — one week-long event per roster entry, titled with the
  assigned person's display name.
* **Personal** — filtered to a single user, showing only their weeks.

Feeds are uploaded to S3 under an obfuscation token so the URLs are
unguessable but shareable.  Calendar clients (Google Calendar, etc.)
can subscribe to the resulting CloudFront / S3 URL.
"""

from __future__ import annotations

import asyncio
import datetime
import logging
from typing import TYPE_CHECKING, Any

import boto3
from icalendar import Calendar, Event  # type: ignore[import-untyped]

from nf_core_bot import config
from nf_core_bot.db.oncall import get_calendar_token, list_roster

if TYPE_CHECKING:
    from slack_sdk.web.async_client import AsyncWebClient

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Display-name resolution
# ---------------------------------------------------------------------------

_name_cache: dict[str, str] = {}


async def _resolve_display_name(client: AsyncWebClient, user_id: str) -> str:
    """Resolve a Slack user ID to a human-readable display name.

    Falls back to the user ID itself if the API call fails.  Results are
    cached in-memory for the process lifetime.
    """
    if user_id in _name_cache:
        return _name_cache[user_id]

    try:
        resp = await client.users_info(user=user_id)
        profile = resp["user"].get("profile", {})
        name = profile.get("display_name") or profile.get("real_name") or user_id
    except Exception:
        logger.warning("Could not resolve display name for %s", user_id)
        name = user_id

    _name_cache[user_id] = name
    return name


# ---------------------------------------------------------------------------
# iCal generation
# ---------------------------------------------------------------------------


def _make_base_calendar(name: str) -> Calendar:
    """Create a base ``VCALENDAR`` with standard properties."""
    cal = Calendar()
    cal.add("prodid", "-//nf-core//on-call-bot//EN")
    cal.add("version", "2.0")
    cal.add("calscale", "GREGORIAN")
    cal.add("method", "PUBLISH")
    cal.add("x-wr-calname", name)
    cal.add("x-wr-timezone", "UTC")
    return cal


def _make_event(week_start: str, summary: str, uid_suffix: str) -> Event:
    """Create a single all-day VEVENT spanning Monday–Sunday."""
    start = datetime.date.fromisoformat(week_start)
    # DTEND for all-day events is exclusive, so Sunday + 1 = next Monday
    end = start + datetime.timedelta(days=7)

    event = Event()
    event.add("dtstart", start)
    event.add("dtend", end)
    event.add("summary", summary)
    event.add("uid", f"oncall-{week_start}-{uid_suffix}@nf-core.bot")
    event.add("dtstamp", datetime.datetime.now(datetime.UTC))
    return event


async def generate_global_calendar(client: AsyncWebClient, roster: list[dict[str, Any]] | None = None) -> bytes:
    """Build the global on-call iCal feed (all users)."""
    if roster is None:
        roster = await list_roster()
    cal = _make_base_calendar("nf-core on-call")

    for entry in roster:
        user_id = entry.get("assigned_user_id", "")
        if not user_id:
            continue
        name = await _resolve_display_name(client, user_id)
        summary = f"nf-core on-call: {name}"
        cal.add_component(_make_event(entry["week_start"], summary, "global"))

    return bytes(cal.to_ical())


async def generate_personal_calendar(
    client: AsyncWebClient, user_id: str, roster: list[dict[str, Any]] | None = None
) -> bytes:
    """Build a personal on-call iCal feed for a single user."""
    if roster is None:
        roster = await list_roster()
    name = await _resolve_display_name(client, user_id)
    cal = _make_base_calendar(f"nf-core on-call — {name}")

    for entry in roster:
        if entry.get("assigned_user_id") == user_id:
            cal.add_component(_make_event(entry["week_start"], f"nf-core on-call: {name}", user_id))

    return bytes(cal.to_ical())


# ---------------------------------------------------------------------------
# S3 upload
# ---------------------------------------------------------------------------


def _get_s3_client() -> Any:
    """Return a boto3 S3 client (region from config)."""
    return boto3.client("s3", region_name=config.AWS_REGION)


async def _upload_to_s3(key: str, body: bytes) -> None:
    """Upload *body* to the configured S3 bucket under *key*."""
    bucket = config.CALENDAR_S3_BUCKET
    if not bucket:
        logger.debug("CALENDAR_S3_BUCKET not set — skipping calendar upload")
        return

    def _put() -> None:
        s3 = _get_s3_client()
        s3.put_object(
            Bucket=bucket,
            Key=key,
            Body=body,
            ContentType="text/calendar; charset=utf-8",
            CacheControl="max-age=300",  # 5-minute cache
        )

    await asyncio.to_thread(_put)
    logger.info("Uploaded calendar to s3://%s/%s", bucket, key)


# ---------------------------------------------------------------------------
# Public API — regenerate and upload all calendars
# ---------------------------------------------------------------------------


async def regenerate_calendars(client: AsyncWebClient) -> None:
    """Regenerate all iCal feeds and upload to S3.

    Called after any roster mutation (switch, skip, reboot, unavailable)
    and periodically by the scheduler.

    No-ops gracefully if S3 is not configured (local dev).
    """
    bucket = config.CALENDAR_S3_BUCKET
    if not bucket:
        logger.debug("CALENDAR_S3_BUCKET not set — calendar regeneration skipped")
        return

    token = await get_calendar_token()
    if not token:
        logger.debug("No calendar token — calendar regeneration skipped")
        return

    # Fetch roster once and share across all generators
    roster = await list_roster()

    # Generate global feed
    global_ical = await generate_global_calendar(client, roster=roster)
    await _upload_to_s3(f"{token}/oncall-all.ics", global_ical)

    # Generate per-user feeds for everyone in the roster
    user_ids = {e["assigned_user_id"] for e in roster if e.get("assigned_user_id")}
    for user_id in user_ids:
        personal_ical = await generate_personal_calendar(client, user_id, roster=roster)
        await _upload_to_s3(f"{token}/oncall-{user_id}.ics", personal_ical)

    logger.info("Regenerated %d calendar feeds", 1 + len(user_ids))


def get_calendar_url(token: str, filename: str) -> str | None:
    """Build the public URL for a calendar file, or None if not configured."""
    domain = config.CALENDAR_CLOUDFRONT_DOMAIN
    if domain:
        return f"https://{domain}/{token}/{filename}"
    return None


async def safe_regenerate_calendars(client: AsyncWebClient) -> None:
    """Best-effort wrapper around :func:`regenerate_calendars`.

    Catches *all* exceptions so callers (mutation handlers, scheduler) never
    fail because of a calendar issue.
    """
    try:
        await regenerate_calendars(client)
    except Exception:
        logger.debug("Calendar regeneration skipped or failed", exc_info=True)
