"""Tests for agent/tracer.py: emit, flush, JSONL format."""

import json

from cognits.agent.tracer import Tracer


def test_emit_buffers(tmp_path, monkeypatch):
    monkeypatch.setattr("cognits.agent.tracer.paths.traces_dir", lambda: tmp_path)
    t = Tracer("s_test")
    t.emit(span_id="sp1", event="tool_start", tool_name="search")
    t.emit(span_id="sp2", event="tool_end", tool_name="search", duration_ms=120)

    assert len(t._buffer) == 2
    assert t._buffer[0]["span_id"] == "sp1"
    assert t._buffer[1]["duration_ms"] == 120


def test_flush_writes_jsonl(tmp_path, monkeypatch):
    monkeypatch.setattr("cognits.agent.tracer.paths.traces_dir", lambda: tmp_path)
    t = Tracer("s_test")
    t.emit(span_id="sp1", event="llm_start", model="deepseek-v4-pro")
    t.emit(span_id="sp1", event="llm_end", tokens_in=100, tokens_out=50)

    import asyncio
    asyncio.run(t.flush())

    trace_file = tmp_path / "traces" / "s_test.jsonl"
    assert trace_file.exists()
    lines = trace_file.read_text().strip().split("\n")
    assert len(lines) == 2
    ev1 = json.loads(lines[0])
    assert ev1["event"] == "llm_start"
    assert ev1["model"] == "deepseek-v4-pro"
    ev2 = json.loads(lines[1])
    assert ev2["tokens_in"] == 100
    assert ev2["tokens_out"] == 50


def test_flush_empty_noop(tmp_path, monkeypatch):
    monkeypatch.setattr("cognits.agent.tracer.paths.traces_dir", lambda: tmp_path)
    t = Tracer("s_test")
    import asyncio
    asyncio.run(t.flush())
    trace_file = tmp_path / "traces" / "s_test.jsonl"
    assert not trace_file.exists()


def test_extra_fields_propagate(tmp_path, monkeypatch):
    monkeypatch.setattr("cognits.agent.tracer.paths.traces_dir", lambda: tmp_path)
    t = Tracer("s_test")
    t.emit(span_id="sp1", event="custom", custom_attr="value", nested={"a": 1})

    import asyncio
    asyncio.run(t.flush())

    trace_file = tmp_path / "traces" / "s_test.jsonl"
    ev = json.loads(trace_file.read_text().strip())
    assert ev["custom_attr"] == "value"
    assert ev["nested"] == {"a": 1}


def test_ts_included(tmp_path, monkeypatch):
    monkeypatch.setattr("cognits.agent.tracer.paths.traces_dir", lambda: tmp_path)
    t = Tracer("s_test")
    t.emit(span_id="sp1", event="error", error="something broke")

    import asyncio
    asyncio.run(t.flush())

    trace_file = tmp_path / "traces" / "s_test.jsonl"
    ev = json.loads(trace_file.read_text().strip())
    assert "ts" in ev
    assert ev["error"] == "something broke"
