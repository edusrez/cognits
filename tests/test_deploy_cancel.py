"""Tests for tool_deploy.py: cancel-safe subagent persistence."""

import asyncio
import json
import threading

import pytest

from cognits.agent.agent import AgentConfig
from cognits.agent.tool_deploy import DeploySubagent
from cognits.rag.engine import RagNotReady
from cognits.storage.database import Database
from cognits.storage.reports import ReportRepository
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


def _make_deploy(reports: ReportRepository, **overrides) -> DeploySubagent:
    cfg = AgentConfig(
        name="test_sub",
        model="m",
        system_prompt="Echo.",
        tools=Registry(),
    )
    kwargs = dict(
        llm_client=_FakeLLM(),
        reports=reports,
        subagents={"test_sub": cfg},
        session_id=lambda: "s_test",
        emit=None,
        rag_engine=None,
        suspended_subagents={},
    )
    kwargs.update(overrides)
    return DeploySubagent(**kwargs)


def test_normal_path_saves_indexes_emits(tmp_path):
    db = Database(tmp_path / "test.db")
    reports = ReportRepository(db)
    deploy = _make_deploy(reports)
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

    report = reports.get(data["reportId"])
    assert report is not None
    assert report.content == "hello DONE"
    assert any(e["type"] == "subagent_end" for e in emits)
    # Verify new subagent_end shape
    se = next(e for e in emits if e["type"] == "subagent_end")
    assert "id" in se["data"]
    assert "agent" in se["data"]
    assert "internal" in se["data"]
    assert se["data"]["internal"] is False  # test_sub is not internal
    assert se["data"]["reportId"] == data["reportId"]


def test_cancel_during_save_shields_and_emits(tmp_path):
    """Cancel at the report_store.save await — the shielded save must
    complete and subagent_end must still emit."""
    db = Database(tmp_path / "test.db")
    reports = ReportRepository(db)
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

    gated = GatedSave(reports)
    deploy = DeploySubagent(
        llm_client=_FakeLLM(),
        reports=gated,
        subagents={"test_sub": AgentConfig(name="test_sub", model="m", system_prompt="Echo.", tools=Registry())},
        session_id=lambda: "s_test",
        emit=None,
        rag_engine=None,
        suspended_subagents={},
    )
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
    assert reports.get(report_id) is not None


def test_cancel_during_index_emits_subagent_end(tmp_path):
    """Cancel at the rag_engine.index await — save already completed,
    subagent_end must still emit, CancelledError must re-raise."""
    db = Database(tmp_path / "test.db")
    reports = ReportRepository(db)
    deploy = _make_deploy(reports)

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
    result = reports.search(1, 10, "created_at DESC", "")
    assert len(result["reports"]) >= 1


def test_subagent_run_cancelled_no_report(tmp_path):
    """Cancelled during subagent.run — no report, no emit."""
    db = Database(tmp_path / "test.db")
    reports = ReportRepository(db)
    deploy = _make_deploy(reports)

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
    result = reports.search(1, 10, "created_at DESC", "")
    assert len(result["reports"]) == 0


def test_concurrent_executes_produce_distinct_instance_ids(tmp_path):
    """Two concurrent execute() calls on the SAME DeploySubagent must
    emit events with DIFFERENT instance_id values (no shared-state race)."""
    db = Database(tmp_path / "test.db")
    reports = ReportRepository(db)

    # Collect all emitted events with a thread-safe list.
    all_emits: list[dict] = []
    lock = threading.Lock()

    deploy = _make_deploy(reports)
    deploy.emit = lambda ev: (lock.acquire(), all_emits.append(ev), lock.release())

    async def run(query: str):
        return await deploy.execute(
            json.dumps({"type": "test_sub", "query": query})
        )

    # Fire two concurrent calls.
    async def concurrent():
        return await asyncio.gather(run("hello-a"), run("hello-b"))

    results = asyncio.run(concurrent())

    assert len(results) == 2
    # Both should produce reports.
    assert json.loads(results[0])["content"] == "hello-a DONE"
    assert json.loads(results[1])["content"] == "hello-b DONE"

    # Extract the instance_id from each subagent_end event.
    end_events = [e for e in all_emits if e["type"] == "subagent_end"]
    assert len(end_events) == 2, "expected 2 subagent_end events"
    id_a = end_events[0]["data"]["id"]
    id_b = end_events[1]["data"]["id"]
    assert id_a != id_b, (
        f"concurrent deploys reused the same instance_id ({id_a}). "
        f"instance_id must be a local variable, not self.instance_id."
    )


def test_rag_not_ready_deferred_warning(tmp_path):
    """When rag_engine.index() raises RagNotReady, the deploy CONTINUES
    (report saved + subagent_end emitted) — indexing is deferred for
    later backfill, not a hard error."""
    db = Database(tmp_path / "test.db")
    reports = ReportRepository(db)

    class FailingRag:
        async def index(self, chunks):
            raise RagNotReady("RAG engine still loading")

    deploy = _make_deploy(reports, rag_engine=FailingRag())
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

    # Report saved despite index failure
    report = reports.get(data["reportId"])
    assert report is not None
    assert report.content == "hello DONE"

    # subagent_end emitted (with reportId since save succeeded)
    assert any(e["type"] == "subagent_end" for e in emits)
    se = next(e for e in emits if e["type"] == "subagent_end")
    assert se["data"]["reportId"] == data["reportId"]


def test_rag_index_real_error_still_continues(tmp_path):
    """When rag_engine.index() raises a real error (not RagNotReady),
    the deploy CONTINUES — report is saved, subagent_end emitted.
    The report is usable even without vector index."""
    db = Database(tmp_path / "test.db")
    reports = ReportRepository(db)

    class FailingRag:
        async def index(self, chunks):
            raise RuntimeError("disk full")

    deploy = _make_deploy(reports, rag_engine=FailingRag())
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

    report = reports.get(data["reportId"])
    assert report is not None
    assert any(e["type"] == "subagent_end" for e in emits)
