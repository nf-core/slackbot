"""Run the proposal-review skill via Claude on AWS Bedrock.

A small manual tool-use loop: send the skill (system prompt) plus the proposal
(user message), let Claude call the read-only ``run_command`` tool to do its
research, feed results back, and repeat until it produces the review text.

Authentication uses the standard AWS credential chain (the ECS task role in
production), so no keys are passed explicitly — billing lands on the AWS account
that owns the Bedrock model access.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

from nf_core_bot import config
from nf_core_bot.proposals.tools import RESEARCH_TOOL, TOOL_NAME
from nf_core_bot.proposals.tools import run_command as default_run_command

if TYPE_CHECKING:
    from anthropic import AsyncAnthropicBedrock

logger = logging.getLogger(__name__)

# Hard cap on tool-use round trips, so a misbehaving loop can't run forever.
MAX_ITERATIONS = 25

_client: AsyncAnthropicBedrock | None = None

ToolRunner = Callable[[str], Awaitable[str]]


def _get_client() -> AsyncAnthropicBedrock:
    """Return a cached :class:`AsyncAnthropicBedrock` client."""
    global _client  # noqa: PLW0603
    if _client is None:
        from anthropic import AsyncAnthropicBedrock

        region = config.BEDROCK_REGION or config.AWS_REGION or "eu-west-1"
        _client = AsyncAnthropicBedrock(aws_region=region)
    return _client


def _text_from(content: list[Any]) -> str:
    """Concatenate the text blocks of a response's content."""
    return "\n".join(block.text for block in content if getattr(block, "type", None) == "text").strip()


def _create_kwargs(system: str, messages: list[dict[str, Any]]) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "model": config.BEDROCK_MODEL_ID,
        "max_tokens": int(config.BEDROCK_MAX_TOKENS or "12000"),
        "system": system,
        "tools": [RESEARCH_TOOL],
        "messages": messages,
    }
    thinking = (config.BEDROCK_THINKING or "adaptive").lower()
    if thinking and thinking != "off":
        kwargs["thinking"] = {"type": thinking}
    return kwargs


async def run_review_agent(
    system_prompt: str,
    proposal_context: str,
    *,
    tool_runner: ToolRunner | None = None,
    max_iterations: int = MAX_ITERATIONS,
) -> str:
    """Drive the review to completion and return Claude's final review text.

    *system_prompt* is the skill (``SKILL.md``); *proposal_context* is the issue
    body + comments. *tool_runner* executes the ``run_command`` tool (defaults to
    the real read-only runner; injectable for tests).
    """
    run_tool = tool_runner or default_run_command
    client = _get_client()
    messages: list[dict[str, Any]] = [{"role": "user", "content": proposal_context}]

    response = None
    for _ in range(max_iterations):
        response = await client.messages.create(**_create_kwargs(system_prompt, messages))

        if response.stop_reason == "refusal":
            logger.warning("Bedrock refused the proposal review")
            return "_The model declined to produce a review for this proposal._"

        if response.stop_reason != "tool_use":
            # end_turn (or max_tokens) — we have the final text.
            return _text_from(response.content)

        # Execute the requested tool calls and feed the results back.
        messages.append({"role": "assistant", "content": response.content})
        tool_results: list[dict[str, Any]] = []
        for block in response.content:
            if getattr(block, "type", None) != "tool_use":
                continue
            if block.name == TOOL_NAME:
                command = (block.input or {}).get("command", "")
                logger.info("proposal-review tool call: %s", command)
                result = await run_tool(command)
            else:
                result = f"ERROR: unknown tool {block.name!r}"
            tool_results.append({"type": "tool_result", "tool_use_id": block.id, "content": result})
        messages.append({"role": "user", "content": tool_results})

    logger.warning("proposal review hit the %d-iteration cap", max_iterations)
    return _text_from(response.content) if response is not None else ""
