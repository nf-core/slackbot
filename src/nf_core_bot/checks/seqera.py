"""Seqera Platform workspace access for nf-core joiners.

New joiners are added to the configured workspace (``nf-core/megatests``) with
a read-only custom role, and each add is recorded in DynamoDB so the weekly
removal job (``scheduler/seqera_jobs.py``) can take access away again when
someone leaves the nf-core GitHub org.

API reference: https://cloud.seqera.io/openapi/seqera-api-latest.yml
(``CreateWorkspaceParticipant`` / ``DeleteWorkspaceParticipant``).
"""

from __future__ import annotations

import enum
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import httpx

from nf_core_bot import config
from nf_core_bot.db.seqera import put_member

if TYPE_CHECKING:
    from slack_sdk.web.async_client import AsyncWebClient

logger = logging.getLogger(__name__)

SEQERA_API_URL = "https://api.cloud.seqera.io"


class SeqeraStatus(enum.Enum):
    """Why a workspace add did or didn't happen."""

    ADDED = "added"
    ALREADY_PARTICIPANT = "already_participant"
    NOT_CONFIGURED = "not_configured"
    NO_EMAIL = "no_email"
    NO_ACCOUNT = "no_account"
    API_ERROR = "api_error"


@dataclass
class SeqeraResult:
    """Outcome of a Seqera workspace add."""

    status: SeqeraStatus
    message: str
    email: str | None = None

    @property
    def has_access(self) -> bool:
        """``True`` when the user is now a workspace participant."""
        return self.status in (SeqeraStatus.ADDED, SeqeraStatus.ALREADY_PARTICIPANT)


@dataclass
class _Settings:
    token: str
    org_id: str
    workspace_id: str


def _settings() -> _Settings | None:
    """Return the Seqera settings, or ``None`` when sync isn't configured."""
    token = config.SEQERA_TOKEN
    org_id = config.SEQERA_ORG_ID
    workspace_id = config.SEQERA_WORKSPACE_ID
    if not (token and org_id and workspace_id):
        return None
    return _Settings(token=token, org_id=org_id, workspace_id=workspace_id)


def removal_dry_run() -> bool:
    """``True`` when the weekly removal job should only log (the default)."""
    return (config.SEQERA_REMOVAL_DRY_RUN or "true").strip().lower() not in ("0", "false", "no", "off")


def _participants_url(settings: _Settings) -> str:
    return f"{SEQERA_API_URL}/orgs/{settings.org_id}/workspaces/{settings.workspace_id}/participants"


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


async def _is_participant(settings: _Settings, email: str) -> bool:
    """Return ``True`` if *email* is already a participant of the workspace.

    ``GET .../participants?search=<email>`` — used to tell a duplicate apart
    from the other 409 case ("collaborator not permitted for organization
    with active SSO"). Raises on an HTTP error.
    """
    async with httpx.AsyncClient(timeout=15) as http:
        resp = await http.get(
            _participants_url(settings),
            headers={"Authorization": f"Bearer {settings.token}"},
            params={"search": email},
        )
    resp.raise_for_status()
    participants = resp.json().get("participants") or []
    return any((p.get("email") or "").lower() == email.lower() for p in participants)


async def add_to_megatests(
    client: AsyncWebClient,
    slack_user_id: str,
    github_username: str,
    email: str | None = None,
) -> SeqeraResult:
    """Add a Slack user to the Seqera workspace with the configured role.

    *email* is the Seqera Platform email from the invitation form, if given;
    otherwise the user's Slack email is used. Successful adds are recorded in
    DynamoDB for the removal job. Never raises for HTTP errors — the reason is
    returned in the :class:`SeqeraResult` instead.
    """
    settings = _settings()
    if settings is None:
        logger.info("Seqera workspace sync is not configured; skipping user %s", slack_user_id)
        return SeqeraResult(SeqeraStatus.NOT_CONFIGURED, "Seqera workspace sync is not configured.")

    if not email:
        email = await _slack_email(client, slack_user_id)
    if not email:
        logger.warning("Slack user %s has no visible email; cannot sync to Seqera", slack_user_id)
        return SeqeraResult(SeqeraStatus.NO_EMAIL, "no email address was found on their Slack profile")

    try:
        async with httpx.AsyncClient(timeout=15) as http:
            resp = await http.put(
                f"{_participants_url(settings)}/add",
                headers={"Authorization": f"Bearer {settings.token}"},
                json={"userNameOrEmail": email, "role": config.SEQERA_WORKSPACE_ROLE},
            )
    except httpx.HTTPError as e:
        logger.exception("Network error adding Slack user %s to Seqera", slack_user_id)
        return SeqeraResult(SeqeraStatus.API_ERROR, f"could not reach the Seqera API ({type(e).__name__})", email)

    if resp.status_code == 409:
        # The spec lists 409 for both a duplicate and an SSO-blocked collaborator,
        # so confirm the user really is a participant before saying so.
        try:
            already = await _is_participant(settings, email)
        except httpx.HTTPError:
            logger.exception("Could not look up Seqera participant %s after a 409", email)
            already = False
        if already:
            logger.info(
                "Slack user %s (%s) is already in Seqera workspace %s", slack_user_id, email, settings.workspace_id
            )
            return SeqeraResult(SeqeraStatus.ALREADY_PARTICIPANT, "already a participant of the workspace", email)

    if resp.status_code == 404:
        # Not in the spec for this endpoint; unconfirmed whether Seqera uses it
        # for an unknown email, so pass its own message through as well.
        detail = _error_message(resp)
        logger.warning("No Seqera account for Slack user %s (%s): %s", slack_user_id, email, detail)
        return SeqeraResult(
            SeqeraStatus.NO_ACCOUNT, f"no Seqera Platform account was found for `{email}` ({detail})", email
        )

    if not resp.is_success:
        detail = _error_message(resp)
        logger.warning(
            "Seqera workspace sync failed for Slack user %s: HTTP %s: %s", slack_user_id, resp.status_code, detail
        )
        return SeqeraResult(SeqeraStatus.API_ERROR, f"the Seqera API returned HTTP {resp.status_code}: {detail}", email)

    logger.info("Added Slack user %s to Seqera workspace %s", slack_user_id, settings.workspace_id)
    participant_id = (resp.json().get("participant") or {}).get("participantId")
    if participant_id is None:
        logger.warning("Seqera add for %s returned no participantId; not recording it", slack_user_id)
    else:
        try:
            await put_member(settings.workspace_id, slack_user_id, github_username, email, int(participant_id))
        except Exception:
            # The add itself worked; failing to record only means the removal
            # job won't manage this person.
            logger.exception("Failed to record Seqera participant for Slack user %s", slack_user_id)
    return SeqeraResult(SeqeraStatus.ADDED, "added to the workspace", email)


async def remove_participant(participant_id: int) -> bool:
    """Remove a participant from the configured workspace.

    Returns ``True`` when the participant is gone (including when Seqera
    reports they were already removed). Raises ``RuntimeError`` when sync
    isn't configured or the API call fails.
    """
    settings = _settings()
    if settings is None:
        raise RuntimeError("Seqera workspace sync is not configured")

    async with httpx.AsyncClient(timeout=15) as http:
        resp = await http.delete(
            f"{_participants_url(settings)}/{participant_id}",
            headers={"Authorization": f"Bearer {settings.token}"},
        )
    if resp.is_success or resp.status_code == 404:
        return True
    raise RuntimeError(f"Seqera API returned HTTP {resp.status_code}: {_error_message(resp)}")
