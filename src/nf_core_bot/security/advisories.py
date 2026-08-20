"""Background job: poll GitHub security advisories across all nf-core repos.

Launched as an ``asyncio.Task`` from ``app.py`` at startup, alongside the
on-call scheduler (see ``scheduler/oncall_jobs.py``).

``repository_advisory`` webhooks don't reliably cover advisories submitted
via GitHub's "Report a vulnerability" form (state ``triage``) — no public
event fires until a maintainer/researcher formally acts on it. So instead
we poll once a day (a single org-wide API call, see
``checks.github.list_all_org_advisories``), diff against what was last
seen, and post anything new/changed to a private Slack channel.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from nf_core_bot import config
from nf_core_bot.checks.github import SecurityAdvisory, list_all_org_advisories
from nf_core_bot.db.advisories import get_known_advisories, save_advisory_state
from nf_core_bot.proposals.slack_utils import resolve_channel_id

if TYPE_CHECKING:
    from slack_sdk.web.async_client import AsyncWebClient

logger = logging.getLogger(__name__)

# Once a day is plenty — only a handful of advisories fire per year.
CHECK_INTERVAL_SECONDS = 24 * 60 * 60


async def run_security_scheduler(client: AsyncWebClient) -> None:
    """Long-running loop: check GitHub security advisories once a day."""
    logger.info("security advisory scheduler started")
    while True:
        try:
            await check_security_advisories(client)
        except Exception:
            logger.exception("security advisory check crashed unexpectedly")
            await _notify(client, "The security advisory check crashed unexpectedly — see bot logs.")
        await asyncio.sleep(CHECK_INTERVAL_SECONDS)


async def check_security_advisories(client: AsyncWebClient) -> None:
    """Fetch every org-wide security advisory, diff against last-seen state, and post a digest.

    A single API call covers every repo (see ``list_all_org_advisories``). If it
    fails — e.g. the account behind ``GITHUB_TOKEN`` isn't an org owner/security
    manager, or lacks the advisories scope — that's reported to Slack, not just logged.
    """
    try:
        advisories = await list_all_org_advisories()
    except Exception:
        logger.exception("Failed to fetch org security advisories")
        await _notify(
            client,
            "Could not fetch security advisories. Check that the account behind `GITHUB_TOKEN` "
            "is an org owner/security manager and the token has the `repository_advisories:write` "
            'scope (classic) or the "Repository security advisories" permission (fine-grained).',
        )
        return

    flagged: list[SecurityAdvisory] = []
    for adv in advisories:
        known = await get_known_advisories(adv.repo)
        prev = known.get(adv.ghsa_id)
        if prev is None or prev["state"] != adv.state or prev["updated_at"] != adv.updated_at:
            flagged.append(adv)
        await save_advisory_state(adv.repo, adv.ghsa_id, adv.state, adv.updated_at)

    if flagged:
        await _post_digest(client, flagged)


def _escape_mrkdwn(text: str) -> str:
    """Escape Slack mrkdwn special characters in externally-supplied text.

    ``adv.summary``/``adv.repo`` come from GitHub's advisory API — free text
    anyone can set by filing a vulnerability report against a public repo.
    Without escaping, a stray ``<``/``>`` can close the ``<url|label>`` link
    early and inject a second, attacker-controlled link (or an ``<!channel>``
    ping) into the message. Mirrors ``scheduler/oncall_jobs.py``'s ``_slack_link``.
    """
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


async def _post_digest(client: AsyncWebClient, advisories: list[SecurityAdvisory]) -> None:
    """Post one Slack message per new/changed advisory to the security channel."""
    channel = await resolve_channel_id(client, config.SECURITY_CHANNEL or "security")
    if channel is None:
        logger.error("Cannot post security advisory digest — #%s channel not resolved", config.SECURITY_CHANNEL)
        return
    for adv in advisories:
        severity = f" · {adv.severity}" if adv.severity else ""
        summary = _escape_mrkdwn(adv.summary)
        text = (
            f":rotating_light: *{_escape_mrkdwn(adv.repo)}* — <{adv.url}|{summary}>\n"
            f"State: `{adv.state}`{severity} · `{adv.ghsa_id}`"
        )
        try:
            await client.chat_postMessage(channel=channel, text=text)
        except Exception:
            logger.exception("Failed to post security advisory %s to Slack", adv.ghsa_id)


# Advisory states that are resolved/done, so are excluded from "open".
_CLOSED_STATES = frozenset({"closed", "withdrawn"})


def format_advisories_summary(advisories: list[SecurityAdvisory]) -> str:
    """Render a summary of all open advisories, grouped by repo, for ``/nf-core security summary``.

    "Open" excludes ``closed``/``withdrawn`` states — ``triage``, ``draft`` and
    ``published`` all still need attention. Summaries are attacker-influenced
    (see ``_escape_mrkdwn``), same as the daily digest.
    """
    open_advisories = [a for a in advisories if a.state not in _CLOSED_STATES]
    if not open_advisories:
        return ":white_check_mark: No open security advisories across nf-core repos."

    by_repo: dict[str, list[SecurityAdvisory]] = {}
    for adv in open_advisories:
        by_repo.setdefault(adv.repo, []).append(adv)

    count = len(open_advisories)
    lines = [f":closed_lock_with_key: *{count} open security advisor{'y' if count == 1 else 'ies'} across nf-core:*"]
    for repo in sorted(by_repo):
        lines.append(f"\n*{_escape_mrkdwn(repo)}*")
        for adv in by_repo[repo]:
            severity = f", {adv.severity}" if adv.severity else ""
            summary = _escape_mrkdwn(adv.summary)
            lines.append(f"• <{adv.url}|{summary}> (`{adv.state}`{severity}) — `{adv.ghsa_id}`")
    return "\n".join(lines)


async def _notify(client: AsyncWebClient, message: str) -> None:
    """Post a check-failure notice to the security channel — never fail silently."""
    channel = await resolve_channel_id(client, config.SECURITY_CHANNEL or "security")
    if channel is None:
        logger.error("Cannot post security-check failure notice — #%s channel not resolved", config.SECURITY_CHANNEL)
        return
    try:
        await client.chat_postMessage(channel=channel, text=f":warning: Security advisory check: {message}")
    except Exception:
        logger.exception("Failed to post security-check failure notice to Slack")
