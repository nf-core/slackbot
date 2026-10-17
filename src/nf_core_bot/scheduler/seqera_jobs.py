"""Background job: remove people who left the nf-core GitHub org from Seqera.

Launched as an ``asyncio.Task`` from ``app.py`` at startup, alongside the
on-call scheduler. Once a week it checks every member the bot added to any
Seqera group (recorded in DynamoDB by ``checks/seqera.py``) against the
nf-core GitHub org and removes anyone who is no longer a member or invitee
from that group. Access granted by hand is never recorded, so never touched.

While ``SEQERA_REMOVAL_DRY_RUN`` is on (the default) it only logs who it would
remove.
"""

from __future__ import annotations

import asyncio
import datetime
import logging
from dataclasses import dataclass, field

from nf_core_bot import config
from nf_core_bot.checks.github import get_org_membership_state
from nf_core_bot.checks.seqera import SeqeraGroup, removal_dry_run, remove_record, seqera_groups
from nf_core_bot.db.seqera import SeqeraMember, list_members

logger = logging.getLogger(__name__)

# Interval between scheduler loop iterations (seconds). Short enough that the
# target hour is never skipped, the weekly guard stops it running twice.
LOOP_INTERVAL = 600

# Monday at this hour (UTC) — an hour after the on-call weekly jobs.
TARGET_HOUR_UTC = 9

_last_weekly_run: str | None = None


@dataclass
class RemovalSummary:
    """What a removal run did, for logging and tests."""

    dry_run: bool
    checked: int = 0
    removed: list[str] = field(default_factory=list)
    would_remove: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


async def run_seqera_scheduler() -> None:
    """Long-running loop: run the Seqera removal sync once a week."""
    logger.info("Seqera removal scheduler started")
    while True:
        try:
            await _tick()
        except Exception:
            logger.exception("Seqera removal scheduler tick failed")
        await asyncio.sleep(LOOP_INTERVAL)


async def _tick(now_utc: datetime.datetime | None = None) -> None:
    global _last_weekly_run  # noqa: PLW0603

    if now_utc is None:
        now_utc = datetime.datetime.now(datetime.UTC)
    today_str = now_utc.date().isoformat()
    if now_utc.weekday() == 0 and now_utc.hour == TARGET_HOUR_UTC and _last_weekly_run != today_str:
        _last_weekly_run = today_str
        await sync_seqera_removals()


async def sync_seqera_removals() -> RemovalSummary | None:
    """Remove bot-added members who are no longer in the nf-core GitHub org, from every group.

    Returns ``None`` when Seqera isn't configured. Any GitHub or Seqera error
    for one person is logged and skipped, never treated as "left".
    """
    if not (config.SEQERA_TOKEN and config.SEQERA_ORG_ID):
        logger.info("Seqera is not configured; skipping removal sync")
        return None

    summary = RemovalSummary(dry_run=removal_dry_run())
    for group_name, group in seqera_groups().items():
        if group.target_key is None:
            continue
        for member in await list_members(group.target_key):
            await _check_member(summary, group_name, group, member)

    logger.info(
        "Seqera removal sync%s: checked %d, removed %d, would remove %d, errors %d",
        " (dry run)" if summary.dry_run else "",
        summary.checked,
        len(summary.removed),
        len(summary.would_remove),
        len(summary.errors),
    )
    return summary


async def _check_member(summary: RemovalSummary, group_name: str, group: SeqeraGroup, member: SeqeraMember) -> None:
    summary.checked += 1
    label = f"{member.github_username} ({member.email}, Slack {member.slack_user_id}, {group_name})"
    try:
        state = await get_org_membership_state(member.github_username)
    except Exception:
        logger.exception("Could not check GitHub org membership for %s; skipping", label)
        summary.errors.append(label)
        return
    if state is not None:
        return

    if summary.dry_run:
        logger.info("[dry run] Would remove %s from Seqera", label)
        summary.would_remove.append(label)
        return

    try:
        await remove_record(group, member)
    except Exception:
        logger.exception("Failed to remove %s from Seqera", label)
        summary.errors.append(label)
        return
    logger.info("Removed %s from Seqera (left the GitHub org)", label)
    summary.removed.append(label)
