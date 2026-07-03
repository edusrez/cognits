"""Structured JSONL trace logging for agent observability.

Emits events to .cognits/traces/{session_id}.jsonl with per-subagent
token tracking, step trace, and tool call/result logging.

All file I/O is buffered and flushed via asyncio.to_thread to avoid
blocking the event loop.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from cognits import paths


class Tracer:
    def __init__(self, session_id: str):
        self.session_id = session_id
        self._buffer: list[dict] = []
        self._dir = paths.traces_dir()
        self._dir.mkdir(parents=True, exist_ok=True)
        self._path = self._dir / f"{session_id}.jsonl"

    def _now(self) -> str:
        return time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())

    def emit(self, *, span_id: str, parent_id: str = "root",
             agent_type: str = "", event: str = "",
             model: str = "", tokens_in: int = 0, tokens_out: int = 0,
             cache_hit: int = 0, cache_miss: int = 0,
             tool_name: str = "", duration_ms: float = 0.0,
             error: str = "", **extra) -> None:
        record = {
            "ts": self._now(),
            "span_id": span_id,
            "parent_id": parent_id,
            "agent_type": agent_type,
            "event": event,
        }
        if model: record["model"] = model
        if tokens_in: record["tokens_in"] = tokens_in
        if tokens_out: record["tokens_out"] = tokens_out
        if cache_hit: record["cache_hit"] = cache_hit
        if cache_miss: record["cache_miss"] = cache_miss
        if tool_name: record["tool_name"] = tool_name
        if duration_ms: record["duration_ms"] = duration_ms
        if error: record["error"] = error
        record.update(extra)
        self._buffer.append(record)

    async def flush(self):
        if not self._buffer:
            return
        records = self._buffer
        self._buffer = []
        import asyncio
        await asyncio.to_thread(self._write, records)

    def _write(self, records: list[dict]):
        with open(self._path, "a", encoding="utf-8") as f:
            for r in records:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
            f.flush()


class NoopTracer:
    """Tracer that discards all events. Used in tests and when tracing is disabled."""
    def emit(self, **kw) -> None: pass
    async def flush(self) -> None: pass
