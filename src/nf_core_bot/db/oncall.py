"""DynamoDB operations for on-call roster, round-robin state, and unavailability."""

from __future__ import annotations

import asyncio
import datetime
import logging
from typing import Any

from boto3.dynamodb.conditions import Attr, Key

from nf_core_bot.db.client import get_table

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Key helpers
# ---------------------------------------------------------------------------

ROSTER_PK_PREFIX = "ONCALL#"
ROSTER_SK = "ROSTER"
META_PK = "ONCALL_META"
ROUND_ROBIN_SK = "ROUND_ROBIN"
REMINDERS_SK_PREFIX = "REMINDERS#"
UNAVAIL_PK_PREFIX = "ONCALL_UNAVAIL#"


def _roster_pk(week_start: str) -> str:
    """PK for a roster entry: ``ONCALL#2026-04-06``."""
    return f"{ROSTER_PK_PREFIX}{week_start}"


def _unavail_pk(user_id: str) -> str:
    """PK for unavailability entries: ``ONCALL_UNAVAIL#U12345``."""
    return f"{UNAVAIL_PK_PREFIX}{user_id}"


def _unavail_sk(start_date: str, end_date: str) -> str:
    """SK for unavailability entries: ``2026-04-06#2026-04-20``."""
    return f"{start_date}#{end_date}"


def _reminders_sk(week_start: str) -> str:
    """SK for reminder tracking: ``REMINDERS#2026-04-06``."""
    return f"{REMINDERS_SK_PREFIX}{week_start}"


def _now_iso() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat()


# ---------------------------------------------------------------------------
# Roster CRUD
# ---------------------------------------------------------------------------


async def put_roster_entry(week_start: str, user_id: str, status: str = "scheduled") -> None:
    """Create a new roster entry for a given week. Raises ValueError if it already exists."""
    table = get_table()

    def _put() -> None:
        table.put_item(
            Item={
                "PK": _roster_pk(week_start),
                "SK": ROSTER_SK,
                "assigned_user_id": user_id,
                "status": status,
                "week_start": week_start,
                "created_at": _now_iso(),
            },
            ConditionExpression=Attr("PK").not_exists(),
        )

    try:
        await asyncio.to_thread(_put)
    except table.meta.client.exceptions.ConditionalCheckFailedException as exc:
        raise ValueError(f"Roster entry for week {week_start} already exists") from exc


async def get_roster_entry(week_start: str) -> dict[str, Any] | None:
    """Return the roster entry for a given week, or None."""
    table = get_table()

    def _get() -> Any:
        return table.get_item(Key={"PK": _roster_pk(week_start), "SK": ROSTER_SK})

    resp = await asyncio.to_thread(_get)
    item: dict[str, Any] | None = resp.get("Item")
    return item


async def update_roster_assignment(week_start: str, user_id: str, status: str) -> None:
    """Update who is assigned to a week and its status. Raises ValueError if the entry doesn't exist."""
    table = get_table()

    def _update() -> None:
        table.update_item(
            Key={"PK": _roster_pk(week_start), "SK": ROSTER_SK},
            UpdateExpression="SET assigned_user_id = :uid, #s = :st, updated_at = :ts",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={
                ":uid": user_id,
                ":st": status,
                ":ts": _now_iso(),
            },
            ConditionExpression=Attr("PK").exists(),
        )

    try:
        await asyncio.to_thread(_update)
    except table.meta.client.exceptions.ConditionalCheckFailedException as exc:
        raise ValueError(f"Roster entry for week {week_start} does not exist") from exc


async def list_roster(from_date: str | None = None) -> list[dict[str, Any]]:
    """Return all roster entries, optionally filtered to weeks >= *from_date*.

    Uses a table scan (acceptable — only ~8-12 roster items exist at a time).
    Results are sorted by week_start ascending.
    """
    table = get_table()

    def _scan() -> list[dict[str, Any]]:
        filter_expr = Attr("PK").begins_with(ROSTER_PK_PREFIX) & Attr("SK").eq(ROSTER_SK)
        items: list[dict[str, Any]] = []
        kwargs: dict[str, Any] = {"FilterExpression": filter_expr}
        while True:
            resp = table.scan(**kwargs)
            items.extend(resp.get("Items", []))
            if "LastEvaluatedKey" not in resp:
                break
            kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
        return items

    items = await asyncio.to_thread(_scan)

    if from_date:
        items = [i for i in items if i.get("week_start", "") >= from_date]

    items.sort(key=lambda i: i.get("week_start", ""))
    return items


async def delete_roster_entry(week_start: str) -> None:
    """Delete a roster entry."""
    table = get_table()

    def _delete() -> None:
        table.delete_item(Key={"PK": _roster_pk(week_start), "SK": ROSTER_SK})

    await asyncio.to_thread(_delete)


# ---------------------------------------------------------------------------
# Round-robin state
# ---------------------------------------------------------------------------


async def get_round_robin_state() -> dict[str, Any]:
    """Return the round-robin state, or a default empty state."""
    table = get_table()

    def _get() -> Any:
        return table.get_item(Key={"PK": META_PK, "SK": ROUND_ROBIN_SK})

    resp = await asyncio.to_thread(_get)
    item: dict[str, Any] | None = resp.get("Item")
    if item:
        return {
            "last_assigned": item.get("last_assigned", {}),
            "queue_front": item.get("queue_front", []),
        }
    return {"last_assigned": {}, "queue_front": []}


