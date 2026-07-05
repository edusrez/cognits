"""Tests for agent/tracer.py: emit buffers + basic flush."""

import asyncio
import json

from cognits.agent.tracer import Tracer


def test_emit_buffers(tmp_path, monkeypatch):
    monkeypatch.setattr("cognits.agent.tracer.paths.traces_dir", lambda: tmp_path / "traces")
    t = Tracer("s_test")
    t.emit(span_id="sp1", event="tool_start", tool_name="search")
    t.emit(span_id="sp2", event="tool_end", tool_name="search", duration_ms=120)
    assert len(t._buffer) == 2
    assert t._buffer[0]["span_id"] == "sp1"
    assert t._buffer[1]["duration_ms"] == 120


def test_flush_writes(tmp_path, monkeypatch):
    td = tmp_path / "traces"
    monkeypatch.setattr("cognits.agent.tracer.paths.traces_dir", lambda: td)
    t = Tracer("s_test")
    t.emit(span_id="sp1", event="llm_start", model="m")
    asyncio.run(t.flush())
    trace_file = td / "s_test.jsonl"
    assert trace_file.exists()
    assert "llm_start" in trace_file.read_text()


def test_tracer_emits_during_agent_run(tmp_path, monkeypatch):
    """Verify tracer.emit is called with cache_hit during an agent run."""
    import asyncio
    from cognits.agent.agent import Agent, AgentConfig
    from cognits.agent.tracer import Tracer
    from cognits.llm.base import LLMClient
    from cognits.llm.types import Message

    monkeypatch.setattr("cognits.agent.tracer.paths.traces_dir", lambda: tmp_path / "traces")

    class FakeLLM:
        async def chat_completion_stream(self, messages, tools, model, reasoning, on_chunk, **kw):
            on_chunk({"choices": [{"delta": {"content": "hi"}, "finish_reason": "stop"}]})
            on_chunk({"usage": {"prompt_tokens": 100, "completion_tokens": 5, "prompt_cache_hit_tokens": 80}})
        async def aclose(self): pass

    tracer = Tracer("s_test")
    cfg = AgentConfig(name="test_agent", model="m", max_steps=1, system_prompt="")
    ag = Agent(cfg, FakeLLM(), tracer=tracer)
    result = asyncio.run(ag.run([Message(role="user", content="hi")], emit=lambda _ev: None))
    assert result == "hi"
    assert len(tracer._buffer) >= 2
    usage_events = [r for r in tracer._buffer if r.get("event") == "usage"]
    assert len(usage_events) == 1
    assert usage_events[0]["cache_hit"] == 80
    assert usage_events[0]["cache_miss"] == 20
