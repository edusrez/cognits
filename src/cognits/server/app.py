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

from fastapi import FastAPI

from cognits import paths
from cognits.storage.db import ReportStore
from cognits.storage.files import Config, Store

log = logging.getLogger("cognits.server")

DEFAULT_PORT = 5173


class AppState:
    def __init__(self) -> None:
        self.store: Store | None = None
        self.report_store: ReportStore | None = None
        self.cached_config: Config = Config()
        # session_id -> SessionAgent (server/session_agent.py)
        self.active_agents: dict[str, object] = {}
        self.desktop_lock = asyncio.Lock()
        self.rag = None  # rag.engine.RagEngine, initialized in main
        self.docling_engine = None  # docling_engine.DoclingEngine

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
            self.report_store = ReportStore(paths.db_path(base))
        except Exception as e:
            log.error("storage: init db: %s", e)

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
        if state.docling_engine is None and os.environ.get("COGNITS_DISABLE_RAG") != "1":
            from cognits.docling_engine import DoclingEngine

            state.docling_engine = DoclingEngine.start_background()
        try:
            yield
        except asyncio.CancelledError:
            pass
        if state.rag is not None:
            state.rag.shutdown()
        if state.docling_engine is not None:
            state.docling_engine.shutdown()

    app = FastAPI(openapi_url=None, docs_url=None, redoc_url=None, lifespan=lifespan)
    app.state.ctx = state

    from cognits.server import (
        routes_chat,
        routes_config,
        routes_files,
        routes_misc,
        routes_notes,
        routes_reports,
        routes_sessions,
        routes_stream,
    )

    routes_misc.register(app, state)
    routes_sessions.register(app, state)
    routes_config.register(app, state)
    routes_files.register(app, state)
    routes_notes.register(app, state)
    routes_reports.register(app, state)
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
