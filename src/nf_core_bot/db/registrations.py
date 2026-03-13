"""Data-access helpers for registration records.

Key patterns
------------
- ``PK=HACKATHON#{id}  SK=REG#{user-id}``                       — primary
- ``GSI1PK=HACKATHON#{id}#SITE#{site}  GSI1SK=REG#{user-id}``   — site index
"""

from __future__ import annotations

import asyncio
import datetime
import logging
from typing import Any

from boto3.dynamodb.conditions import Attr, Key

from nf_core_bot.db.client import get_table

logger = logging.getLogger(__name__)


def _pk(hackathon_id: str) -> str:
    return f"HACKATHON#{hackathon_id}"


def _sk(user_id: str) -> str:
    return f"REG#{user_id}"


def _gsi1pk(hackathon_id: str, site_id: str) -> str:
    return f"HACKATHON#{hackathon_id}#SITE#{site_id}"


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------


async def create_registration(
    hackathon_id: str,
    user_id: str,
    site_id: str | None,
    form_data: dict[str, Any],
    profile_data: dict[str, Any],
) -> None:
    """Register a user for a hackathon.

    *profile_data* is expected to contain ``email``, ``slack_display_name``,
    and ``github_username`` (auto-populated from the Slack profile).

    If *site_id* is provided the item also receives GSI1 keys so it can be
    queried by site.

    Raises :class:`ValueError` if the registration already exists.
    """
    table = get_table()
    now = datetime.datetime.now(datetime.UTC).isoformat()

    item: dict[str, Any] = {
        "PK": _pk(hackathon_id),
        "SK": _sk(user_id),
        "hackathon_id": hackathon_id,
        "user_id": user_id,
        "site_id": site_id,
        "form_data": form_data,
        "profile_data": profile_data,
        "registered_at": now,
        "updated_at": now,
    }

    if site_id is not None:
        item["GSI1PK"] = _gsi1pk(hackathon_id, site_id)
        item["GSI1SK"] = _sk(user_id)

    def _put() -> None:
        table.put_item(
            Item=item,
            ConditionExpression=Attr("PK").not_exists(),
        )

    try:
        await asyncio.to_thread(_put)
    except table.meta.client.exceptions.ConditionalCheckFailedException:
        raise ValueError(f"User '{user_id}' is already registered for hackathon '{hackathon_id}'") from None

    logger.info(
        "Created registration for user '%s' in hackathon '%s' (site=%s).",
        user_id,
        hackathon_id,
        site_id,
    )


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------


async def get_registration(hackathon_id: str, user_id: str) -> dict[str, Any] | None:
    """Return a single registration, or ``None`` if not found."""
    table = get_table()

    def _get() -> dict[str, Any] | None:
        response = table.get_item(
            Key={"PK": _pk(hackathon_id), "SK": _sk(user_id)},
        )
        item: dict[str, Any] | None = response.get("Item")
        return item

    return await asyncio.to_thread(_get)


async def list_registrations(hackathon_id: str) -> list[dict[str, Any]]:
    """Return all registrations for a hackathon.

    Uses ``PK=HACKATHON#{id}`` with ``SK begins_with('REG#')``.
    """
    table = get_table()

    def _query() -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        kwargs: dict[str, Any] = {
            "KeyConditionExpression": (Key("PK").eq(_pk(hackathon_id)) & Key("SK").begins_with("REG#")),
        }
        while True:
            response = table.query(**kwargs)
            items.extend(response.get("Items", []))
            last_key = response.get("LastEvaluatedKey")
            if last_key is None:
                break
            kwargs["ExclusiveStartKey"] = last_key
        return items

    return await asyncio.to_thread(_query)


async def list_registrations_by_site(
    hackathon_id: str,
    site_id: str,
) -> list[dict[str, Any]]:
    """Return registrations for a specific site using GSI1.

    ``GSI1PK=HACKATHON#{id}#SITE#{site}`` with
    ``GSI1SK begins_with('REG#')``.
    """
    table = get_table()

    def _query() -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        kwargs: dict[str, Any] = {
            "IndexName": "GSI1",
            "KeyConditionExpression": (
                Key("GSI1PK").eq(_gsi1pk(hackathon_id, site_id)) & Key("GSI1SK").begins_with("REG#")
            ),
        }
        while True:
            response = table.query(**kwargs)
            items.extend(response.get("Items", []))
            last_key = response.get("LastEvaluatedKey")
            if last_key is None:
                break
            kwargs["ExclusiveStartKey"] = last_key
        return items

    return await asyncio.to_thread(_query)


