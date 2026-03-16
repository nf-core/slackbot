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
    ("hackathon list", "List hackathons", "all"),
    ("hackathon register", "Register for the active hackathon", "all"),
    ("hackathon edit", "Edit your registration", "all"),
    ("hackathon cancel", "Cancel your registration", "all"),
    ("hackathon sites [hackathon-id]", "List sites, organisers, and registration counts", "all"),
    ("hackathon export [hackathon-id]", "Export all registrations as CSV", "organiser"),
    ("hackathon admin list", "List all hackathons (incl. draft/archived)", "admin"),
    ("hackathon admin preview [hackathon-id]", "Preview the registration form", "admin"),
    ("hackathon admin add-site", "Add a new site (opens a form)", "admin"),
    ("hackathon admin edit-site", "Edit a site (opens a form)", "admin"),
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


def _format_commands(
    cmds: list[tuple[str, str, str]],
    prefix: str = "/nf-core",
    strip_namespace: str | None = None,
) -> str:
    """Render a list of commands as a Slack mrkdwn string.

    *strip_namespace* removes a leading namespace from each command
    string.  For example, when invoked via ``/hackathon``, set
    ``strip_namespace="hackathon"`` so that ``hackathon register``
    renders as ``/hackathon register`` rather than
    ``/hackathon hackathon register``.
    """
    lines: list[str] = []
    for cmd, desc, _ in cmds:
        if strip_namespace and cmd.startswith(strip_namespace):
            cmd = cmd[len(strip_namespace) :].lstrip()
            if not cmd:
                cmd = ""
        display = f"  `{prefix} {cmd}`" if cmd else f"  `{prefix}`"
        lines.append(f"{display} — {desc}")
    return "\n".join(lines)


async def handle_help(
    ack: Ack,
    respond: Respond,
    client: AsyncWebClient,
    user_id: str,
    command_name: str = "/nf-core",
) -> None:
    """Top-level help: ``/nf-core help``."""
    await ack()

    admin = await is_core_team(client, user_id)

    visible: list[tuple[str, str, str]] = []
    for cmd, desc, role in GENERAL_COMMANDS:
        if (role == "all") or (role == "admin" and admin):
            visible.append((cmd, desc, role))

    sections: list[str] = ["*nf-core bot — available commands*\n"]
    sections.append(_format_commands(visible, prefix=command_name))
    sections.append(f"\nRun `{command_name} hackathon help` for hackathon commands.")
    if admin:
        sections.append(f"Run `{command_name} github help` for GitHub commands.")

    await respond("\n".join(sections), response_type="ephemeral")


async def handle_hackathon_help(
    ack: Ack,
    respond: Respond,
    client: AsyncWebClient,
    user_id: str,
    command_name: str = "/nf-core",
) -> None:
    """Hackathon-scoped help: ``/nf-core hackathon help``.

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

    via_hackathon = command_name == "/hackathon"
    prefix = "/hackathon" if via_hackathon else "/nf-core"
    strip_ns = "hackathon" if via_hackathon else None

    sections = ["*Hackathon commands*\n"]
    sections.append(_format_commands(visible, prefix=prefix, strip_namespace=strip_ns))
    if not via_hackathon:
        sections.append("\n_Tip: you can use `h`, `hack`, or `hackathons` as shortcuts for `hackathon`._")

    await respond("\n".join(sections), response_type="ephemeral")


async def handle_github_help(
    ack: Ack,
    respond: Respond,
    client: AsyncWebClient,
    user_id: str,
    command_name: str = "/nf-core",
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
    sections.append(_format_commands(GITHUB_COMMANDS, prefix=command_name))
    sections.append(
        "\nYou can also right-click any message and use *More actions → Add to GitHub org* "
        "to invite the message author."
    )

    await respond("\n".join(sections), response_type="ephemeral")
