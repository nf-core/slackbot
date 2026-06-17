"""Automated review of nf-core new-pipeline proposals.

Watches the #new-pipelines channel for the GitHub→Slack post about a new
proposal, runs the ``nfcore-proposal-review`` skill via Claude on AWS Bedrock,
and posts a structured verdict back as a threaded reply tagging ``@core-team``.

Also exposes a ``/nf-core proposals review <N>`` slash command and a
"Review pipeline proposal" message shortcut.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Coroutine

logger = logging.getLogger(__name__)

# Strong references to in-flight review tasks so they are not garbage-collected
# mid-run (reviews run in the background; see Python asyncio task docs).
_background_tasks: set[asyncio.Task[Any]] = set()


def spawn(coro: Coroutine[Any, Any, Any]) -> asyncio.Task[Any]:
    """Run *coro* as a tracked background task.

    Reviews take minutes, so they must not block the Slack ack. Exceptions are
    logged rather than swallowed silently.
    """

    async def _runner() -> None:
        try:
            await coro
        except Exception:
            logger.exception("Background proposal-review task failed")

    task = asyncio.create_task(_runner())
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return task
