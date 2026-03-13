"""Context-aware help — shows only commands the user has permission for."""

from __future__ import annotations

from typing import TYPE_CHECKING

from nf_core_bot.db.hackathons import get_active_hackathon
from nf_core_bot.permissions.checks import is_core_team, is_organiser_any_site

if TYPE_CHECKING:
    from slack_bolt.context.ack.async_ack import AsyncAck as Ack
    from slack_bolt.context.respond.async_respond import AsyncRespond as Respond
    from slack_sdk.web.async_client import AsyncWebClient

# ── Definitions ──────────────────────────────────────────────────────

# Each entry: (command string, description, min_role)
# min_role: "all" | "organiser" | "admin"
HACKATHON_COMMANDS: list[tuple[str, str, str]] = [
    ("hackathon list", "List hackathons and your registration status", "all"),
    ("hackathon register", "Register for the active hackathon", "all"),
    ("hackathon edit", "Edit your registration", "all"),
    ("hackathon cancel", "Cancel your registration", "all"),
    ("hackathon attendees [hackathon-id]", "List attendees (optionally by site)", "organiser"),
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

GITHUB_COMMANDS: list[tuple[str, str, str]] = [
    ("github add-member @user", "Invite a Slack user to nf-core GitHub org", "admin"),
    ("github add-member <username>", "Invite a GitHub user to nf-core GitHub org", "admin"),
]

GENERAL_COMMANDS: list[tuple[str, str, str]] = [
    ("help", "Show this help message", "all"),
    ("hackathon help", "Show hackathon commands", "all"),
    ("github help", "Show GitHub commands (@core-team only)", "admin"),
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

    admin = await is_core_team(client, user_id)

    visible: list[tuple[str, str, str]] = []
    for cmd, desc, role in GENERAL_COMMANDS:
        if (role == "all") or (role == "admin" and admin):
            visible.append((cmd, desc, role))

    sections: list[str] = ["*nf-core bot — available commands*\n"]
    sections.append(_format_commands(visible))
    sections.append("\nRun `/nf-core-bot hackathon help` for hackathon commands.")
    if admin:
        sections.append("Run `/nf-core-bot github help` for GitHub commands.")

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

    admin = await is_core_team(client, user_id)

    # Show organiser commands if the user is admin or a site organiser for
    # the currently active hackathon.
    organiser = admin
    if not organiser:
        try:
            active = await get_active_hackathon()
            if active:
                organiser = await is_organiser_any_site(user_id, active["hackathon_id"])
        except Exception:
            pass  # DynamoDB unavailable — hide organiser commands

    visible: list[tuple[str, str, str]] = []
    for cmd, desc, role in HACKATHON_COMMANDS:
        if (role == "all") or (role == "organiser" and (organiser or admin)) or (role == "admin" and admin):
            visible.append((cmd, desc, role))

    sections = ["*Hackathon commands*\n"]
    sections.append(_format_commands(visible))

    await respond("\n".join(sections), response_type="ephemeral")


async def handle_github_help(
    ack: Ack,
    respond: Respond,
    client: AsyncWebClient,
    user_id: str,
) -> None:
    """GitHub-scoped help: ``/nf-core-bot github help``.

    Only visible to @core-team members.
    """
    await ack()

    admin = await is_core_team(client, user_id)

    if not admin:
        await respond(
            "Sorry, GitHub commands are restricted to `@core-team` members.",
            response_type="ephemeral",
        )
        return

    sections = ["*GitHub commands* (`@core-team` only)\n"]
    sections.append(_format_commands(GITHUB_COMMANDS))
    sections.append(
        "\nYou can also right-click any message and use *More actions → Add to GitHub org* "
        "to invite the message author."
    )

    await respond("\n".join(sections), response_type="ephemeral")
