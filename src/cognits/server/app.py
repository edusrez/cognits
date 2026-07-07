"""Port of internal/server/server.go: application state and factory.

Concurrency invariant: all shared state (cached_config, active_agents,
SessionAgent pub/sub) is touched only from the event loop; handlers are
async and delegate blocking I/O to asyncio.to_thread.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.middleware import Middleware

from cognits import paths
from cognits.storage.assessment import AssessmentItemRepository
from cognits.storage.database import Database
from cognits.storage.files import Config, Store
from cognits.storage.learner_state import LearnerStateRepository
from cognits.storage.messages import MessageRepository
from cognits.storage.notes import NoteRepository
from cognits.storage.pedagogical import PedagogicalPlanRepository
from cognits.storage.reports import ReportRepository
from cognits.storage.session_config import SessionConfigRepository
from cognits.storage.skills import SkillRepository
from cognits.storage.study_plans import StudyPlanRepository

log = logging.getLogger("cognits.server")

from cognits.constants import DEFAULT_PORT


_DRAIN_TIMEOUT = float(os.environ.get("COGNITS_DRAIN_TIMEOUT", "5.0"))


class _CancelSuppressMiddleware:
    """Pure ASGI middleware: swallow asyncio.CancelledError so uvicorn doesn't
    print a traceback when in-flight requests (e.g. SSE streams) are cancelled
    during shutdown.  Only swallows after the response has started — before that,
    re-raise so uvicorn doesn't log 'ASGI callable returned without completing
    response'.  CancelledError is a BaseException (not Exception), so
    Starlette/FastAPI exception handlers don't catch it — this does."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        response_started = False

        async def send_wrapper(message):
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        except asyncio.CancelledError:
            if response_started:
                # Response was in progress — swallow to avoid traceback
                pass
            else:
                # Response hadn't started — re-raise so uvicorn handles it
                raise


class AppState:
    def __init__(self) -> None:
        self.store: Store | None = None
        self.db: Database | None = None
        self.reports: ReportRepository | None = None
        self.messages: MessageRepository | None = None
        self.notes: NoteRepository | None = None
        self.skills: SkillRepository | None = None
        self.learner_state: LearnerStateRepository | None = None
        self.study_plans: StudyPlanRepository | None = None
        self.pedagogy: PedagogicalPlanRepository | None = None
        self.session_config: SessionConfigRepository | None = None
        self.assessment: AssessmentItemRepository | None = None
        self.cached_config: Config = Config()
        self.active_agents: dict[str, object] = {}
        self.suspended_subagents: dict[str, object] = {}
        self.pending_critiques: dict[str, str] = {}
        self.desktop_lock = asyncio.Lock()
        self.rag = None
        self.docling_engine = None

        try:
            base = paths.data_dir()
        except OSError as e:
            log.error("storage: data dir: %s", e)
            return

        try:
            self.store = Store(base)
            self.store.init_sessions_dir()
        except OSError as e:
            log.error("storage: init store: %s", e)
            return

        try:
            self.cached_config = self.store.load_config()
        except Exception as e:
            log.error("storage: load config: %s", e)
            self.cached_config = Config()

        try:
            self.db = Database(paths.db_path(base))
            self.reports = ReportRepository(self.db)
            self.messages = MessageRepository(self.db)
            self.notes = NoteRepository(self.db)
            self.skills = SkillRepository(self.db)
            self.learner_state = LearnerStateRepository(self.db)
            self.study_plans = StudyPlanRepository(self.db)
            self.pedagogy = PedagogicalPlanRepository(self.db)
            self.session_config = SessionConfigRepository(self.db)
            self.assessment = AssessmentItemRepository(self.db)
        except Exception as e:
            log.error("storage: init db: %s", e)

    @property
    def rag_or_none(self):
        # NOTE: rag_or_none is captured at ChatService construction time
        # (chat_service.py:566 + subagent_config builders).  If the engine
        # becomes ready mid-build, the captured reference stays None.  This
        # is acceptable: reports saved during the not-ready window are
        # indexed by the backfill scan on next startup; agents can still
        # run productively with deploy_subagent tool results + TinyFish.
        r = self.rag
        return r if r is not None and r.error is None and r.ready.is_set() else None

    async def drain_agents(self, timeout: float) -> None:
        """Cancels all active runs and waits for their finally blocks to
        persist the partial response, with a shared total timeout."""
        agents = list(self.active_agents.values())
        for sa in agents:
            sa.task.cancel()
        if not agents:
            return
        waits = [asyncio.create_task(sa.done_event.wait()) for sa in agents]
        done, pending = await asyncio.wait(waits, timeout=timeout)
        for t in pending:
            t.cancel()
        if pending:
            log.warning("server: drain timeout (%d agents still open)", len(pending))


