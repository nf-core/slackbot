"""Data-access helpers for hackathon metadata records.

Key pattern
-----------
- ``PK=HACKATHON#{id}  SK=META`` — one item per hackathon.

Statuses: draft → open → closed → archived.
"""

from __future__ import annotations

import asyncio
import datetime
import logging
from typing import Any

from boto3.dynamodb.conditions import Attr, Key

from nf_core_bot.db.client import get_table

logger = logging.getLogger(__name__)

VALID_STATUSES = frozenset({"draft", "open", "closed", "archived"})


def _pk(hackathon_id: str) -> str:
    return f"HACKATHON#{hackathon_id}"


_SK = "META"


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------


async def create_hackathon(hackathon_id: str, title: str, form_yaml: str) -> None:
    """Create a new hackathon with ``status='draft'``.

    Raises :class:`ValueError` if a hackathon with *hackathon_id* already
    exists.
    """
    table = get_table()
    now = datetime.datetime.now(datetime.UTC).isoformat()
    item: dict[str, Any] = {
        "PK": _pk(hackathon_id),
        "SK": _SK,
        "hackathon_id": hackathon_id,
        "title": title,
        "form_yaml": form_yaml,
        "status": "draft",
        "created_at": now,
        "updated_at": now,
    }

    def _put() -> None:
        table.put_item(
            Item=item,
            ConditionExpression=Attr("PK").not_exists(),
        )

    try:
        await asyncio.to_thread(_put)
    except table.meta.client.exceptions.ConditionalCheckFailedException:
        raise ValueError(f"Hackathon '{hackathon_id}' already exists") from None

    logger.info("Created hackathon '%s'.", hackathon_id)


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------


async def get_hackathon(hackathon_id: str) -> dict[str, Any] | None:
    """Return hackathon metadata, or ``None`` if not found."""
    table = get_table()

    def _get() -> dict[str, Any] | None:
        response = table.get_item(Key={"PK": _pk(hackathon_id), "SK": _SK})
        item: dict[str, Any] | None = response.get("Item")
        return item

    return await asyncio.to_thread(_get)


async def list_hackathons() -> list[dict[str, Any]]:
    """Return **all** hackathons via a table scan.

    This is acceptable because the number of hackathons is expected to stay
    very small (< 100 over the lifetime of the project).
    """
    table = get_table()

    def _scan() -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        kwargs: dict[str, Any] = {
            "FilterExpression": Attr("SK").eq(_SK) & Key("PK").begins_with("HACKATHON#"),
        }
        while True:
            response = table.scan(**kwargs)
            items.extend(response.get("Items", []))
            last_key = response.get("LastEvaluatedKey")
            if last_key is None:
                break
            kwargs["ExclusiveStartKey"] = last_key
        return items

    return await asyncio.to_thread(_scan)


async def get_active_hackathon() -> dict[str, Any] | None:
    """Return the first hackathon with ``status='open'``, or ``None``.

    If multiple hackathons are open simultaneously only the first one
    encountered during the scan is returned.
    """
    table = get_table()

    def _scan() -> dict[str, Any] | None:
        kwargs: dict[str, Any] = {
            "FilterExpression": (Attr("SK").eq(_SK) & Key("PK").begins_with("HACKATHON#") & Attr("status").eq("open")),
        }
        while True:
            response = table.scan(**kwargs)
            items: list[dict[str, Any]] = response.get("Items", [])
            if items:
                return items[0]
            last_key = response.get("LastEvaluatedKey")
            if last_key is None:
                return None
            kwargs["ExclusiveStartKey"] = last_key

    return await asyncio.to_thread(_scan)


# ---------------------------------------------------------------------------
# Update
# ---------------------------------------------------------------------------


async def update_hackathon_status(hackathon_id: str, new_status: str) -> None:
    """Transition a hackathon to *new_status*.

    Raises :class:`ValueError` if *new_status* is invalid or the hackathon
    does not exist.
    """
    if new_status not in VALID_STATUSES:
        raise ValueError(f"Invalid status '{new_status}'. Must be one of {sorted(VALID_STATUSES)}.")

    table = get_table()
    now = datetime.datetime.now(datetime.UTC).isoformat()

    def _update() -> None:
        table.update_item(
            Key={"PK": _pk(hackathon_id), "SK": _SK},
            UpdateExpression="SET #s = :s, updated_at = :u",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={":s": new_status, ":u": now},
            ConditionExpression=Attr("PK").exists(),
        )

    try:
        await asyncio.to_thread(_update)
    except table.meta.client.exceptions.ConditionalCheckFailedException:
        raise ValueError(f"Hackathon '{hackathon_id}' not found") from None

    logger.info("Hackathon '%s' status → %s.", hackathon_id, new_status)
