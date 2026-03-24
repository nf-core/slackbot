"""``/nf-core on-call calendar [all|me]`` — share subscribable iCal URLs."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from nf_core_bot import config
from nf_core_bot.calendar.generator import get_calendar_url, safe_regenerate_calendars
from nf_core_bot.db.oncall import get_or_create_calendar_token

if TYPE_CHECKING:
    from slack_bolt.context.respond.async_respond import AsyncRespond as Respond
    from slack_sdk.web.async_client import AsyncWebClient

logger = logging.getLogger(__name__)


def _subscribe_instructions() -> str:
    """Return Slack mrkdwn with instructions for subscribing to the URL."""
    return (
        "\n\n*Subscribe in Google Calendar:*"
        "\n1. Open <https://calendar.google.com|Google Calendar>"
        "\n2. Click the *+* next to _Other calendars_ → *From URL*"
        "\n3. Paste this URL and click *Add calendar*"
        "\n\nGoogle Calendar refreshes subscribed calendars every 12–24 hours, "
        "so changes may take a while to appear."
        "\n\n*Other calendar apps:*"
        "\nMost calendar apps support subscribing via URL — look for "
        '"Add calendar by URL" or "Subscribe to calendar" and paste the link above.'
    )


async def handle_oncall_calendar(
    respond: Respond,
    client: AsyncWebClient,
    user_id: str,
    args: list[str],
) -> None:
    """Handle ``/nf-core on-call calendar [all|me]``."""
    if not config.CALENDAR_S3_BUCKET:
        await respond(
            "Calendar feeds are not configured. The `CALENDAR_S3_BUCKET` environment variable must be set.",
            response_type="ephemeral",
        )
        return

    sub = args[0].lower() if args else "help"

    if sub == "all":
        token = await get_or_create_calendar_token()
        url = get_calendar_url(token, "oncall-all.ics")
        if not url:
            await respond("Calendar URL could not be generated.", response_type="ephemeral")
            return

        # Fire-and-forget regeneration so the file exists (don't block the response)
        asyncio.create_task(safe_regenerate_calendars(client))

        await respond(
            f"*Global on-call calendar*\n\n"
            f"Subscribe to this URL to see who is on call each week:\n"
            f"`{url}`" + _subscribe_instructions(),
            response_type="ephemeral",
        )

    elif sub == "me":
        token = await get_or_create_calendar_token()
        url = get_calendar_url(token, f"oncall-{user_id}.ics")
        if not url:
            await respond("Calendar URL could not be generated.", response_type="ephemeral")
            return

        # Fire-and-forget regeneration so the file exists (don't block the response)
        asyncio.create_task(safe_regenerate_calendars(client))

        await respond(
            f"*Your on-call calendar*\n\n"
            f"Subscribe to this URL to see when you are on call:\n"
            f"`{url}`" + _subscribe_instructions(),
            response_type="ephemeral",
        )

    else:
        await respond(
            "*Usage:*\n"
            "  `/nf-core on-call calendar all` — global on-call calendar URL\n"
            "  `/nf-core on-call calendar me` — your personal on-call calendar URL",
            response_type="ephemeral",
        )
