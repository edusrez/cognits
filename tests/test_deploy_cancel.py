"""Tests for tool_deploy.py: cancel-safe subagent persistence."""

import asyncio
import json
import threading

import pytest

from cognits.agent.agent import AgentConfig
from cognits.agent.tool_deploy import DeploySubagent
from cognits.storage.db import ReportStore
from cognits.tools import Registry


class _FakeLLM:
    """Replies to the subagent query by echoing it back."""

    async def aclose(self):
        pass

    async def chat_completion_stream(self, messages, tools, model,
                                     reasoning, on_chunk, **_kw):
        for m in reversed(messages):
            if m.role == "user":
                reply = m.content + " DONE"
                break
        else:
            reply = "DONE"
        on_chunk({"choices": [{"delta": {"content": reply}}]})
        on_chunk({"choices": [{"delta": {}, "finish_reason": "stop"}]})


def _make_deploy(database: ReportStore, **overrides) -> DeploySubagent:
    cfg = AgentConfig(
        name="test_sub",
        model="m",
        system_prompt="Echo.",
        tools=Registry(),
    )
    kwargs = dict(
        llm_client=_FakeLLM(),
        report_store=database,
        subagents={"test_sub": cfg},
        session_id=lambda: "s_test",
        emit=None,
        rag_engine=None,
        suspended_subagents={},
    )
    kwargs.update(overrides)
    return DeploySubagent(**kwargs)


def test_normal_path_saves_indexes_emits(tmp_path):
    db = ReportStore(tmp_path / "test.db")
    deploy = _make_deploy(db)
    emits: list[dict] = []
    deploy.emit = lambda ev: emits.append(ev)

    async def run():
        return await deploy.execute(
            json.dumps({"type": "test_sub", "query": "hello"})
        )

    result = asyncio.run(run())
    data = json.loads(result)
    assert data["content"] == "hello DONE"
    assert data["reportId"]

    report = db.get(data["reportId"])
    assert report is not None
    assert report.content == "hello DONE"
    assert any(e["type"] == "subagent_end" for e in emits)


def test_cancel_during_save_shields_and_emits(tmp_path):
    """Cancel at the report_store.save await — the shielded save must
    complete and subagent_end must still emit."""
    db = ReportStore(tmp_path / "test.db")
    save_started = threading.Event()
    save_release = threading.Event()
    save_calls: list[str] = []

    class GatedSave:
        def __init__(self, inner):
            self._inner = inner

        def save(self, report):
            save_calls.append(report.id)
            save_started.set()
            save_release.wait(timeout=5)
            return self._inner.save(report)

    gated = GatedSave(db)
    deploy = _make_deploy(db, report_store=gated)
    emits: list[dict] = []
    deploy.emit = lambda ev: emits.append(ev)

    async def run():
        task = asyncio.create_task(
            deploy.execute(json.dumps({"type": "test_sub", "query": "hello"}))
        )
        await asyncio.to_thread(save_started.wait, 5)
        task.cancel()
        save_release.set()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(run())

    assert len(save_calls) >= 1
    assert any(e["type"] == "subagent_end" for e in emits)
    report_id = save_calls[0]
    assert db.get(report_id) is not None


def test_cancel_during_index_emits_subagent_end(tmp_path):
    """Cancel at the rag_engine.index await — save already completed,
    subagent_end must still emit, CancelledError must re-raise."""
    db = ReportStore(tmp_path / "test.db")
    deploy = _make_deploy(db)

    class GatedRag:
        def __init__(self):
            self.started = asyncio.Event()
            self.release = asyncio.Event()
            self.calls: list[int] = []

        async def index(self, chunks):
            self.calls.append(len(chunks))
            self.started.set()
            await self.release.wait()
            return len(chunks)

    gated = GatedRag()
    deploy.rag_engine = gated
    emits: list[dict] = []
    deploy.emit = lambda ev: emits.append(ev)

    async def run():
        task = asyncio.create_task(
            deploy.execute(json.dumps({"type": "test_sub", "query": "hello"}))
        )
        await asyncio.wait_for(gated.started.wait(), timeout=5)
        task.cancel()
        gated.release.set()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(run())

    assert any(e["type"] == "subagent_end" for e in emits)
    result = db.search_reports(1, 10, "created_at DESC", "")
    assert len(result["reports"]) >= 1


def test_subagent_run_cancelled_no_report(tmp_path):
    """Cancelled during subagent.run — no report, no emit."""
    db = ReportStore(tmp_path / "test.db")
    deploy = _make_deploy(db)

    class CancellingLLM:
        async def aclose(self): pass

        async def chat_completion_stream(self, *a, **kw):
            raise asyncio.CancelledError

    deploy.llm_client = CancellingLLM()
    emits: list[dict] = []
    deploy.emit = lambda ev: emits.append(ev)

    async def run():
        task = asyncio.create_task(
            deploy.execute(json.dumps({"type": "test_sub", "query": "x"}))
        )
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(run())

    assert not any(e["type"] == "subagent_end" for e in emits)
    result = db.search_reports(1, 10, "created_at DESC", "")
    assert len(result["reports"]) == 0
