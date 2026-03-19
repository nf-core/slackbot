"""``/nf-core on-call list`` — show the upcoming on-call schedule."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from nf_core_bot.commands.oncall.helpers import current_week_start, format_week_range
from nf_core_bot.db.oncall import list_roster

if TYPE_CHECKING:
    from slack_bolt.context.respond.async_respond import AsyncRespond as Respond

logger = logging.getLogger(__name__)

_STATUS_ICONS = {
    "scheduled": "",
    "swapped": " _(swapped)_",
    "skipped": " _(replacement)_",
    "completed": " _(done)_",
}


async def handle_oncall_list(respond: Respond) -> None:
    """Display the upcoming ~8 weeks of on-call assignments."""

    items = await list_roster(from_date=current_week_start())

    if not items:
        await respond(
            text="No on-call schedule found. The schedule will be created automatically on Monday.",
            response_type="ephemeral",
        )
        return

    lines: list[str] = []
    for item in items:
        week = format_week_range(item["week_start"])
        user = item.get("assigned_user_id")
        status_note = _STATUS_ICONS.get(item.get("status", ""), "")
        if user:
            lines.append(f"*{week}*  —  <@{user}>{status_note}")
        else:
            lines.append(f"*{week}*  —  _unassigned_")

    header = ":calendar: *On-call schedule*\n\n"
    await respond(text=header + "\n".join(lines), response_type="ephemeral")