async def _backfill_rag_index(state: AppState) -> None:
    """Fire-and-forget: wait for RAG to be ready, then index any reports
    whose chunks were never saved (e.g. reports created before the BGE-M3
    model finished loading).  Idempotent — re-indexed chunks are handled
    by ON CONFLICT DO UPDATE in vector_index."""
    if state.rag is None:
        return
    try:
        await asyncio.wait_for(state.rag.ready.wait(), timeout=600)
    except asyncio.TimeoutError:
        log.warning("backfill: RAG not ready after 600s, skipping")
        return
    except asyncio.CancelledError:
        return
    if state.rag.error is not None:
        log.warning("rag backfill: RAG engine failed during startup: %s", state.rag.error)
        return
    if state.db is None or state.reports is None:
        return

    def _scan() -> list[tuple]:
        # NOTE: COUNT=0 catches both zero-chunk and fully-missing entries.
        # Partial-chunk reports (crash during a previous indexing loop) are NOT
        # re-indexed — that edge case would require comparing expected vs stored
        # counts, which is over-engineering for a crash-during-loop scenario.
        with state.db.lock:
            return state.db.conn.execute(
                """SELECT r.id, r.title, r.content, r.subagent
                   FROM reports r
                   WHERE (SELECT COUNT(*) FROM report_chunks rc WHERE rc.report_id = r.id) = 0"""
            ).fetchall()  # type: ignore[union-attr]

    try:
        unindexed = await asyncio.to_thread(_scan)
    except Exception as e:
        log.error("rag backfill: scan failed: %s", e)
        return

    if not unindexed:
        log.debug("rag backfill: all reports already indexed")
        return

    log.info("rag backfill: found %d un-indexed reports — re-indexing", len(unindexed))

    from cognits.rag.chunker import split_markdown

    indexed_count = 0
    for row in unindexed:
        report_id, title, content, subagent = row
        if not content:
            continue
        try:
            chunks = split_markdown(content, report_id, title, source_type=subagent)
            if chunks:
                n = await state.rag.index(chunks)  # type: ignore[union-attr]
                log.info("rag backfill: indexed %d chunks for report %s", n, report_id)
                indexed_count += 1
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.error("rag backfill: failed to index report %s: %s", report_id, e)

    log.info("rag backfill: re-indexed %d/%d reports", indexed_count, len(unindexed))


def create_app(state: AppState | None = None) -> FastAPI:
    if state is None:
        state = AppState()

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI):
        # The RAG engine loads in a background thread (ONNX ~5-15s, first
        # run downloads ~2.3 GB): the server responds immediately and the
        # tools degrade with a clear error until it is ready.
        if state.rag is None and os.environ.get("COGNITS_DISABLE_RAG") != "1":
            from cognits.rag.engine import RagEngine

            state.rag = RagEngine.start_background()
            if state.db is not None:
                state.rag.set_db(state.db)
            asyncio.create_task(_backfill_rag_index(state))
        if state.docling_engine is None and os.environ.get("COGNITS_DISABLE_RAG") != "1":
            from cognits.docling_engine import DoclingEngine

            state.docling_engine = DoclingEngine.start_background()
        try:
            yield
        except asyncio.CancelledError:
            pass
        await state.drain_agents(timeout=_DRAIN_TIMEOUT)
        if state.db is not None:
            await asyncio.to_thread(state.db.shutdown)
        if state.rag is not None:
            state.rag.shutdown()
        if state.docling_engine is not None:
            state.docling_engine.shutdown()

    app = FastAPI(openapi_url=None, docs_url=None, redoc_url=None, lifespan=lifespan,
                  middleware=[Middleware(_CancelSuppressMiddleware)])
    app.state.ctx = state

    from cognits.server.exceptions import CognitsError

    @app.exception_handler(CognitsError)
    async def _cognits_error_handler(request, exc: CognitsError):
        return JSONResponse(
            status_code=exc.http_status,
            content={"error": exc.code, "message": exc.message, "details": exc.details},
        )

    from cognits.server import (
        routes_chat,
        routes_config,
        routes_files,
        routes_misc,
        routes_notes,
        routes_reports,
        routes_sessions,
        routes_skills,
        routes_study,
        routes_stream,
    )

    routes_misc.register(app, state)
    routes_sessions.register(app, state)
    routes_config.register(app, state)
    routes_files.register(app, state)
    routes_notes.register(app, state)
    routes_reports.register(app, state)
    routes_skills.register(app, state)
    routes_study.register(app, state)
    routes_chat.register(app, state)
    routes_stream.register(app, state)

    # The frontend catch-all goes last: Starlette resolves routes in
    # registration order and /api/* must win.
    if os.environ.get("ENV") == "dev":
        from cognits.server.devproxy import register_dev_proxy

        register_dev_proxy(app)
    else:
        from cognits.server.frontend import register_prod_frontend

        register_prod_frontend(app)

    return app
