"""Data-access helpers for site and organiser records.

Key patterns
------------
- ``PK=HACKATHON#{id}  SK=SITE#{site-id}``                — site metadata
- ``PK=HACKATHON#{id}  SK=SITE#{site-id}#ORG#{user-id}``  — organiser link
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


def _site_sk(site_id: str) -> str:
    return f"SITE#{site_id}"


def _org_sk(site_id: str, user_id: str) -> str:
    return f"SITE#{site_id}#ORG#{user_id}"


# ---------------------------------------------------------------------------
# Sites
# ---------------------------------------------------------------------------


async def add_site(
    hackathon_id: str,
    site_id: str,
    name: str,
    city: str,
    country: str,
) -> None:
    """Add a site to a hackathon.

    Raises :class:`ValueError` if the site already exists.
    """
    table = get_table()
    now = datetime.datetime.now(datetime.UTC).isoformat()
    item: dict[str, Any] = {
        "PK": _pk(hackathon_id),
        "SK": _site_sk(site_id),
        "hackathon_id": hackathon_id,
        "site_id": site_id,
        "name": name,
        "city": city,
        "country": country,
        "created_at": now,
    }

    def _put() -> None:
        table.put_item(
            Item=item,
            ConditionExpression=Attr("PK").not_exists(),
        )

    try:
        await asyncio.to_thread(_put)
    except table.meta.client.exceptions.ConditionalCheckFailedException:
        raise ValueError(f"Site '{site_id}' already exists in hackathon '{hackathon_id}'") from None

    logger.info("Added site '%s' to hackathon '%s'.", site_id, hackathon_id)


async def remove_site(hackathon_id: str, site_id: str) -> None:
    """Remove a site.

    Raises :class:`ValueError` if the site does not exist.
    """
    table = get_table()

    def _delete() -> None:
        table.delete_item(
            Key={"PK": _pk(hackathon_id), "SK": _site_sk(site_id)},
            ConditionExpression=Attr("PK").exists(),
        )

    try:
        await asyncio.to_thread(_delete)
    except table.meta.client.exceptions.ConditionalCheckFailedException:
        raise ValueError(f"Site '{site_id}' not found in hackathon '{hackathon_id}'") from None

    logger.info("Removed site '%s' from hackathon '%s'.", site_id, hackathon_id)


async def update_site(
    hackathon_id: str,
    site_id: str,
    name: str,
    city: str,
    country: str,
) -> None:
    """Update an existing site's metadata.

    Raises :class:`ValueError` if the site does not exist.
    """
    table = get_table()
    now = datetime.datetime.now(datetime.UTC).isoformat()

    def _update() -> None:
        table.update_item(
            Key={"PK": _pk(hackathon_id), "SK": _site_sk(site_id)},
            UpdateExpression="SET #n = :n, city = :c, country = :co, updated_at = :u",
            ExpressionAttributeNames={"#n": "name"},
            ExpressionAttributeValues={
                ":n": name,
                ":c": city,
                ":co": country,
                ":u": now,
            },
            ConditionExpression=Attr("PK").exists(),
        )

    try:
        await asyncio.to_thread(_update)
    except table.meta.client.exceptions.ConditionalCheckFailedException:
        raise ValueError(f"Site '{site_id}' not found in hackathon '{hackathon_id}'") from None

    logger.info("Updated site '%s' in hackathon '%s'.", site_id, hackathon_id)


async def get_site(hackathon_id: str, site_id: str) -> dict[str, Any] | None:
    """Return site metadata, or ``None`` if not found."""
    table = get_table()

    def _get() -> dict[str, Any] | None:
        response = table.get_item(
            Key={"PK": _pk(hackathon_id), "SK": _site_sk(site_id)},
        )
        item: dict[str, Any] | None = response.get("Item")
        return item

    return await asyncio.to_thread(_get)


async def list_sites(hackathon_id: str) -> list[dict[str, Any]]:
    """Return all sites for a hackathon.

    Queries ``PK=HACKATHON#{id}`` with ``SK begins_with('SITE#')`` and
    filters out organiser records (whose SK contains ``#ORG#``).
    """
    table = get_table()

    def _query() -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        kwargs: dict[str, Any] = {
            "KeyConditionExpression": (Key("PK").eq(_pk(hackathon_id)) & Key("SK").begins_with("SITE#")),
        }
        while True:
            response = table.query(**kwargs)
            # Exclude organiser rows (SK contains '#ORG#') — filtered
            # in Python because DynamoDB does not allow key attributes
            # in FilterExpression.
            items.extend(item for item in response.get("Items", []) if "#ORG#" not in str(item.get("SK", "")))
            last_key = response.get("LastEvaluatedKey")
            if last_key is None:
                break
            kwargs["ExclusiveStartKey"] = last_key
        return items

    return await asyncio.to_thread(_query)


# ---------------------------------------------------------------------------
# Organisers
# ---------------------------------------------------------------------------


async def add_organiser(hackathon_id: str, site_id: str, user_id: str) -> None:
    """Add an organiser to a site.

    Raises :class:`ValueError` if the organiser record already exists.
    """
    table = get_table()
    now = datetime.datetime.now(datetime.UTC).isoformat()
    item: dict[str, Any] = {
        "PK": _pk(hackathon_id),
        "SK": _org_sk(site_id, user_id),
        "hackathon_id": hackathon_id,
        "site_id": site_id,
        "user_id": user_id,
        "created_at": now,
    }

    def _put() -> None:
        table.put_item(
            Item=item,
            ConditionExpression=Attr("PK").not_exists(),
        )

    try:
        await asyncio.to_thread(_put)
    except table.meta.client.exceptions.ConditionalCheckFailedException:
        raise ValueError(
            f"User '{user_id}' is already an organiser for site '{site_id}' in hackathon '{hackathon_id}'"
        ) from None

    logger.info(
        "Added organiser '%s' to site '%s' (hackathon '%s').",
        user_id,
        site_id,
        hackathon_id,
    )


async def remove_organiser(hackathon_id: str, site_id: str, user_id: str) -> None:
    """Remove an organiser from a site.

    Raises :class:`ValueError` if the organiser record does not exist.
    """
    table = get_table()

    def _delete() -> None:
        table.delete_item(
            Key={"PK": _pk(hackathon_id), "SK": _org_sk(site_id, user_id)},
            ConditionExpression=Attr("PK").exists(),
        )

    try:
        await asyncio.to_thread(_delete)
    except table.meta.client.exceptions.ConditionalCheckFailedException:
        raise ValueError(
            f"Organiser '{user_id}' not found for site '{site_id}' in hackathon '{hackathon_id}'"
        ) from None

    logger.info(
        "Removed organiser '%s' from site '%s' (hackathon '%s').",
        user_id,
        site_id,
        hackathon_id,
    )


async def list_organisers(hackathon_id: str, site_id: str) -> list[dict[str, Any]]:
    """Return all organisers for a specific site."""
    table = get_table()
    prefix = f"SITE#{site_id}#ORG#"

    def _query() -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        kwargs: dict[str, Any] = {
            "KeyConditionExpression": (Key("PK").eq(_pk(hackathon_id)) & Key("SK").begins_with(prefix)),
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
