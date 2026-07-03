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


def test_flush_empty_noop(tmp_path, monkeypatch):
    monkeypatch.setattr("cognits.agent.tracer.paths.traces_dir", lambda: tmp_path / "traces")
    t = Tracer("s_test")
    asyncio.run(t.flush())
    assert not (tmp_path / "traces" / "s_test.jsonl").exists()