async def save_round_robin_state(state: dict[str, Any]) -> None:
    """Persist the round-robin state (overwrites)."""
    table = get_table()

    def _put() -> None:
        table.put_item(
            Item={
                "PK": META_PK,
                "SK": ROUND_ROBIN_SK,
                "last_assigned": state.get("last_assigned", {}),
                "queue_front": state.get("queue_front", []),
                "updated_at": _now_iso(),
            }
        )

    await asyncio.to_thread(_put)


async def add_to_queue_front(user_id: str) -> None:
    """Add *user_id* to the front of the skip queue, idempotently."""
    rr_state = await get_round_robin_state()
    queue_front: list[str] = rr_state.get("queue_front", [])
    if user_id not in queue_front:
        queue_front.insert(0, user_id)
    rr_state["queue_front"] = queue_front
    await save_round_robin_state(rr_state)


# ---------------------------------------------------------------------------
# Unavailability
# ---------------------------------------------------------------------------


async def add_unavailability(user_id: str, start_date: str, end_date: str) -> None:
    """Record that *user_id* is unavailable from *start_date* to *end_date* (inclusive)."""
    table = get_table()

    def _put() -> None:
        table.put_item(
            Item={
                "PK": _unavail_pk(user_id),
                "SK": _unavail_sk(start_date, end_date),
                "start_date": start_date,
                "end_date": end_date,
                "user_id": user_id,
                "created_at": _now_iso(),
            }
        )

    await asyncio.to_thread(_put)


async def remove_unavailability(user_id: str, start_date: str, end_date: str) -> None:
    """Remove a specific unavailability entry."""
    table = get_table()

    def _delete() -> None:
        table.delete_item(
            Key={
                "PK": _unavail_pk(user_id),
                "SK": _unavail_sk(start_date, end_date),
            }
        )

    await asyncio.to_thread(_delete)


async def list_unavailability(user_id: str) -> list[dict[str, Any]]:
    """Return all unavailability entries for a user."""
    table = get_table()

    def _query() -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        kwargs: dict[str, Any] = {
            "KeyConditionExpression": Key("PK").eq(_unavail_pk(user_id)),
        }
        while True:
            resp = table.query(**kwargs)
            items.extend(resp.get("Items", []))
            if "LastEvaluatedKey" not in resp:
                break
            kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
        return items

    return await asyncio.to_thread(_query)


async def is_user_unavailable(user_id: str, week_start: str) -> bool:
    """Check whether *user_id* has any unavailability overlapping the week starting on *week_start*.

    A week runs Monday–Sunday (7 days).  An unavailability range overlaps if:
    ``unavail.start_date <= week_end AND unavail.end_date >= week_start``
    """
    week_start_date = datetime.date.fromisoformat(week_start)
    week_end_date = week_start_date + datetime.timedelta(days=6)
    week_end = week_end_date.isoformat()

    entries = await list_unavailability(user_id)
    return any(entry["start_date"] <= week_end and entry["end_date"] >= week_start for entry in entries)


async def get_all_unavailable_users(week_start: str) -> set[str]:
    """Return the set of user IDs who are unavailable for the given week.

    Scans all ONCALL_UNAVAIL# items.  Acceptable cost given the small number
    of unavailability entries expected.
    """
    table = get_table()
    week_start_date = datetime.date.fromisoformat(week_start)
    week_end_date = week_start_date + datetime.timedelta(days=6)
    week_end = week_end_date.isoformat()

    def _scan() -> list[dict[str, Any]]:
        filter_expr = Attr("PK").begins_with(UNAVAIL_PK_PREFIX)
        items: list[dict[str, Any]] = []
        kwargs: dict[str, Any] = {"FilterExpression": filter_expr}
        while True:
            resp = table.scan(**kwargs)
            items.extend(resp.get("Items", []))
            if "LastEvaluatedKey" not in resp:
                break
            kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
        return items

    items = await asyncio.to_thread(_scan)
    unavailable: set[str] = set()
    for item in items:
        if item["start_date"] <= week_end and item["end_date"] >= week_start:
            unavailable.add(item["user_id"])
    return unavailable


# ---------------------------------------------------------------------------
# Reminder tracking
# ---------------------------------------------------------------------------


async def get_reminder_tracking(week_start: str) -> dict[str, Any]:
    """Return the reminder tracking record for a week, or empty defaults."""
    table = get_table()

    def _get() -> Any:
        return table.get_item(Key={"PK": META_PK, "SK": _reminders_sk(week_start)})

    resp = await asyncio.to_thread(_get)
    item: dict[str, Any] | None = resp.get("Item")
    if item:
        return {
            "assignment_sent": item.get("assignment_sent", False),
            "week_before_sent": item.get("week_before_sent", False),
            "daily_sent": item.get("daily_sent", []),
            "announcement_sent": item.get("announcement_sent", False),
        }
    return {
        "assignment_sent": False,
        "week_before_sent": False,
        "daily_sent": [],
        "announcement_sent": False,
    }


async def save_reminder_tracking(week_start: str, data: dict[str, Any]) -> None:
    """Persist reminder tracking state for a week (overwrites)."""
    table = get_table()

    def _put() -> None:
        table.put_item(
            Item={
                "PK": META_PK,
                "SK": _reminders_sk(week_start),
                "assignment_sent": data.get("assignment_sent", False),
                "week_before_sent": data.get("week_before_sent", False),
                "daily_sent": data.get("daily_sent", []),
                "announcement_sent": data.get("announcement_sent", False),
                "updated_at": _now_iso(),
            }
        )

    await asyncio.to_thread(_put)
