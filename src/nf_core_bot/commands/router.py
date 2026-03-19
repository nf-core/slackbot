"""Parse slash-command text and dispatch to handlers.

Two slash commands share this router:

* ``/nf-core <subcommand>`` — top-level help, GitHub commands
* ``/hackathon <subcommand>`` — all hackathon commands

``app.py`` registers both commands and delegates to the appropriate
entry-point in this module (``dispatch`` for ``/nf-core``,
``dispatch_hackathon`` for ``/hackathon``).
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
from nf_core_bot.commands.help import handle_github_help, handle_hackathon_help, handle_help, handle_oncall_help
from nf_core_bot.commands.oncall.list_cmd import handle_oncall_list
from nf_core_bot.commands.oncall.me import handle_oncall_me
from nf_core_bot.commands.oncall.reboot import handle_oncall_reboot
from nf_core_bot.commands.oncall.skip import handle_oncall_skip
from nf_core_bot.commands.oncall.switch import handle_oncall_switch
from nf_core_bot.commands.oncall.unavailable import handle_oncall_unavailable
from nf_core_bot.permissions.checks import is_core_team

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

    Handles top-level help and GitHub commands only.
    Hackathon commands go through :func:`dispatch_hackathon`.
    """
    raw_text: str = command.get("text", "").strip()
    sub, rest = _parse_subcommand(raw_text)
    user_id: str = command["user_id"]

    # ── Top-level commands ───────────────────────────────────────────
    if sub == "help":
        await handle_help(ack, respond, client, user_id)
        return

    # ── GitHub commands ──────────────────────────────────────────────
    if sub == "github":
        await _route_github(ack, respond, client, user_id, command, rest)
        return

    # ── On-call commands ─────────────────────────────────────────────
    if sub == "on-call":
        await _route_oncall(ack, respond, client, user_id, rest)
        return

    # ── Unknown ──────────────────────────────────────────────────────
    await ack()
    await respond(
        f"Unknown command: `{sub}`. Run `/nf-core help` for a list of commands.",
        response_type="ephemeral",
    )


async def dispatch_hackathon(
    ack: Ack,
    respond: Respond,
    client: AsyncWebClient,
    command: dict[str, str],
) -> None:
    """Route ``/hackathon <text>`` to the correct handler."""
    raw_text: str = command.get("text", "").strip()
    user_id: str = command["user_id"]
    _, tokens = _parse_subcommand(raw_text)
    # _parse_subcommand returns ("help", []) for empty input, but for
    # /hackathon we want the first token as the subcommand directly.
    all_tokens = raw_text.split() if raw_text else []
    await _route_hackathon(ack, respond, client, user_id, command, all_tokens)


async def _route_hackathon(
    ack: Ack,
    respond: Respond,
    client: AsyncWebClient,
    user_id: str,
    command: dict[str, str],
    tokens: list[str],
) -> None:
    """Dispatch ``/hackathon <sub> [args…]``."""
    if not tokens or tokens[0].lower() == "help":
        await handle_hackathon_help(ack, respond, client, user_id)
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
        await _route_admin(ack, respond, client, body, rest)
    else:
        await ack()
        await respond(
            f"Unknown hackathon command: `{sub}`. Run `/hackathon help` for options.",
            response_type="ephemeral",
        )


async def _route_admin(
    ack: Ack,
    respond: Respond,
    client: AsyncWebClient,
    body: dict[str, str],
    tokens: list[str],
) -> None:
    """Dispatch ``/hackathon admin <sub> [args…]``."""
    if not tokens:
        await ack()
        await respond(
            "Missing admin subcommand. Run `/hackathon help` for options.",
            response_type="ephemeral",
        )
        return

    sub = tokens[0].lower()
    rest = tokens[1:]

    handler = _ADMIN_DISPATCH.get(sub)
    if handler is None:
        await ack()
        await respond(
            f"Unknown admin command: `{sub}`. Run `/hackathon help` for options.",
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
    if not tokens or tokens[0].lower() == "help":
        await handle_github_help(ack, respond, client, user_id)
        return

    sub = tokens[0].lower()
    rest = tokens[1:]

    handler = _GITHUB_DISPATCH.get(sub)
    if handler is None:
        await ack()
        await respond(
            f"Unknown github command: `{sub}`. Run `/nf-core github help` for options.",
            response_type="ephemeral",
        )
        return

    await handler(ack, respond, client, user_id, command, rest)  # type: ignore[operator]


# ── On-call dispatch ─────────────────────────────────────────────────

_ONCALL_DISPATCH: dict[str, object] = {
    "list": handle_oncall_list,
    "me": handle_oncall_me,
    "switch": handle_oncall_switch,
    "skip": handle_oncall_skip,
    "unavailable": handle_oncall_unavailable,
    "reboot": handle_oncall_reboot,
}


async def _route_oncall(
    ack: Ack,
    respond: Respond,
    client: AsyncWebClient,
    user_id: str,
    tokens: list[str],
) -> None:
    """Dispatch ``/nf-core on-call <sub> [args…]``.

    All on-call commands are restricted to ``@core-team`` members.
    """
    await ack()

    if not await is_core_team(client, user_id):
        await respond(
            "Sorry, on-call commands are restricted to `@core-team` members.",
            response_type="ephemeral",
        )
        return

    if not tokens or tokens[0].lower() == "help":
        await handle_oncall_help(respond)
        return

    sub = tokens[0].lower()
    rest = tokens[1:]

    handler = _ONCALL_DISPATCH.get(sub)
    if handler is None:
        await respond(
            f"Unknown on-call command: `{sub}`. Run `/nf-core on-call help` for options.",
            response_type="ephemeral",
        )
        return

    # Dispatch: handlers have varying signatures.
    if sub == "list":
        await handler(respond)  # type: ignore[operator]
    elif sub == "me":
        await handler(respond, user_id)  # type: ignore[operator]
    elif sub in ("switch", "unavailable"):
        await handler(respond, client, user_id, rest)  # type: ignore[operator]
    else:
        # skip, reboot: (respond, client, user_id)
        await handler(respond, client, user_id)  # type: ignore[operator]
