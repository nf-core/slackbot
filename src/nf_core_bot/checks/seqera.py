"""Seqera Platform access management.

Access is granted through named *groups* (see :data:`SEQERA_GROUPS` /
:func:`seqera_groups`): each maps a friendly name to a Seqera target, either a
workspace (with a role) or an organisation team. The joiner auto-sync in
``commands/github/invite_flow.py`` adds people to ``megatests``; the
``/nf-core seqera`` command (``commands/seqera/``) adds, removes and lists
access for any group.

Every add is recorded in DynamoDB so ``list``, ``remove`` and the weekly
removal job (``scheduler/seqera_jobs.py``) know which access the bot manages.

API reference: https://cloud.seqera.io/openapi/seqera-api-latest.yml
(``CreateWorkspaceParticipant`` / ``DeleteWorkspaceParticipant`` /
``CreateOrganizationTeamMember`` / ``DeleteOrganizationTeamMember``).
"""

from __future__ import annotations

import enum
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import httpx

from nf_core_bot import config
from nf_core_bot.db.seqera import SeqeraMember, delete_member, get_member, put_member

if TYPE_CHECKING:
    from slack_sdk.web.async_client import AsyncWebClient

logger = logging.getLogger(__name__)

SEQERA_API_URL = "https://api.cloud.seqera.io"

MEGATESTS = "megatests"


class SeqeraStatus(enum.Enum):
    """Why an add or remove did or didn't happen."""

    ADDED = "added"
    ALREADY_PARTICIPANT = "already_participant"
    REMOVED = "removed"
    NOT_MANAGED = "not_managed"
    UNKNOWN_GROUP = "unknown_group"
    NOT_CONFIGURED = "not_configured"
    NO_EMAIL = "no_email"
    NO_ACCOUNT = "no_account"
    API_ERROR = "api_error"


@dataclass
class SeqeraResult:
    """Outcome of a Seqera add or remove."""

    status: SeqeraStatus
    message: str
    email: str | None = None

    @property
    def has_access(self) -> bool:
        """``True`` when the user is now in the group."""
        return self.status in (SeqeraStatus.ADDED, SeqeraStatus.ALREADY_PARTICIPANT)


@dataclass(frozen=True)
class SeqeraGroup:
    """A Seqera access target: a workspace with a role, or an organisation team.

    Set either ``workspace_id`` (and ``role``) or ``team_id``.
    """

    description: str
    workspace_id: str | None = None
    role: str | None = None
    team_id: str | None = None

    @property
    def target_key(self) -> str | None:
        """DynamoDB key for this target: ``<workspace-id>`` or ``TEAM#<team-id>``; ``None`` if unset."""
        if self.workspace_id:
            return self.workspace_id
        if self.team_id:
            return f"TEAM#{self.team_id}"
        return None


# Groups beyond megatests, keyed by the name used in ``/nf-core seqera``.
# IDs are the numeric Seqera IDs, as strings. Changes go through PR review.
# For example:
#   "maintainers": SeqeraGroup("nf-core maintainers team", team_id="1234"),
#   "dev": SeqeraGroup("nf-core/dev workspace (launch)", workspace_id="5678", role="launch"),
SEQERA_GROUPS: dict[str, SeqeraGroup] = {}


def seqera_groups() -> dict[str, SeqeraGroup]:
    """Return every group by name.

    ``megatests`` keeps its workspace ID and role in config (the
    ``SEQERA_WORKSPACE_ID`` param and ``SEQERA_WORKSPACE_ROLE``), as set up for
    the joiner auto-sync. The rest come from :data:`SEQERA_GROUPS`.
    """
    return {
        MEGATESTS: SeqeraGroup(
            "nf-core/megatests workspace (read-only)",
            workspace_id=config.SEQERA_WORKSPACE_ID,
            role=config.SEQERA_WORKSPACE_ROLE,
        ),
        **SEQERA_GROUPS,
    }


@dataclass
class _Settings:
    token: str
    org_id: str


def _settings() -> _Settings | None:
    """Return the org-wide Seqera settings, or ``None`` when Seqera isn't configured."""
    token = config.SEQERA_TOKEN
    org_id = config.SEQERA_ORG_ID
    if not (token and org_id):
        return None
    return _Settings(token=token, org_id=org_id)


