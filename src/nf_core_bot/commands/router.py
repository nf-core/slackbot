"""Parse the ``/nf-core-bot`` slash command text and dispatch to handlers.

The single slash command ``/nf-core-bot <subcommand> [args…]`` is split into
tokens here and routed to the appropriate handler module.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from nf_core_bot.commands.github.add_member import handle_add_member
from nf_core_bot.commands.hackathon.admin import (
    handle_admin_add_organiser,
    handle_admin_add_site,
    handle_admin_archive,
    handle_admin_close,
    handle_admin_create,
    handle_admin_list,
    handle_admin_list_sites,
    handle_admin_open,
    handle_admin_remove_organiser,
    handle_admin_remove_site,
)
from nf_core_bot.commands.hackathon.attendees import handle_attendees
from nf_core_bot.commands.hackathon.list_cmd import handle_list
from nf_core_bot.commands.hackathon.register import (
    handle_cancel,
    handle_edit,
    handle_register,
)
from nf_core_bot.commands.help import handle_github_help, handle_hackathon_help, handle_help

if TYPE_CHECKING:
    from slack_bolt.context.ack.async_ack import AsyncAck as Ack
    from slack_bolt.context.respond.async_respond import AsyncRespond as Respond
    from slack_sdk.web.async_client import AsyncWebClient

logger = logging.getLogger(__name__)


# ── Parsing helper ──────────────────────────────────────────────────


def _parse_subcommand(text: str) -> tuple[str, list[str]]:
    """Split raw slash-command text into ``(subcommand, rest_tokens)``.

    Returns ``("help", [])`` for empty input.
    """
    tokens = text.split() if text.strip() else []
    if not tokens:
        return ("help", [])
    return (tokens[0].lower(), tokens[1:])


# ── Admin subcommand dispatch table ─────────────────────────────────

_ADMIN_DISPATCH: dict[str, object] = {
    "create": handle_admin_create,
    "open": handle_admin_open,
    "close": handle_admin_close,
    "archive": handle_admin_archive,
    "list": handle_admin_list,
    "add-site": handle_admin_add_site,
    "remove-site": handle_admin_remove_site,
    "list-sites": handle_admin_list_sites,
    "add-organiser": handle_admin_add_organiser,
    "remove-organiser": handle_admin_remove_organiser,
}


async def dispatch(
    ack: Ack,
    respond: Respond,
    client: AsyncWebClient,
    command: dict[str, str],
) -> None:
    """Route ``/nf-core-bot <text>`` to the correct handler.

    This is the single callback registered on the ``/nf-core-bot`` command
    in ``app.py``.
    """
    raw_text: str = command.get("text", "").strip()
    sub, rest = _parse_subcommand(raw_text)
    user_id: str = command["user_id"]

    # ── Top-level commands ───────────────────────────────────────────
    if sub == "help":
        await handle_help(ack, respond, client, user_id)
        return

    # ── Hackathon commands ───────────────────────────────────────────
    if sub == "hackathon":
        await _route_hackathon(ack, respond, client, user_id, command, rest)
        return

    # ── GitHub commands ──────────────────────────────────────────────
    if sub == "github":
        await _route_github(ack, respond, client, user_id, command, rest)
        return

    # ── Unknown ──────────────────────────────────────────────────────
    await ack()
    await respond(
        f"Unknown command: `{sub}`. Run `/nf-core-bot help` for a list of commands.",
        response_type="ephemeral",
    )


async def _route_hackathon(
    ack: Ack,
    respond: Respond,
    client: AsyncWebClient,
    user_id: str,
    command: dict[str, str],
    tokens: list[str],
) -> None:
    """Dispatch ``/nf-core-bot hackathon <sub> [args…]``."""
    if not tokens or tokens[0].lower() == "help":
        await handle_hackathon_help(ack, respond, client, user_id)
        return

    sub = tokens[0].lower()
    rest = tokens[1:]

    # Build a body dict that handlers expect for trigger_id / user_id.
    body: dict[str, str] = {
        "trigger_id": command.get("trigger_id", ""),
        "user_id": user_id,
    }

    if sub == "register":
        await handle_register(ack, respond, client, body)
    elif sub == "edit":
        await handle_edit(ack, respond, client, body)
    elif sub == "cancel":
        await handle_cancel(ack, respond, client, body)
    elif sub == "list":
        await handle_list(ack, respond, client, body)
    elif sub == "attendees":
        await handle_attendees(ack, respond, client, body, rest)
    elif sub == "admin":
        await _route_admin(ack, respond, rest)
    else:
        await ack()
        await respond(
            f"Unknown hackathon command: `{sub}`. Run `/nf-core-bot hackathon help` for options.",
            response_type="ephemeral",
        )


async def _route_admin(
    ack: Ack,
    respond: Respond,
    tokens: list[str],
) -> None:
    """Dispatch ``/nf-core-bot hackathon admin <sub> [args…]``."""
    if not tokens:
        await ack()
        await respond(
            "Missing admin subcommand. Run `/nf-core-bot hackathon help` for options.",
            response_type="ephemeral",
        )
        return

    sub = tokens[0].lower()
    rest = tokens[1:]

    handler = _ADMIN_DISPATCH.get(sub)
    if handler is None:
        await ack()
        await respond(
            f"Unknown admin command: `{sub}`. Run `/nf-core-bot hackathon help` for options.",
            response_type="ephemeral",
        )
        return

    # ``handle_admin_list`` takes no extra args; the rest accept a list.
    if sub == "list":
        await handler(ack, respond)  # type: ignore[operator]
    else:
        await handler(ack, respond, rest)  # type: ignore[operator]


# ── GitHub dispatch ──────────────────────────────────────────────────

_GITHUB_DISPATCH: dict[str, object] = {
    "add-member": handle_add_member,
}


async def _route_github(
    ack: Ack,
    respond: Respond,
    client: AsyncWebClient,
    user_id: str,
    command: dict[str, str],
    tokens: list[str],
) -> None:
    """Dispatch ``/nf-core-bot github <sub> [args…]``."""
    if not tokens or tokens[0].lower() == "help":
        await handle_github_help(ack, respond, client, user_id)
        return

    sub = tokens[0].lower()
    rest = tokens[1:]

    handler = _GITHUB_DISPATCH.get(sub)
    if handler is None:
        await ack()
        await respond(
            f"Unknown github command: `{sub}`. Run `/nf-core-bot github help` for options.",
            response_type="ephemeral",
        )
        return

    await handler(ack, respond, client, user_id, command, rest)  # type: ignore[operator]
