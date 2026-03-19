"""Context-aware help — shows only commands the user has permission for."""

from __future__ import annotations

from typing import TYPE_CHECKING

from nf_core_bot.forms.loader import get_active_form
from nf_core_bot.permissions.checks import is_core_team, is_organiser_any_site

if TYPE_CHECKING:
    from slack_bolt.context.ack.async_ack import AsyncAck as Ack
    from slack_bolt.context.respond.async_respond import AsyncRespond as Respond
    from slack_sdk.web.async_client import AsyncWebClient

# ── Definitions ──────────────────────────────────────────────────────

# Each entry: (command string, description, min_role)
# min_role: "all" | "organiser" | "admin"
HACKATHON_COMMANDS: list[tuple[str, str, str]] = [
    ("list", "List hackathons", "all"),
    ("register", "Register for the active hackathon", "all"),
    ("edit", "Edit your registration", "all"),
    ("cancel", "Cancel your registration", "all"),
    ("sites", "List sites, organisers, and registration counts", "all"),
    ("export", "Export all registrations as CSV", "organiser"),
    ("admin list", "List all hackathons (incl. draft/archived)", "admin"),
    ("admin preview", "Preview the registration form", "admin"),
    ("admin add-site", "Add a new site (opens a form)", "admin"),
    ("admin edit-site", "Edit a site (opens a form)", "admin"),
]

GITHUB_COMMANDS: list[tuple[str, str, str]] = [
    ("github add-member @user", "Invite a Slack user to nf-core GitHub org", "admin"),
    ("github add-member <username>", "Invite a GitHub user to nf-core GitHub org", "admin"),
]

ONCALL_COMMANDS: list[tuple[str, str, str]] = [
    ("on-call list", "Show the upcoming on-call schedule", "admin"),
    ("on-call me", "Show your upcoming on-call dates", "admin"),
    ("on-call switch", "Swap your next on-call week with the person after you", "admin"),
    ("on-call switch YYYY-MM-DD", "Swap your next on-call week with the specified week", "admin"),
    ("on-call skip", "Skip your next on-call week (a replacement is assigned)", "admin"),
    ("on-call unavailable YYYY-MM-DD YYYY-MM-DD", "Mark yourself as unavailable for a date range", "admin"),
    ("on-call reboot", "Wipe and rebuild the on-call schedule from scratch", "admin"),
]

GENERAL_COMMANDS: list[tuple[str, str, str]] = [
    ("help", "Show this help message", "all"),
    ("on-call help", "Show on-call rotation commands (@core-team only)", "admin"),
    ("github help", "Show GitHub commands (@core-team only)", "admin"),
]


def _format_commands(
    cmds: list[tuple[str, str, str]],
    prefix: str = "/nf-core",
) -> str:
    """Render a list of commands as a Slack mrkdwn string."""
    lines: list[str] = []
    for cmd, desc, _ in cmds:
        display = f"  `{prefix} {cmd}`" if cmd else f"  `{prefix}`"
        lines.append(f"{display} — {desc}")
    return "\n".join(lines)


async def handle_help(
    ack: Ack,
    respond: Respond,
    client: AsyncWebClient,
    user_id: str,
) -> None:
    """Top-level help: ``/nf-core help``."""
    await ack()

    admin = await is_core_team(client, user_id)

    visible: list[tuple[str, str, str]] = []
    for cmd, desc, role in GENERAL_COMMANDS:
        if (role == "all") or (role == "admin" and admin):
            visible.append((cmd, desc, role))

    sections: list[str] = ["*nf-core bot — available commands*\n"]
    sections.append(_format_commands(visible))
    sections.append("\nRun `/hackathon help` for hackathon commands.")

    await respond("\n".join(sections), response_type="ephemeral")


async def handle_hackathon_help(
    ack: Ack,
    respond: Respond,
    client: AsyncWebClient,
    user_id: str,
) -> None:
    """Hackathon help: ``/hackathon help``.

    Shows only the commands the calling user has access to.
    """
    await ack()

    admin = await is_core_team(client, user_id)

    # Show organiser commands if the user is admin or a site organiser for
    # the currently active hackathon.
    organiser = admin
    if not organiser:
        try:
            active = get_active_form()
            if active:
                organiser = await is_organiser_any_site(user_id, active["hackathon_id"])
        except Exception:
            pass  # DynamoDB unavailable — hide organiser commands

    visible: list[tuple[str, str, str]] = []
    for cmd, desc, role in HACKATHON_COMMANDS:
        if (role == "all") or (role == "organiser" and (organiser or admin)) or (role == "admin" and admin):
            visible.append((cmd, desc, role))

    sections = ["*Hackathon commands*\n"]
    sections.append(_format_commands(visible, prefix="/hackathon"))

    await respond("\n".join(sections), response_type="ephemeral")


async def handle_github_help(
    ack: Ack,
    respond: Respond,
    client: AsyncWebClient,
    user_id: str,
) -> None:
    """GitHub-scoped help: ``/nf-core github help``.

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


async def handle_oncall_help(
    respond: Respond,
) -> None:
    """On-call help: ``/nf-core on-call help``.

    Only visible to ``@core-team`` members (permission checked in router).
    """
    sections = ["*On-call rotation commands* (`@core-team` only)\n"]
    sections.append(_format_commands(ONCALL_COMMANDS))

    await respond("\n".join(sections), response_type="ephemeral")
