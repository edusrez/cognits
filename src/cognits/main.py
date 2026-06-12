"""Punto de entrada: port de cmd/learnit/main.go.

Arranca el servidor HTTP local, abre el navegador y gestiona el shutdown:
la primera señal drena los agentes activos (sus finally persisten respuestas
parciales) y la segunda mata el proceso en seco.
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
        # Las señales las gestiona _install_signal_handlers: uvicorn no debe
        # cortar antes de que el drenaje persista las respuestas parciales.
        pass


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    port_env = os.environ.get("PORT", "")
    try:
        port = int(port_env) if port_env else DEFAULT_PORT
    except ValueError:
        print(f"PORT inválido: {port_env!r}", file=sys.stderr)
        raise SystemExit(1)

    try:
        asyncio.run(_run(port))
    except KeyboardInterrupt:
        pass


def _cleanup_legacy_sidecar() -> None:
    """El backend Go gestionaba el RAG como sidecar con venv propio; ahora es
    in-process. Borra los restos (conservando chroma_db, que se reutiliza)."""
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
        await serve_task  # propaga el error de arranque (p.ej. puerto ocupado)
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
            # Un segundo Ctrl+C durante el drenaje mata el proceso en seco.
            os._exit(1)
        shutting_down = True
        asyncio.ensure_future(_shutdown(state, server))

    try:
        loop.add_signal_handler(signal.SIGINT, on_signal)
        loop.add_signal_handler(signal.SIGTERM, on_signal)
    except NotImplementedError:
        # Windows: sin add_signal_handler; el handler salta en el hilo
        # principal y reencola en el loop.
        signal.signal(signal.SIGINT, lambda *_: loop.call_soon_threadsafe(on_signal))


async def _shutdown(state: AppState, server: uvicorn.Server) -> None:
    # Drenar ANTES de pedir el cierre a uvicorn: uvicorn espera a las
    # conexiones en vuelo (los SSE), que solo terminan cuando el drenaje
    # cierra sus done_event — el orden inverso sería un interbloqueo. El RAG
    # lo apaga el lifespan de la app tras el cierre HTTP.
    await state.drain_agents(DRAIN_TIMEOUT)
    server.should_exit = True


if __name__ == "__main__":
    main()
