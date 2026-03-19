"""``/nf-core on-call me`` — show the caller's upcoming on-call dates."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from nf_core_bot.commands.oncall.helpers import current_week_start, format_week_range
from nf_core_bot.db.oncall import list_roster

if TYPE_CHECKING:
    from slack_bolt.async_app import AsyncAck as Ack
    from slack_bolt.async_app import AsyncRespond as Respond

logger = logging.getLogger(__name__)


async def handle_oncall_me(ack: Ack, respond: Respond, user_id: str) -> None:
    """Show the calling user's upcoming on-call weeks."""
    await ack()

    items = await list_roster(from_date=current_week_start())
    my_weeks = [i for i in items if i.get("assigned_user_id") == user_id]

    if not my_weeks:
        await respond(
            text="You have no upcoming on-call weeks in the current schedule.",
            response_type="ephemeral",
        )
        return

    lines = [f"• *{format_week_range(w['week_start'])}*" for w in my_weeks]
    header = ":calendar: *Your upcoming on-call weeks:*\n\n"
    await respond(text=header + "\n".join(lines), response_type="ephemeral")
