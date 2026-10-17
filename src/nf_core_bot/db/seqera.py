"""DynamoDB operations for Seqera workspace participants added by the bot.

Only people the bot itself added are recorded, so the weekly removal job
(``scheduler/seqera_jobs.py``) never touches participants added by hand.
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
    """A workspace participant the bot added."""

    workspace_id: str
    slack_user_id: str
    github_username: str
    email: str
    participant_id: int
    added_at: str


def _pk(workspace_id: str) -> str:
    """PK for a workspace's bot-added participants: ``SEQERA#<workspace-id>``."""
    return f"{SEQERA_PK_PREFIX}{workspace_id}"


def _sk(slack_user_id: str) -> str:
    return f"{USER_SK_PREFIX}{slack_user_id}"


def _now_iso() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat()


async def put_member(
    workspace_id: str,
    slack_user_id: str,
    github_username: str,
    email: str,
    participant_id: int,
) -> None:
    """Record that the bot added *slack_user_id* to *workspace_id* (overwrites)."""
    table = get_table()

    def _put() -> None:
        table.put_item(
            Item={
                "PK": _pk(workspace_id),
                "SK": _sk(slack_user_id),
                "workspace_id": workspace_id,
                "slack_user_id": slack_user_id,
                "github_username": github_username,
                "email": email,
                "participant_id": participant_id,
                "added_at": _now_iso(),
            }
        )

    await asyncio.to_thread(_put)


async def list_members(workspace_id: str) -> list[SeqeraMember]:
    """Return every participant the bot added to *workspace_id*."""
    table = get_table()

    def _query() -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        kwargs: dict[str, Any] = {
            "KeyConditionExpression": Key("PK").eq(_pk(workspace_id)) & Key("SK").begins_with(USER_SK_PREFIX)
        }
        while True:
            resp = table.query(**kwargs)
            items.extend(resp.get("Items", []))
            if "LastEvaluatedKey" not in resp:
                break
            kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
        return items

    items = await asyncio.to_thread(_query)
    return [
        SeqeraMember(
            workspace_id=item["workspace_id"],
            slack_user_id=item["slack_user_id"],
            github_username=item["github_username"],
            email=item["email"],
            participant_id=int(item["participant_id"]),
            added_at=item["added_at"],
        )
        for item in items
    ]


async def delete_member(workspace_id: str, slack_user_id: str) -> None:
    """Forget a bot-added participant (after removing them from the workspace)."""
    table = get_table()

    def _delete() -> None:
        table.delete_item(Key={"PK": _pk(workspace_id), "SK": _sk(slack_user_id)})

    await asyncio.to_thread(_delete)
