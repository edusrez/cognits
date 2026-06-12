"""Entry point: port of cmd/learnit/main.go.

Starts the local HTTP server, opens the browser and manages shutdown: the
first signal drains active agents (their finally blocks persist partial
responses) and the second one hard-kills the process.
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import signal
import sys

import uvicorn

from cognits import __version__, paths
from cognits.server.app import DEFAULT_PORT, AppState, create_app
from cognits.server.browser import open_browser

log = logging.getLogger("cognits")

DRAIN_TIMEOUT = 5.0


class _Server(uvicorn.Server):
    def install_signal_handlers(self) -> None:
        # Signals are handled by _install_signal_handlers: uvicorn must not
        # shut down before the drain persists the partial responses.
        pass


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    port_env = os.environ.get("PORT", "")
    try:
        port = int(port_env) if port_env else DEFAULT_PORT
    except ValueError:
        print(f"invalid PORT: {port_env!r}", file=sys.stderr)
        raise SystemExit(1)

    try:
        asyncio.run(_run(port))
    except KeyboardInterrupt:
        pass


def _cleanup_legacy_sidecar() -> None:
    """The Go backend ran RAG as a sidecar with its own venv; it is now
    in-process. Removes the leftovers (keeping chroma_db, which is reused)."""
    rag_dir = paths.data_dir(create=False) / "rag"
    shutil.rmtree(rag_dir / "venv", ignore_errors=True)
    for name in ("sidecar.py", "requirements.txt"):
        try:
            (rag_dir / name).unlink()
        except OSError:
            pass


async def _run(port: int) -> None:
    _cleanup_legacy_sidecar()
    state = AppState()
    app = create_app(state)

    host = os.environ.get("COGNITS_HOST") or os.environ.get("LEARNIT_HOST") or "127.0.0.1"

    config = uvicorn.Config(
        app,
        host=host,
        port=port,
        log_level="warning",
        timeout_graceful_shutdown=int(DRAIN_TIMEOUT),
    )
    server = _Server(config)

    _install_signal_handlers(state, server)

    serve_task = asyncio.create_task(server.serve())
    while not server.started and not serve_task.done():
        await asyncio.sleep(0.05)
    if serve_task.done():
        await serve_task  # propagates the startup error (e.g. port in use)
        return

    url = f"http://localhost:{port}"
    print(f"Cognits {__version__} -> {url}", flush=True)
    open_browser(url)

    await serve_task
    print("\nbye", flush=True)


def _install_signal_handlers(state: AppState, server: uvicorn.Server) -> None:
    loop = asyncio.get_running_loop()
    shutting_down = False

    def on_signal() -> None:
        nonlocal shutting_down
        if shutting_down:
            # A second Ctrl+C during the drain hard-kills the process.
            os._exit(1)
        shutting_down = True
        asyncio.ensure_future(_shutdown(state, server))

    try:
        loop.add_signal_handler(signal.SIGINT, on_signal)
        loop.add_signal_handler(signal.SIGTERM, on_signal)
    except NotImplementedError:
        # Windows: no add_signal_handler; the handler fires on the main
        # thread and re-enqueues onto the loop.
        signal.signal(signal.SIGINT, lambda *_: loop.call_soon_threadsafe(on_signal))


async def _shutdown(state: AppState, server: uvicorn.Server) -> None:
    # Drain BEFORE asking uvicorn to shut down: uvicorn waits for in-flight
    # connections (the SSE streams), which only end when the drain sets
    # their done_event — the reverse order would deadlock. The RAG engine is
    # shut down by the app lifespan after the HTTP close.
    await state.drain_agents(DRAIN_TIMEOUT)
    server.should_exit = True


if __name__ == "__main__":
    main()
