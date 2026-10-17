"""DynamoDB operations for Seqera access the bot granted.

Only people the bot itself added are recorded, so ``/nf-core seqera remove``
and the weekly removal job (``scheduler/seqera_jobs.py``) never touch access
granted by hand.

Records are keyed by *target*: a workspace ID, or ``TEAM#<team-id>`` for an
organisation team (see ``SeqeraGroup.target_key`` in ``checks/seqera.py``).
"""

from __future__ import annotations

import asyncio
import datetime
from dataclasses import dataclass
from typing import Any

from boto3.dynamodb.conditions import Key

from nf_core_bot.db.client import get_table

SEQERA_PK_PREFIX = "SEQERA#"
USER_SK_PREFIX = "USER#"


@dataclass
class SeqeraMember:
    """Access the bot granted to one Slack user for one target."""

    target: str
    slack_user_id: str
    github_username: str
    email: str
    # Workspace participant ID, or team member ID for a team target.
    participant_id: int
    added_at: str
    group: str | None = None


def _pk(target: str) -> str:
    """PK for a target's bot-added members: ``SEQERA#<target>``."""
    return f"{SEQERA_PK_PREFIX}{target}"


def _sk(slack_user_id: str) -> str:
    return f"{USER_SK_PREFIX}{slack_user_id}"


def _now_iso() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat()


def _from_item(item: dict[str, Any]) -> SeqeraMember:
    return SeqeraMember(
        target=item["workspace_id"],
        slack_user_id=item["slack_user_id"],
        github_username=item["github_username"],
        email=item["email"],
        participant_id=int(item["participant_id"]),
        added_at=item["added_at"],
        group=item.get("group"),
    )


async def put_member(
    target: str,
    slack_user_id: str,
    github_username: str,
    email: str,
    participant_id: int,
    group: str | None = None,
) -> None:
    """Record that the bot added *slack_user_id* to *target* (overwrites)."""
    table = get_table()

    def _put() -> None:
        item: dict[str, Any] = {
            "PK": _pk(target),
            "SK": _sk(slack_user_id),
            # Attribute name predates team targets; it holds any target key.
            "workspace_id": target,
            "slack_user_id": slack_user_id,
            "github_username": github_username,
            "email": email,
            "participant_id": participant_id,
            "added_at": _now_iso(),
        }
        if group is not None:
            item["group"] = group
        table.put_item(Item=item)

    await asyncio.to_thread(_put)


async def get_member(target: str, slack_user_id: str) -> SeqeraMember | None:
    """Return the record for *slack_user_id* in *target*, or ``None``."""
    table = get_table()

    def _get() -> dict[str, Any] | None:
        item: dict[str, Any] | None = table.get_item(Key={"PK": _pk(target), "SK": _sk(slack_user_id)}).get("Item")
        return item

    item = await asyncio.to_thread(_get)
    return _from_item(item) if item else None


async def list_members(target: str) -> list[SeqeraMember]:
    """Return every member the bot added to *target*."""
    table = get_table()

    def _query() -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        kwargs: dict[str, Any] = {
            "KeyConditionExpression": Key("PK").eq(_pk(target)) & Key("SK").begins_with(USER_SK_PREFIX)
        }
        while True:
            resp = table.query(**kwargs)
            items.extend(resp.get("Items", []))
            if "LastEvaluatedKey" not in resp:
                break
            kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
        return items

    items = await asyncio.to_thread(_query)
    return [_from_item(item) for item in items]


async def delete_member(target: str, slack_user_id: str) -> None:
    """Forget a bot-added member (after removing them in Seqera)."""
    table = get_table()

    def _delete() -> None:
        table.delete_item(Key={"PK": _pk(target), "SK": _sk(slack_user_id)})

    await asyncio.to_thread(_delete)
