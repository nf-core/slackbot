"""Parse the ``/nf-core`` slash command text and dispatch to handlers.

The single slash command ``/nf-core <subcommand> [args…]`` is split into
tokens here and routed to the appropriate handler module.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from nf_core_bot.commands.github.add_member import handle_add_member
from nf_core_bot.commands.hackathon.admin import (
    handle_admin_add_site,
    handle_admin_edit_site,
    handle_admin_list,
    handle_admin_preview,
    handle_export,
    handle_list_sites,
)
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
    "list": handle_admin_list,
    "preview": handle_admin_preview,
    "add-site": handle_admin_add_site,
    "edit-site": handle_admin_edit_site,
}


async def dispatch(
    ack: Ack,
    respond: Respond,
    client: AsyncWebClient,
    command: dict[str, str],
) -> None:
    """Route ``/nf-core <text>`` to the correct handler.

    This is the single callback registered on the ``/nf-core`` command
    in ``app.py``.
    """
    raw_text: str = command.get("text", "").strip()
    sub, rest = _parse_subcommand(raw_text)
    user_id: str = command["user_id"]

    command_name: str = command.get("command", "/nf-core")

    # ── Top-level commands ───────────────────────────────────────────
    if sub == "help":
        await handle_help(ack, respond, client, user_id, command_name=command_name)
        return

    # ── Hackathon commands ───────────────────────────────────────────
    if sub in ("hackathon", "hackathons", "hack", "h"):
        await _route_hackathon(ack, respond, client, user_id, command, rest)
        return

    # ── GitHub commands ──────────────────────────────────────────────
    if sub == "github":
        await _route_github(ack, respond, client, user_id, command, rest)
        return

    # ── Unknown ──────────────────────────────────────────────────────
    await ack()
    await respond(
        f"Unknown command: `{sub}`. Run `{command_name} help` for a list of commands.",
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
    """Dispatch ``/nf-core hackathon <sub> [args…]``."""
    command_name: str = command.get("command", "/nf-core")

    if not tokens or tokens[0].lower() == "help":
        await handle_hackathon_help(ack, respond, client, user_id, command_name=command_name)
        return

    sub = tokens[0].lower()
    if sub in ("a", "adm"):
        sub = "admin"
    rest = tokens[1:]

    # Build a body dict that handlers expect for trigger_id / user_id.
    body: dict[str, str] = {
        "trigger_id": command.get("trigger_id", ""),
        "user_id": user_id,
    }

    # Help hint adapts to the slash command used.
    help_hint = "/hackathon help" if command_name == "/hackathon" else "/nf-core hackathon help"

    if sub == "register":
        await handle_register(ack, respond, client, body)
    elif sub == "edit":
        await handle_edit(ack, respond, client, body)
    elif sub == "cancel":
        await handle_cancel(ack, respond, client, body)
    elif sub == "list":
        await handle_list(ack, respond, client, body)
    elif sub in ("sites", "list-sites"):
        await handle_list_sites(ack, respond, rest)
    elif sub == "export":
        await handle_export(ack, respond, client, body, rest)
    elif sub == "admin":
        await _route_admin(ack, respond, client, body, rest, help_hint=help_hint)
    else:
        await ack()
        await respond(
            f"Unknown hackathon command: `{sub}`. Run `{help_hint}` for options.",
            response_type="ephemeral",
        )


async def _route_admin(
    ack: Ack,
    respond: Respond,
    client: AsyncWebClient,
    body: dict[str, str],
    tokens: list[str],
    *,
    help_hint: str = "/nf-core hackathon help",
) -> None:
    """Dispatch ``/nf-core hackathon admin <sub> [args…]``."""
    if not tokens:
        await ack()
        await respond(
            f"Missing admin subcommand. Run `{help_hint}` for options.",
            response_type="ephemeral",
        )
        return

    sub = tokens[0].lower()
    rest = tokens[1:]

    handler = _ADMIN_DISPATCH.get(sub)
    if handler is None:
        await ack()
        await respond(
            f"Unknown admin command: `{sub}`. Run `{help_hint}` for options.",
            response_type="ephemeral",
        )
        return

    # Dispatch: handlers have varying signatures.
    if sub == "list":
        await handler(ack, respond)  # type: ignore[operator]
    else:
        await handler(ack, respond, client, body, rest)  # type: ignore[operator]


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
    """Dispatch ``/nf-core github <sub> [args…]``."""
    command_name: str = command.get("command", "/nf-core")

    if not tokens or tokens[0].lower() == "help":
        await handle_github_help(ack, respond, client, user_id, command_name=command_name)
        return

    sub = tokens[0].lower()
    rest = tokens[1:]

    handler = _GITHUB_DISPATCH.get(sub)
    if handler is None:
        await ack()
        await respond(
            f"Unknown github command: `{sub}`. Run `{command_name} github help` for options.",
            response_type="ephemeral",
        )
        return

    await handler(ack, respond, client, user_id, command, rest)  # type: ignore[operator]
