"""Tests of the agentic loop with a scripted LLM client."""

import asyncio
import json

import pytest

from cognits.agent.agent import Agent, AgentConfig, AgentError
from cognits.tools import Registry, Tool


class ScriptedLLM:
    """Replays scripted streams: each element is the chunk list for one
    chat_completion_stream call."""

    def __init__(self, streams):
        self.streams = list(streams)
        self.calls = []

    async def chat_completion_stream(self, messages, tools, model, reasoning, on_chunk):
        self.calls.append([m.to_payload() for m in messages])
        for chunk in self.streams.pop(0):
            on_chunk(chunk)


class EchoTool(Tool):
    name = "echo"
    description = "echo"
    schema = {"type": "object"}

    def __init__(self):
        self.received = []

    async def execute(self, raw_args: str) -> str:
        self.received.append(raw_args)
        return json.dumps({"echo": json.loads(raw_args)})


def _delta(content=None, reasoning=None, tool_calls=None, finish=None, usage=None):
    delta = {}
    if content is not None:
        delta["content"] = content
    if reasoning is not None:
        delta["reasoning_content"] = reasoning
    if tool_calls is not None:
        delta["tool_calls"] = tool_calls
    chunk = {"choices": [{"delta": delta, "finish_reason": finish}]}
    if usage is not None:
        chunk["usage"] = usage
    return chunk


def test_run_simple_content():
    llm = ScriptedLLM([[_delta(content="Hello"), _delta(content=" world", finish="stop")]])
    events = []
    agent = Agent(AgentConfig(model="m", system_prompt="sp"), llm)

    from cognits.llm.types import Message

    result = asyncio.run(agent.run([Message(role="user", content="hi")], events.append))
    assert result == "Hello world"
    assert [e["data"] for e in events if e["type"] == "token"] == ["Hello", " world"]
    # The system prompt is prepended.
    assert llm.calls[0][0] == {"role": "system", "content": "sp"}


def test_run_tool_call_with_scattered_indices_and_fragmented_args():
    tool = EchoTool()
    registry = Registry()
    registry.register(tool)

    streams = [
        [
            # Fragmented args in multiple deltas and non-zero index.
            _delta(tool_calls=[{"index": 2, "id": "call_1", "type": "function",
                                "function": {"name": "echo", "arguments": '{"a"'}}]),
            _delta(tool_calls=[{"index": 2, "function": {"arguments": ': 1}'}}]),
            _delta(finish="tool_calls"),
        ],
        [_delta(content="done", finish="stop", usage={"prompt_tokens": 5})],
    ]
    llm = ScriptedLLM(streams)
    events = []
    agent = Agent(AgentConfig(model="m", tools=registry), llm)

    from cognits.llm.types import Message

    result = asyncio.run(agent.run([Message(role="user", content="x")], events.append))
    assert result == "done"
    assert tool.received == ['{"a": 1}']

    types = [e["type"] for e in events]
    assert types == ["tool_start", "tool_end", "token", "usage"]

    # The second call carries the assistant with tool_calls and the tool result.
    second = llm.calls[1]
    assert second[-2]["tool_calls"][0]["function"]["arguments"] == '{"a": 1}'
    assert second[-1]["role"] == "tool"
    assert second[-1]["tool_call_id"] == "call_1"


def test_run_max_steps():
    tc = [{"index": 0, "id": "c1", "type": "function",
           "function": {"name": "echo", "arguments": "{}"}}]
    registry = Registry()
    registry.register(EchoTool())
    llm = ScriptedLLM([
        [_delta(tool_calls=tc, finish="tool_calls")],
        [_delta(tool_calls=tc, finish="tool_calls")],
    ])
    agent = Agent(AgentConfig(model="m", max_steps=2, tools=registry), llm)

    from cognits.llm.types import Message

    with pytest.raises(AgentError, match="max steps reached"):
        asyncio.run(agent.run([Message(role="user", content="x")], lambda e: None))


def test_unknown_tool():
    tc = [{"index": 0, "id": "c1", "type": "function",
           "function": {"name": "nope", "arguments": "{}"}}]
    llm = ScriptedLLM([[_delta(tool_calls=tc, finish="tool_calls")]])
    agent = Agent(AgentConfig(model="m", tools=Registry()), llm)

    from cognits.llm.types import Message

    with pytest.raises(AgentError, match="unknown tool"):
        asyncio.run(agent.run([Message(role="user", content="x")], lambda e: None))
