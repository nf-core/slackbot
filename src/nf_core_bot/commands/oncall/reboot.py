"""``/nf-core on-call reboot`` — wipe and rebuild the on-call schedule."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from nf_core_bot.db.oncall import delete_roster_entry, list_roster, save_round_robin_state
from nf_core_bot.scheduler.oncall_jobs import _maybe_extend_roster

if TYPE_CHECKING:
    from slack_bolt.context.respond.async_respond import AsyncRespond as Respond
    from slack_sdk.web.async_client import AsyncWebClient

logger = logging.getLogger(__name__)


async def handle_oncall_reboot(
    respond: Respond,
    client: AsyncWebClient,
    user_id: str,
) -> None:
    """Wipe the current schedule and rebuild from scratch.

    This deletes all future roster entries and the round-robin state,
    then immediately re-extends the schedule using the current
    ``@core-team`` membership.
    """
    # 1. Delete all existing roster entries
    roster = await list_roster()
    deleted = 0
    for entry in roster:
        await delete_roster_entry(entry["week_start"])
        deleted += 1

    # 2. Reset round-robin state
    await save_round_robin_state({"last_assigned": {}, "queue_front": []})

    logger.info("on-call reboot by %s: deleted %d roster entries, reset round-robin state", user_id, deleted)

    # 3. Rebuild schedule
    await _maybe_extend_roster(client)

    # 4. Confirm
    new_roster = await list_roster()
    week_count = len(new_roster)

    await respond(
        text=f"On-call schedule rebooted. Deleted {deleted} old entries, created {week_count} new weeks.",
        response_type="ephemeral",
    )
