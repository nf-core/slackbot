"""DynamoDB state for proposal reviews — dedup so each proposal is reviewed once.

Key pattern::

    PK = PROPOSAL_REVIEW#<issue-number>   SK = META

Stores when a proposal was auto-reviewed and the thread it was posted to, so
the scheduler/listener doesn't re-review on message edits or bot restarts.
"""

from __future__ import annotations

import asyncio
import datetime
from typing import Any

from boto3.dynamodb.conditions import Attr

from nf_core_bot.db.client import get_table

_SK = "META"
_STATUS_IN_PROGRESS = "in_progress"
_STATUS_POSTED = "posted"


def _pk(number: int) -> str:
    return f"PROPOSAL_REVIEW#{number}"


def _now_iso() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat()


async def get_review_record(number: int) -> dict[str, Any] | None:
    """Return the review record for *number*, or ``None`` if not yet reviewed."""
    table = get_table()
    resp = await asyncio.to_thread(table.get_item, Key={"PK": _pk(number), "SK": _SK})
    return resp.get("Item")


async def claim_review(number: int) -> bool:
    """Atomically claim the review for *number*.

    Returns ``True`` if this caller won the claim (no prior record existed),
    ``False`` if it was already claimed/reviewed. Prevents duplicate concurrent
    reviews of the same proposal.
    """
    table = get_table()

    def _put() -> None:
        table.put_item(
            Item={"PK": _pk(number), "SK": _SK, "status": _STATUS_IN_PROGRESS, "claimed_at": _now_iso()},
            ConditionExpression=Attr("PK").not_exists(),
        )

    try:
        await asyncio.to_thread(_put)
        return True
    except table.meta.client.exceptions.ConditionalCheckFailedException:
        return False


async def mark_reviewed(number: int, *, thread_ts: str | None = None, channel: str | None = None) -> None:
    """Record that *number* has been reviewed and posted."""
    table = get_table()
    item: dict[str, Any] = {
        "PK": _pk(number),
        "SK": _SK,
        "status": _STATUS_POSTED,
        "reviewed_at": _now_iso(),
    }
    if thread_ts:
        item["thread_ts"] = thread_ts
    if channel:
        item["channel"] = channel
    await asyncio.to_thread(table.put_item, Item=item)


async def release_claim(number: int) -> None:
    """Delete the claim for *number* (e.g. after a failed review) so it can retry."""
    table = get_table()
    await asyncio.to_thread(table.delete_item, Key={"PK": _pk(number), "SK": _SK})
