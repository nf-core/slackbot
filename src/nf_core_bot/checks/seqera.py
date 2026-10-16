"""Add nf-core joiners to the configured Seqera workspace."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import httpx

from nf_core_bot import config

if TYPE_CHECKING:
    from slack_sdk.web.async_client import AsyncWebClient

logger = logging.getLogger(__name__)


async def add_to_megatests(client: AsyncWebClient, slack_user_id: str) -> bool:
    """Add a Slack user's email to the Seqera workspace with its configured role."""
    token = config.SEQERA_TOKEN
    org_id = config.SEQERA_ORG_ID
    workspace_id = config.SEQERA_WORKSPACE_ID
    if not all((token, org_id, workspace_id)):
        logger.info("Seqera workspace sync is not configured; skipping user %s", slack_user_id)
        return False

    response: Any = await client.users_info(user=slack_user_id)
    email = response.get("user", {}).get("profile", {}).get("email")
    if not email:
        logger.warning("Slack user %s has no visible email; cannot sync to Seqera", slack_user_id)
        return False

    url = f"https://api.cloud.seqera.io/orgs/{org_id}/workspaces/{workspace_id}/participants/add"
    async with httpx.AsyncClient(timeout=15) as http:
        result = await http.put(
            url,
            headers={"Authorization": f"Bearer {token}"},
            json={"userNameOrEmail": email, "role": config.SEQERA_WORKSPACE_ROLE},
        )
    if result.is_success:
        logger.info("Added Slack user %s to Seqera workspace %s", slack_user_id, workspace_id)
        return True

    logger.warning(
        "Seqera workspace sync failed for Slack user %s: HTTP %s: %s",
        slack_user_id,
        result.status_code,
        result.text,
    )
    return False
