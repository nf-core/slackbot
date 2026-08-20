"""DynamoDB operations for tracking previously-seen GitHub security advisories."""

from __future__ import annotations

import asyncio
import datetime
from typing import Any

from boto3.dynamodb.conditions import Key

from nf_core_bot.db.client import get_table

ADVISORY_PK_PREFIX = "ADVISORY#"


def _advisory_pk(repo: str) -> str:
    """PK for a repo's advisories: ``ADVISORY#rnaseq``."""
    return f"{ADVISORY_PK_PREFIX}{repo}"


def _now_iso() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat()


async def get_known_advisories(repo: str) -> dict[str, dict[str, str]]:
    """Return ``{ghsa_id: {"state": ..., "updated_at": ...}}`` for *repo*."""
    table = get_table()

    def _query() -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        kwargs: dict[str, Any] = {"KeyConditionExpression": Key("PK").eq(_advisory_pk(repo))}
        while True:
            resp = table.query(**kwargs)
            items.extend(resp.get("Items", []))
            if "LastEvaluatedKey" not in resp:
                break
            kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
        return items

    items = await asyncio.to_thread(_query)
    return {item["SK"]: {"state": item["state"], "updated_at": item["updated_at"]} for item in items}


async def save_advisory_state(repo: str, ghsa_id: str, state: str, updated_at: str) -> None:
    """Persist the last-seen state/updated_at for a single advisory (overwrites)."""
    table = get_table()

    def _put() -> None:
        table.put_item(
            Item={
                "PK": _advisory_pk(repo),
                "SK": ghsa_id,
                "state": state,
                "updated_at": updated_at,
                "seen_at": _now_iso(),
            }
        )

    await asyncio.to_thread(_put)
