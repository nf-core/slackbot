"""``/nf-core on-call skip`` — skip the caller's next on-call week."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from nf_core_bot import config
from nf_core_bot.commands.oncall.helpers import current_week_start, format_week_range
from nf_core_bot.db.oncall import (
    add_to_queue_front,
    get_all_unavailable_users,
    get_round_robin_state,
    list_roster,
    save_round_robin_state,
    update_roster_assignment,
)
from nf_core_bot.permissions.checks import refresh_core_team

if TYPE_CHECKING:
    from slack_bolt.context.respond.async_respond import AsyncRespond as Respond
    from slack_sdk.web.async_client import AsyncWebClient

logger = logging.getLogger(__name__)


async def handle_oncall_skip(
    respond: Respond,
    client: AsyncWebClient,
    user_id: str,
) -> None:
    """Skip the caller's next on-call week, finding a replacement."""

    roster = await list_roster(from_date=current_week_start())
    if not roster:
        await respond(text="No on-call schedule found yet.", response_type="ephemeral")
        return

    # Find the caller's next assignment
    my_entry = next((e for e in roster if e.get("assigned_user_id") == user_id), None)
    if my_entry is None:
        await respond(
            text="You don't have an upcoming on-call week to skip.",
            response_type="ephemeral",
        )
        return

    my_week = my_entry["week_start"]
    replacement = await find_skip_replacement(client, roster, my_week, user_id)

    if replacement is None:
        await respond(
            text=(
                "No one is available to cover your on-call week. "
                "Try `/nf-core on-call switch` to swap with someone directly."
            ),
            response_type="ephemeral",
        )
        return

    # Assign the replacement
    await update_roster_assignment(my_week, replacement, "skipped")

    # Move the caller to the front of the round-robin queue
    await add_to_queue_front(user_id)

    week_range = format_week_range(my_week)

    # DM the replacement
    await client.chat_postMessage(
        channel=replacement,
        text=(
            f":wave: You've been assigned on-call duty for *{week_range}* "
            f"because <@{user_id}> needed to skip. "
            f"Use `/nf-core on-call switch` if you need to change this."
        ),
    )

    # DM the caller
    await client.chat_postMessage(
        channel=user_id,
        text=(
            f":white_check_mark: You've been removed from on-call for *{week_range}*. "
            f"<@{replacement}> will cover. You'll be prioritised for the next available week."
        ),
    )

    await respond(
        text=f":white_check_mark: Skipped! <@{replacement}> will cover *{week_range}* for you.",
        response_type="ephemeral",
    )


async def find_skip_replacement(
    client: AsyncWebClient,
    roster: list[dict[str, Any]],
    week_start: str,
    skipping_user_id: str,
) -> str | None:
    """Find the best replacement for a skipped week.

    Priority:
    1. People in ``queue_front`` who are not already assigned and not unavailable.
    2. Round-robin order: person who went longest without being on-call.

    Returns the user ID of the replacement, or ``None`` if nobody is available.
    """
    # Fetch independent data concurrently
    members, unavailable, rr_state = await asyncio.gather(
        refresh_core_team(client, config.CORE_TEAM_USERGROUP_HANDLE or "core-team"),
        get_all_unavailable_users(week_start),
        get_round_robin_state(),
    )

    # Users already assigned in the schedule window
    assigned_users = {e.get("assigned_user_id") for e in roster if e.get("assigned_user_id")}
    # Remove the skipping user (their slot is being freed)
    assigned_users.discard(skipping_user_id)

    # Candidates: in core-team, not already assigned, not unavailable, not the skipper
    candidates = members - assigned_users - unavailable - {skipping_user_id}
    if not candidates:
        return None
    last_assigned: dict[str, str] = rr_state.get("last_assigned", {})
    queue_front: list[str] = rr_state.get("queue_front", [])

    # Check queue_front first (people who previously skipped)
    for uid in queue_front:
        if uid in candidates:
            queue_front.remove(uid)
            rr_state["queue_front"] = queue_front
            await save_round_robin_state(rr_state)
            return uid

    # Fall back to round-robin: sort by last assigned date (earliest first, never-assigned first)
    def _sort_key(uid: str) -> str:
        return last_assigned.get(uid, "0000-00-00")

    result: str = min(candidates, key=_sort_key)
    return result