def removal_dry_run() -> bool:
    """``True`` when the weekly removal job should only log (the default)."""
    return (config.SEQERA_REMOVAL_DRY_RUN or "true").strip().lower() not in ("0", "false", "no", "off")


def _participants_url(settings: _Settings, workspace_id: str) -> str:
    return f"{SEQERA_API_URL}/orgs/{settings.org_id}/workspaces/{workspace_id}/participants"


def _team_members_url(settings: _Settings, team_id: str) -> str:
    return f"{SEQERA_API_URL}/orgs/{settings.org_id}/teams/{team_id}/members"


def _error_message(resp: httpx.Response) -> str:
    """Pull ``message`` out of a Seqera ``ErrorResponse``, falling back to the raw body."""
    try:
        body = resp.json()
    except ValueError:
        return resp.text
    if isinstance(body, dict) and body.get("message"):
        return str(body["message"])
    return resp.text


async def _slack_email(client: AsyncWebClient, slack_user_id: str) -> str | None:
    response: Any = await client.users_info(user=slack_user_id)
    email: str | None = response.get("user", {}).get("profile", {}).get("email")
    return email


async def add_to_group(
    client: AsyncWebClient,
    slack_user_id: str,
    github_username: str,
    group_name: str,
    email: str | None = None,
) -> SeqeraResult:
    """Add a Slack user to the Seqera group *group_name*.

    *email* is the user's Seqera Platform email, if known; otherwise their
    Slack email is used. Successful adds are recorded in DynamoDB. Never
    raises for HTTP errors — the reason is returned in the
    :class:`SeqeraResult` instead.
    """
    group = seqera_groups().get(group_name)
    if group is None:
        return SeqeraResult(SeqeraStatus.UNKNOWN_GROUP, f"there is no Seqera group called `{group_name}`")

    settings = _settings()
    target_key = group.target_key
    if settings is None or target_key is None:
        logger.info("Seqera group %s is not configured; skipping user %s", group_name, slack_user_id)
        return SeqeraResult(SeqeraStatus.NOT_CONFIGURED, f"the Seqera group `{group_name}` is not configured")

    if not email:
        email = await _slack_email(client, slack_user_id)
    if not email:
        logger.warning("Slack user %s has no visible email; cannot add to Seqera", slack_user_id)
        return SeqeraResult(SeqeraStatus.NO_EMAIL, "no email address was found on their Slack profile")

    headers = {"Authorization": f"Bearer {settings.token}"}
    try:
        async with httpx.AsyncClient(timeout=15) as http:
            if group.workspace_id:
                resp = await http.put(
                    f"{_participants_url(settings, group.workspace_id)}/add",
                    headers=headers,
                    json={"userNameOrEmail": email, "role": group.role},
                )
            else:
                resp = await http.post(
                    _team_members_url(settings, str(group.team_id)),
                    headers=headers,
                    json={"userNameOrEmail": email},
                )
    except httpx.HTTPError as e:
        logger.exception("Network error adding Slack user %s to Seqera group %s", slack_user_id, group_name)
        return SeqeraResult(SeqeraStatus.API_ERROR, f"could not reach the Seqera API ({type(e).__name__})", email)

    if resp.status_code == 409:
        logger.info("Slack user %s (%s) is already in Seqera group %s", slack_user_id, email, group_name)
        return SeqeraResult(SeqeraStatus.ALREADY_PARTICIPANT, f"already in `{group_name}`", email)

    if resp.status_code == 404:
        logger.warning("No Seqera account for Slack user %s (%s): %s", slack_user_id, email, _error_message(resp))
        return SeqeraResult(SeqeraStatus.NO_ACCOUNT, f"no Seqera Platform account was found for `{email}`", email)

    if not resp.is_success:
        detail = _error_message(resp)
        logger.warning(
            "Seqera add to %s failed for %s: HTTP %s: %s", group_name, slack_user_id, resp.status_code, detail
        )
        return SeqeraResult(SeqeraStatus.API_ERROR, f"the Seqera API returned HTTP {resp.status_code}: {detail}", email)

    logger.info("Added Slack user %s to Seqera group %s", slack_user_id, group_name)
    body = resp.json()
    if group.workspace_id:
        seqera_id = (body.get("participant") or {}).get("participantId")
    else:
        seqera_id = (body.get("member") or {}).get("memberId")
    if seqera_id is None:
        logger.warning("Seqera add for %s to %s returned no ID; not recording it", slack_user_id, group_name)
    else:
        try:
            await put_member(target_key, slack_user_id, github_username, email, int(seqera_id), group=group_name)
        except Exception:
            # The add itself worked; failing to record only means the bot
            # won't manage this person's access.
            logger.exception("Failed to record Seqera add for Slack user %s", slack_user_id)
    return SeqeraResult(SeqeraStatus.ADDED, f"added to `{group_name}`", email)


