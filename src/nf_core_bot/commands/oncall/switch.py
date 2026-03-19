"""``/nf-core on-call switch [YYYY-MM-DD]`` — swap on-call weeks with another person."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from nf_core_bot.commands.oncall.helpers import (
    current_week_start,
    format_week_range,
    monday_of_week,
    parse_date_arg,
)
from nf_core_bot.db.oncall import list_roster, update_roster_assignment

if TYPE_CHECKING:
    from slack_bolt.async_app import AsyncAck as Ack
    from slack_bolt.async_app import AsyncRespond as Respond
    from slack_sdk.web.async_client import AsyncWebClient

logger = logging.getLogger(__name__)


async def handle_oncall_switch(
    ack: Ack,
    respond: Respond,
    client: AsyncWebClient,
    user_id: str,
    args: list[str],
) -> None:
    """Swap the caller's next on-call week with another week's assignee."""
    await ack()

    roster = await list_roster(from_date=current_week_start())
    if not roster:
        await respond(text="No on-call schedule found yet.", response_type="ephemeral")
        return

    # Find the caller's next assignment
    my_entry = next((e for e in roster if e.get("assigned_user_id") == user_id), None)
    if my_entry is None:
        await respond(
            text="You don't have an upcoming on-call week to swap.",
            response_type="ephemeral",
        )
        return

    my_week = my_entry["week_start"]

    # Determine the target week
    if args:
        try:
            target_date = parse_date_arg(args[0])
        except ValueError as exc:
            await respond(text=str(exc), response_type="ephemeral")
            return
        target_week = monday_of_week(target_date).isoformat()
    else:
        # Default: the week immediately after the caller's assignment
        my_idx = next(i for i, e in enumerate(roster) if e["week_start"] == my_week)
        if my_idx + 1 >= len(roster):
            await respond(
                text="There is no week after your assignment in the schedule to swap with.",
                response_type="ephemeral",
            )
            return
        target_week = roster[my_idx + 1]["week_start"]

    # Find the target entry
    target_entry = next((e for e in roster if e["week_start"] == target_week), None)
    if target_entry is None:
        await respond(
            text=f"No roster entry found for the week of {target_week}.",
            response_type="ephemeral",
        )
        return

    target_user = target_entry.get("assigned_user_id")
    if not target_user:
        await respond(
            text=f"The week of {format_week_range(target_week)} is unassigned — nothing to swap with.",
            response_type="ephemeral",
        )
        return

    if target_user == user_id:
        await respond(
            text="You can't swap with yourself.",
            response_type="ephemeral",
        )
        return

    # Perform the swap
    await asyncio.gather(
        update_roster_assignment(my_week, target_user, "swapped"),
        update_roster_assignment(target_week, user_id, "swapped"),
    )

    my_range = format_week_range(my_week)
    target_range = format_week_range(target_week)

    # DM both parties
    swap_msg_caller = (
        f":arrows_counterclockwise: Swap confirmed! You are now on call *{target_range}* "
        f"(was {my_range}). <@{target_user}> takes {my_range}."
    )
    swap_msg_target = (
        f":arrows_counterclockwise: On-call swap: <@{user_id}> swapped with you. "
        f"You are now on call *{my_range}* (was {target_range})."
    )

    await asyncio.gather(
        client.chat_postMessage(channel=user_id, text=swap_msg_caller),
        client.chat_postMessage(channel=target_user, text=swap_msg_target),
    )

    await respond(
        text=(
            f":arrows_counterclockwise: Swap confirmed! <@{target_user}> takes *{my_range}*, you take *{target_range}*."
        ),
        response_type="ephemeral",
    )
