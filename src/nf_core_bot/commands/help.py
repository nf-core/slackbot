"""Context-aware help — shows only commands the user has permission for."""

from __future__ import annotations

from typing import TYPE_CHECKING

from nf_core_bot import config
from nf_core_bot.permissions.checks import is_core_team

if TYPE_CHECKING:
    from slack_bolt.context.ack.async_ack import AsyncAck as Ack
    from slack_bolt.context.respond.async_respond import AsyncRespond as Respond
    from slack_sdk.web.async_client import AsyncWebClient

# ── Definitions ──────────────────────────────────────────────────────

# Each entry: (command string, description, min_role)
# min_role: "all" | "organiser" | "admin"
HACKATHON_COMMANDS: list[tuple[str, str, str]] = [
    ("hackathon register", "Register for the active hackathon", "all"),
    ("hackathon edit", "Edit your registration", "all"),
    ("hackathon cancel", "Cancel your registration", "all"),
    ("hackathon attendees [site]", "List attendees (optionally by site)", "organiser"),
    ("hackathon admin create <id>", "Create a new hackathon", "admin"),
    ("hackathon admin open <id>", "Open registration", "admin"),
    ("hackathon admin close <id>", "Close registration", "admin"),
    ("hackathon admin archive <id>", "Archive a hackathon", "admin"),
    ("hackathon admin list", "List all hackathons", "admin"),
    ("hackathon admin add-site <hackathon> <site>", "Add a local site", "admin"),
    ("hackathon admin remove-site <hackathon> <site>", "Remove a local site", "admin"),
    ("hackathon admin list-sites <hackathon>", "List sites for a hackathon", "admin"),
    ("hackathon admin add-organiser <hackathon> <site> @user", "Add a site organiser", "admin"),
    ("hackathon admin remove-organiser <hackathon> <site> @user", "Remove a site organiser", "admin"),
]

GENERAL_COMMANDS: list[tuple[str, str, str]] = [
    ("help", "Show this help message", "all"),
    ("hackathon help", "Show hackathon commands", "all"),
]


def _format_commands(cmds: list[tuple[str, str, str]]) -> str:
    """Render a list of commands as a Slack mrkdwn string."""
    lines: list[str] = []
    for cmd, desc, _ in cmds:
        lines.append(f"  `/nf-core-bot {cmd}` — {desc}")
    return "\n".join(lines)


async def handle_help(
    ack: Ack,
    respond: Respond,
    client: AsyncWebClient,
    user_id: str,
) -> None:
    """Top-level help: ``/nf-core-bot help``."""
    await ack()

    sections: list[str] = ["*nf-core bot — available commands*\n"]
    sections.append(_format_commands(GENERAL_COMMANDS))
    sections.append("\nRun `/nf-core-bot hackathon help` for hackathon commands.")

    await respond("\n".join(sections), response_type="ephemeral")


async def handle_hackathon_help(
    ack: Ack,
    respond: Respond,
    client: AsyncWebClient,
    user_id: str,
) -> None:
    """Hackathon-scoped help: ``/nf-core-bot hackathon help``.

    Shows only the commands the calling user has access to.
    """
    await ack()

    usergroup = config.CORE_TEAM_USERGROUP_HANDLE
    assert usergroup is not None  # has default
    admin = await is_core_team(client, user_id, usergroup)

    # For organiser check we'd need a hackathon id; show organiser commands
    # if the user is an admin (they implicitly have organiser access) or if
    # they are an organiser on any currently active hackathon.
    organiser = admin  # TODO: also check is_organiser_any_site once active hackathon lookup exists

    visible: list[tuple[str, str, str]] = []
    for cmd, desc, role in HACKATHON_COMMANDS:
        if role == "all" or role == "organiser" and (organiser or admin) or role == "admin" and admin:
            visible.append((cmd, desc, role))

    sections = ["*Hackathon commands*\n"]
    sections.append(_format_commands(visible))

    await respond("\n".join(sections), response_type="ephemeral")
