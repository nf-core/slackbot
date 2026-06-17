"""Tests for the Bedrock tool-use loop."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from nf_core_bot.proposals import bedrock


def _text(t: str) -> SimpleNamespace:
    return SimpleNamespace(type="text", text=t)


def _tool(id_: str, name: str, inp: dict) -> SimpleNamespace:
    return SimpleNamespace(type="tool_use", id=id_, name=name, input=inp)


def _resp(stop_reason: str, content: list) -> SimpleNamespace:
    return SimpleNamespace(stop_reason=stop_reason, content=content)


async def test_runs_tool_then_returns_text() -> None:
    client = AsyncMock()
    client.messages.create.side_effect = [
        _resp("tool_use", [_tool("t1", bedrock.TOOL_NAME, {"command": "nf-core modules info fastqc"})]),
        _resp("end_turn", [_text("VERDICT: CONDITIONAL_ACCEPT")]),
    ]
    calls: list[str] = []

    async def runner(cmd: str) -> str:
        calls.append(cmd)
        return "fastqc exists"

    with patch.object(bedrock, "_get_client", return_value=client):
        out = await bedrock.run_review_agent("SYS", "CTX", tool_runner=runner)

    assert "CONDITIONAL_ACCEPT" in out
    assert calls == ["nf-core modules info fastqc"]
    assert client.messages.create.await_count == 2


async def test_refusal_returns_message() -> None:
    client = AsyncMock()
    client.messages.create.return_value = _resp("refusal", [])
    with patch.object(bedrock, "_get_client", return_value=client):
        out = await bedrock.run_review_agent("SYS", "CTX", tool_runner=AsyncMock())
    assert "declined" in out.lower()


async def test_unknown_tool_is_reported() -> None:
    client = AsyncMock()
    client.messages.create.side_effect = [
        _resp("tool_use", [_tool("t1", "mystery", {})]),
        _resp("end_turn", [_text("done")]),
    ]
    runner = AsyncMock()
    with patch.object(bedrock, "_get_client", return_value=client):
        out = await bedrock.run_review_agent("SYS", "CTX", tool_runner=runner)
    # The real tool runner is never called for an unknown tool name.
    runner.assert_not_awaited()
    assert out == "done"


async def test_iteration_cap() -> None:
    client = AsyncMock()
    client.messages.create.return_value = _resp("tool_use", [_tool("t", bedrock.TOOL_NAME, {"command": "jq -n 1"})])

    async def runner(cmd: str) -> str:
        return "ok"

    with patch.object(bedrock, "_get_client", return_value=client):
        out = await bedrock.run_review_agent("SYS", "CTX", tool_runner=runner, max_iterations=3)
    assert client.messages.create.await_count == 3
    assert isinstance(out, str)
