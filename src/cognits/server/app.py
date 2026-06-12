"""Port de internal/server/server.go: estado de la aplicación y factory.

Invariante de concurrencia: todo el estado compartido (cached_config,
active_agents, pub/sub de SessionAgent) se toca solo desde el event loop;
los handlers son async y delegan el I/O bloqueante a asyncio.to_thread.
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
        self.rag = None  # rag.engine.RagEngine, se inicializa en main

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
        """Cancela todos los runs activos y espera a que sus finally persistan
        la respuesta parcial, con un timeout total compartido."""
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
            log.warning("server: drain timeout (%d agentes sin cerrar)", len(pending))


def create_app(state: AppState | None = None) -> FastAPI:
    if state is None:
        state = AppState()

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI):
        # El motor RAG carga en un hilo de fondo (ONNX ~5-15s, primera vez
        # descarga ~2,3 GB): el servidor responde al instante y las tools
        # degradan con error claro hasta que esté listo.
        if state.rag is None and os.environ.get("COGNITS_DISABLE_RAG") != "1":
            from cognits.rag.engine import RagEngine

            state.rag = RagEngine.start_background()
        yield
        if state.rag is not None:
            state.rag.shutdown()

    app = FastAPI(openapi_url=None, docs_url=None, redoc_url=None, lifespan=lifespan)
    app.state.ctx = state

    from cognits.server import (
        routes_chat,
        routes_config,
        routes_misc,
        routes_reports,
        routes_sessions,
        routes_stream,
    )

    routes_misc.register(app, state)
    routes_sessions.register(app, state)
    routes_config.register(app, state)
    routes_reports.register(app, state)
    routes_chat.register(app, state)
    routes_stream.register(app, state)

    # El catch-all del frontend va al final: Starlette resuelve por orden de
    # registro y las rutas /api/* deben ganar.
    if os.environ.get("ENV") == "dev":
        from cognits.server.devproxy import register_dev_proxy

        register_dev_proxy(app)
    else:
        from cognits.server.frontend import register_prod_frontend

        register_prod_frontend(app)

    return app