async def add_to_megatests(
    client: AsyncWebClient,
    slack_user_id: str,
    github_username: str,
    email: str | None = None,
) -> SeqeraResult:
    """Add a Slack user to the megatests workspace (the joiner auto-sync)."""
    return await add_to_group(client, slack_user_id, github_username, MEGATESTS, email)


async def remove_record(group: SeqeraGroup, member: SeqeraMember) -> None:
    """Remove a recorded member from *group* in Seqera, then delete the record.

    Seqera reporting them as already gone (404) counts as removed. Raises
    ``RuntimeError`` when Seqera isn't configured or the API call fails; the
    record is kept in that case.
    """
    settings = _settings()
    if settings is None or group.target_key is None:
        raise RuntimeError("Seqera group is not configured")

    if group.workspace_id:
        url = f"{_participants_url(settings, group.workspace_id)}/{member.participant_id}"
    else:
        url = f"{_team_members_url(settings, str(group.team_id))}/{member.participant_id}/delete"

    async with httpx.AsyncClient(timeout=15) as http:
        resp = await http.delete(url, headers={"Authorization": f"Bearer {settings.token}"})
    if not (resp.is_success or resp.status_code == 404):
        raise RuntimeError(f"Seqera API returned HTTP {resp.status_code}: {_error_message(resp)}")
    await delete_member(group.target_key, member.slack_user_id)


async def remove_from_group(slack_user_id: str, group_name: str) -> SeqeraResult:
    """Remove a Slack user from the Seqera group *group_name*.

    Only access the bot recorded can be removed this way; anything else is
    reported as :attr:`SeqeraStatus.NOT_MANAGED`. Never raises — the reason is
    returned in the :class:`SeqeraResult` instead.
    """
    group = seqera_groups().get(group_name)
    if group is None:
        return SeqeraResult(SeqeraStatus.UNKNOWN_GROUP, f"there is no Seqera group called `{group_name}`")
    target_key = group.target_key
    if _settings() is None or target_key is None:
        return SeqeraResult(SeqeraStatus.NOT_CONFIGURED, f"the Seqera group `{group_name}` is not configured")

    member = await get_member(target_key, slack_user_id)
    if member is None:
        return SeqeraResult(
            SeqeraStatus.NOT_MANAGED,
            f"the bot has no record of adding them to `{group_name}`; remove them in Seqera Platform instead",
        )

    try:
        await remove_record(group, member)
    except Exception as e:
        logger.exception("Failed to remove Slack user %s from Seqera group %s", slack_user_id, group_name)
        return SeqeraResult(SeqeraStatus.API_ERROR, str(e), member.email)
    logger.info("Removed Slack user %s from Seqera group %s", slack_user_id, group_name)
    return SeqeraResult(SeqeraStatus.REMOVED, f"removed from `{group_name}`", member.email)


async def groups_for_user(slack_user_id: str) -> list[tuple[str, SeqeraMember]]:
    """Return ``(group name, record)`` for every configured group the bot added *slack_user_id* to."""
    found: list[tuple[str, SeqeraMember]] = []
    for name, group in seqera_groups().items():
        if group.target_key is None:
            continue
        member = await get_member(group.target_key, slack_user_id)
        if member is not None:
            found.append((name, member))
    return found
