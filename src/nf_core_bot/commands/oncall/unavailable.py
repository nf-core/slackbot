"""``/nf-core on-call unavailable`` — manage the caller's unavailability ranges.

Subcommands:

* ``unavailable YYYY-MM-DD YYYY-MM-DD`` — mark the caller as unavailable.
* ``unavailable list`` — list the caller's stored unavailability ranges.
* ``unavailable remove YYYY-MM-DD YYYY-MM-DD`` — remove a previously stored range.
"""

from __future__ import annotations

import datetime
import logging
from typing import TYPE_CHECKING

from nf_core_bot.calendar.generator import safe_regenerate_calendars
from nf_core_bot.commands.oncall.helpers import (
    current_week_start,
    format_date_range,
    format_week_range,
    parse_date_arg,
    today_iso,
)
from nf_core_bot.commands.oncall.skip import find_skip_replacement
from nf_core_bot.db.oncall import (
    add_to_queue_front,
    add_unavailability,
    list_roster,
    list_unavailability,
    remove_unavailability,
    update_roster_assignment,
)

if TYPE_CHECKING:
    from slack_bolt.context.respond.async_respond import AsyncRespond as Respond
    from slack_sdk.web.async_client import AsyncWebClient

logger = logging.getLogger(__name__)

USAGE = (
    "Usage:\n"
    "  `/nf-core on-call unavailable YYYY-MM-DD YYYY-MM-DD` — mark a date range as unavailable\n"
    "  `/nf-core on-call unavailable list` — list your unavailable date ranges\n"
    "  `/nf-core on-call unavailable remove YYYY-MM-DD YYYY-MM-DD` — remove a date range"
)


async def handle_oncall_unavailable(
    respond: Respond,
    client: AsyncWebClient,
    user_id: str,
    args: list[str],
) -> None:
    """Dispatch to the correct unavailable subcommand based on *args*."""

    if not args:
        await respond(text=USAGE, response_type="ephemeral")
        return

    sub = args[0].lower()
    if sub == "list":
        await _handle_list(respond, user_id)
        return
    if sub == "remove":
        await _handle_remove(respond, user_id, args[1:])
        return

    await _handle_add(respond, client, user_id, args)


async def _handle_add(
    respond: Respond,
    client: AsyncWebClient,
    user_id: str,
    args: list[str],
) -> None:
    """Mark the caller as unavailable between two dates (inclusive)."""

    if len(args) < 2:
        await respond(text=USAGE, response_type="ephemeral")
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

    msg_parts: list[str] = [f":calendar: Marked you as unavailable *{format_date_range(start_str, end_str)}*."]

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

    # Regenerate calendars if any weeks were reassigned
    if my_overlapping:
        await safe_regenerate_calendars(client)


async def _handle_list(respond: Respond, user_id: str) -> None:
    """Show the caller's stored unavailability ranges (only current/future)."""

    today = today_iso()
    entries = await list_unavailability(user_id)
    upcoming = sorted((e for e in entries if e["end_date"] >= today), key=lambda e: e["start_date"])

    if not upcoming:
        await respond(
            text="You have no upcoming unavailable date ranges.",
            response_type="ephemeral",
        )
        return

    lines = [
        f"• *{format_date_range(e['start_date'], e['end_date'])}*  `{e['start_date']} {e['end_date']}`"
        for e in upcoming
    ]
    header = ":calendar: *Your upcoming unavailable date ranges:*\n\n"
    footer = (
        "\n\nTo remove a range, run "
        "`/nf-core on-call unavailable remove YYYY-MM-DD YYYY-MM-DD` "
        "with the dates shown in backticks."
    )
    await respond(text=header + "\n".join(lines) + footer, response_type="ephemeral")


async def _handle_remove(respond: Respond, user_id: str, args: list[str]) -> None:
    """Remove a stored unavailability range matching the given start/end dates."""

    if len(args) < 2:
        await respond(
            text="Usage: `/nf-core on-call unavailable remove YYYY-MM-DD YYYY-MM-DD`",
            response_type="ephemeral",
        )
        return

    try:
        start = parse_date_arg(args[0])
        end = parse_date_arg(args[1])
    except ValueError as exc:
        await respond(text=str(exc), response_type="ephemeral")
        return

    start_str = start.isoformat()
    end_str = end.isoformat()

    try:
        await remove_unavailability(user_id, start_str, end_str)
    except ValueError:
        await respond(
            text=(
                f"No unavailability range found for *{format_date_range(start_str, end_str)}*. "
                "Run `/nf-core on-call unavailable list` to see your ranges."
            ),
            response_type="ephemeral",
        )
        return

    await respond(
        text=f":white_check_mark: Removed unavailability *{format_date_range(start_str, end_str)}*.",
        response_type="ephemeral",
    )


def _week_overlaps(week_start: str, range_start: str, range_end: str) -> bool:
    """Check if a week (Mon–Sun) overlaps with a date range."""
    ws = datetime.date.fromisoformat(week_start)
    we = ws + datetime.timedelta(days=6)
    rs = datetime.date.fromisoformat(range_start)
    re_ = datetime.date.fromisoformat(range_end)
    return ws <= re_ and we >= rs