async def count_registrations(hackathon_id: str) -> int:
    """Return the total number of registrations for a hackathon.

    Uses ``Select='COUNT'`` to avoid transferring item data.
    """
    table = get_table()

    def _query() -> int:
        total = 0
        kwargs: dict[str, Any] = {
            "KeyConditionExpression": (Key("PK").eq(_pk(hackathon_id)) & Key("SK").begins_with("REG#")),
            "Select": "COUNT",
        }
        while True:
            response = table.query(**kwargs)
            total += int(response["Count"])
            last_key = response.get("LastEvaluatedKey")
            if last_key is None:
                break
            kwargs["ExclusiveStartKey"] = last_key
        return total

    return await asyncio.to_thread(_query)


async def count_registrations_by_site(hackathon_id: str, site_id: str) -> int:
    """Return the number of registrations for a specific site via GSI1.

    Uses ``Select='COUNT'`` to avoid transferring item data.
    """
    table = get_table()

    def _query() -> int:
        total = 0
        kwargs: dict[str, Any] = {
            "IndexName": "GSI1",
            "KeyConditionExpression": (
                Key("GSI1PK").eq(_gsi1pk(hackathon_id, site_id)) & Key("GSI1SK").begins_with("REG#")
            ),
            "Select": "COUNT",
        }
        while True:
            response = table.query(**kwargs)
            total += int(response["Count"])
            last_key = response.get("LastEvaluatedKey")
            if last_key is None:
                break
            kwargs["ExclusiveStartKey"] = last_key
        return total

    return await asyncio.to_thread(_query)


# ---------------------------------------------------------------------------
# Update
# ---------------------------------------------------------------------------


async def update_registration(
    hackathon_id: str,
    user_id: str,
    site_id: str | None,
    form_data: dict[str, Any],
) -> None:
    """Update an existing registration's form data (and optionally site).

    Raises :class:`ValueError` if the registration does not exist.
    """
    table = get_table()
    now = datetime.datetime.now(datetime.UTC).isoformat()

    # Build the update expression dynamically based on whether site_id changed.
    update_parts = [
        "form_data = :fd",
        "site_id = :sid",
        "updated_at = :u",
    ]
    attr_values: dict[str, Any] = {
        ":fd": form_data,
        ":sid": site_id,
        ":u": now,
    }

    if site_id is not None:
        update_parts.append("GSI1PK = :g1pk")
        update_parts.append("GSI1SK = :g1sk")
        attr_values[":g1pk"] = _gsi1pk(hackathon_id, site_id)
        attr_values[":g1sk"] = _sk(user_id)

    set_expr = "SET " + ", ".join(update_parts)
    # Remove GSI1 keys when site is cleared, otherwise just SET.
    full_expr = set_expr + " REMOVE GSI1PK, GSI1SK" if site_id is None else set_expr

    def _update() -> None:
        table.update_item(
            Key={"PK": _pk(hackathon_id), "SK": _sk(user_id)},
            UpdateExpression=full_expr,
            ExpressionAttributeValues=attr_values,
            ConditionExpression=Attr("PK").exists(),
        )

    try:
        await asyncio.to_thread(_update)
    except table.meta.client.exceptions.ConditionalCheckFailedException:
        raise ValueError(f"Registration for user '{user_id}' in hackathon '{hackathon_id}' not found") from None

    logger.info(
        "Updated registration for user '%s' in hackathon '%s'.",
        user_id,
        hackathon_id,
    )


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------


async def delete_registration(hackathon_id: str, user_id: str) -> None:
    """Delete a registration.

    Raises :class:`ValueError` if the registration does not exist.
    """
    table = get_table()

    def _delete() -> None:
        table.delete_item(
            Key={"PK": _pk(hackathon_id), "SK": _sk(user_id)},
            ConditionExpression=Attr("PK").exists(),
        )

    try:
        await asyncio.to_thread(_delete)
    except table.meta.client.exceptions.ConditionalCheckFailedException:
        raise ValueError(f"Registration for user '{user_id}' in hackathon '{hackathon_id}' not found") from None

    logger.info(
        "Deleted registration for user '%s' in hackathon '%s'.",
        user_id,
        hackathon_id,
    )
