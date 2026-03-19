"""``/nf-core on-call unavailable <start> <end>`` — mark the caller as unavailable."""

from __future__ import annotations

import datetime
import logging
from typing import TYPE_CHECKING

from nf_core_bot.commands.oncall.helpers import (
    current_week_start,
    format_week_range,
    parse_date_arg,
)
from nf_core_bot.commands.oncall.skip import find_skip_replacement
from nf_core_bot.db.oncall import (
    add_to_queue_front,
    add_unavailability,
    list_roster,
    update_roster_assignment,
)

if TYPE_CHECKING:
    from slack_bolt.context.respond.async_respond import AsyncRespond as Respond
    from slack_sdk.web.async_client import AsyncWebClient

logger = logging.getLogger(__name__)


async def handle_oncall_unavailable(
    respond: Respond,
    client: AsyncWebClient,
    user_id: str,
    args: list[str],
) -> None:
    """Mark the caller as unavailable between two dates (inclusive)."""

    if len(args) < 2:
        await respond(
            text="Usage: `/nf-core on-call unavailable YYYY-MM-DD YYYY-MM-DD`",
            response_type="ephemeral",
        )
        return

    try:
        start = parse_date_arg(args[0])
        end = parse_date_arg(args[1])
    except ValueError as exc:
        await respond(text=str(exc), response_type="ephemeral")
        return

    if end < start:
        await respond(
            text="End date must be on or after the start date.",
            response_type="ephemeral",
        )
        return

    if end < datetime.date.today():
        await respond(
            text="Both dates are in the past. Please provide future dates.",
            response_type="ephemeral",
        )
        return

    start_str = start.isoformat()
    end_str = end.isoformat()

    # Store the unavailability
    await add_unavailability(user_id, start_str, end_str)

    msg_parts: list[str] = [
        f":calendar: Marked you as unavailable *{start.strftime('%b %-d')} – {end.strftime('%b %-d')}*."
    ]

    # Check if the caller is already assigned any weeks that overlap
    roster = await list_roster(from_date=current_week_start())
    my_overlapping = [
        e
        for e in roster
        if e.get("assigned_user_id") == user_id and _week_overlaps(e["week_start"], start_str, end_str)
    ]

    for entry in my_overlapping:
        week = entry["week_start"]
        week_range = format_week_range(week)

        replacement = await find_skip_replacement(client, roster, week, user_id)
        if replacement:
            await update_roster_assignment(week, replacement, "skipped")

            # Update round-robin: move caller to front of queue
            await add_to_queue_front(user_id)

            # DM the replacement
            await client.chat_postMessage(
                channel=replacement,
                text=(
                    f":wave: You've been assigned on-call duty for *{week_range}* "
                    f"because <@{user_id}> is unavailable. "
                    f"Use `/nf-core on-call switch` if you need to change this."
                ),
            )

            msg_parts.append(f"Reassigned *{week_range}* to <@{replacement}>.")

            # Remove that person from the roster's "assigned" set so the next
            # iteration doesn't consider them already assigned
            for r in roster:
                if r["week_start"] == week:
                    r["assigned_user_id"] = replacement
                    break
        else:
            msg_parts.append(f":warning: No replacement found for *{week_range}* — that week is now unassigned.")
            await update_roster_assignment(week, "", "skipped")

    await respond(text="\n".join(msg_parts), response_type="ephemeral")


def _week_overlaps(week_start: str, range_start: str, range_end: str) -> bool:
    """Check if a week (Mon–Sun) overlaps with a date range."""
    ws = datetime.date.fromisoformat(week_start)
    we = ws + datetime.timedelta(days=6)
    rs = datetime.date.fromisoformat(range_start)
    re_ = datetime.date.fromisoformat(range_end)
    return ws <= re_ and we >= rs
