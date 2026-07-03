"""Port of internal/agent/agent.go: the agentic loop (stream → tool calls →
execute → repeat until finish_reason != tool_calls or max_steps).

Events are dicts {"type": str, "data": Any}. emit must not block: it's called
from the stream callback, on the event loop.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from dataclasses import dataclass, field

from cognits.constants import (
    MAX_CONCURRENT_DEPLOYS,
    MAX_CONCURRENT_TOOLS,
    MEM_CRITICAL,
    MEM_HIGH,
    MEM_WARN,
    TOOL_SEM_LOW,
)
from cognits.llm.base import LLMClient
from cognits.llm.deepseek import DeepSeekClient

_tool_sem = asyncio.Semaphore(MAX_CONCURRENT_TOOLS)
_deploy_sem = asyncio.Semaphore(MAX_CONCURRENT_DEPLOYS)
_tool_sem_low = asyncio.Semaphore(TOOL_SEM_LOW)
_memory_pressure: str = "ok"


def set_memory_pressure(rss_mb: int) -> None:
    global _memory_pressure
    if rss_mb > MEM_CRITICAL:
        _memory_pressure = "critical"
    elif rss_mb > MEM_HIGH:
        _memory_pressure = "high"
    elif rss_mb > MEM_WARN:
        _memory_pressure = "warn"
    else:
        _memory_pressure = "ok"
from cognits.llm.types import ROLE_ASSISTANT, ROLE_SYSTEM, ROLE_TOOL, Message, ToolCall
from cognits.tools import Registry

Event = dict
Emit = Callable[[Event], None]


class AgentError(Exception):
    pass


@dataclass
class AgentConfig:
    name: str = ""
    model: str = ""
    reasoning: str = ""
    max_steps: int = 0
    system_prompt: str = ""
    tools: Registry | None = None
    subagents: dict[str, "AgentConfig"] = field(default_factory=dict)
    max_tokens: int | None = None
    temperature: float | None = None
    top_p: float | None = None
    critique_mode: bool = False
    tool_registry: str = ""


class Agent:
    def __init__(self, cfg: AgentConfig, llm_client: LLMClient, tracer=None):
        self.cfg = cfg
        self.llm = llm_client
        from cognits.agent.tracer import NoopTracer
        self.tracer = tracer or NoopTracer()
        # Set by run() after a completed execution — contains the full
        # accumulated message list (system + user + assistant + tools)
        # so callers (e.g. DeploySubagent) can resume paused subagents.
        self.last_messages: list[Message] | None = None

    async def run(self, messages: list[Message], emit: Emit) -> str:
        cfg = self.cfg
        if cfg.system_prompt:
            messages = [Message(role=ROLE_SYSTEM, content=cfg.system_prompt)] + messages

        tool_defs = cfg.tools.definitions() if cfg.tools is not None else []

        iteration = 0
        while cfg.max_steps == 0 or iteration < cfg.max_steps:
            content_parts: list[str] = []
            # Tool call indices can come scattered: accumulate by index and
            # iterate sorted, without assuming 0..n-1.
            tool_accs: dict[int, dict] = {}
            finish_reason = ""

            def on_chunk(chunk: dict) -> None:
                nonlocal finish_reason
                choices = chunk.get("choices") or []
                if not choices:
                    if chunk.get("usage"):
                        emit({"type": "usage", "data": chunk["usage"]})
                    return
                delta = choices[0].get("delta") or {}

                content = delta.get("content") or ""
                if content:
                    content_parts.append(content)
                    emit({"type": "token", "data": content})
                reasoning = delta.get("reasoning_content") or ""
                if reasoning:
                    emit({"type": "reasoning", "data": reasoning})

                for tc in delta.get("tool_calls") or []:
                    idx = tc.get("index") or 0
                    acc = tool_accs.setdefault(
                        idx, {"id": "", "type": "", "name": "", "args": []}
                    )
                    if tc.get("id"):
                        acc["id"] = tc["id"]
                    if tc.get("type"):
                        acc["type"] = tc["type"]
                    fn = tc.get("function") or {}
                    if fn.get("name"):
                        acc["name"] = fn["name"]
                    acc["args"].append(fn.get("arguments") or "")

                if choices[0].get("finish_reason"):
                    finish_reason = choices[0]["finish_reason"]
                if chunk.get("usage"):
                    emit({"type": "usage", "data": chunk["usage"]})

            try:
                await self.llm.chat_completion_stream(
                    messages, tool_defs, cfg.model, cfg.reasoning, on_chunk,
                    max_tokens=cfg.max_tokens,
                    temperature=cfg.temperature,
                    top_p=cfg.top_p,
                )
            except asyncio.CancelledError:
                raise
            except Exception as e:
                raise AgentError(f"agent: llm stream: {e}") from e

            content = "".join(content_parts)

            if not tool_accs or finish_reason != "tool_calls":
                if content:
                    messages.append(Message(role=ROLE_ASSISTANT, content=content))
                self.last_messages = messages
                return content

            tool_calls = [
                ToolCall(
                    id=tool_accs[idx]["id"],
                    type="function",
                    name=tool_accs[idx]["name"],
                    arguments="".join(tool_accs[idx]["args"]),
                )
                for idx in sorted(tool_accs)
            ]
            if content or tool_calls:
                messages.append(
                    Message(role=ROLE_ASSISTANT, content=content, tool_calls=tool_calls)
                )

            async def _exec_tool(tc: ToolCall) -> str:
                tool = cfg.tools.get(tc.name) if cfg.tools is not None else None
                if tool is None:
                    raise AgentError(f"agent: unknown tool: {tc.name}")

                emit(
                    {
                        "type": "tool_start",
                        "data": {"tool": tc.name, "args": tc.arguments, "id": tc.id, "agent": cfg.name},
                    }
                )

                sem = _deploy_sem if tc.name == "deploy_subagent" else _tool_sem
                if _memory_pressure in ("critical", "high"):
                    sem = _tool_sem_low
                async with sem:
                    try:
                        result = await tool.execute(tc.arguments)
                    except asyncio.CancelledError:
                        raise
                    except Exception as e:
                        result = json.dumps({"error": str(e)}, ensure_ascii=False)

                emit({"type": "tool_end", "data": {"tool": tc.name, "id": tc.id}})
                return result

            results = await asyncio.gather(*(_exec_tool(tc) for tc in tool_calls))

            for tc, result in zip(tool_calls, results):
                messages.append(
                    Message(role=ROLE_TOOL, content=result, tool_call_id=tc.id)
                )

            iteration += 1

        raise AgentError(f"agent: max steps reached ({cfg.max_steps})")
