"""Entry point for Cognits.

Starts the local HTTP server inside a Textual TUI: progress bar + menu
(Open Web / Close) → running state, all inside a single bordered panel.
"""

from __future__ import annotations

import argparse
import asyncio
import atexit
import logging
import os
import shutil
import signal
import sys
import threading
import time
from pathlib import Path

import uvicorn
from textual import on, events
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import VerticalGroup
from textual.theme import Theme
from textual.widgets import Label, OptionList, Static
from textual.widgets.option_list import Option

from cognits import __version__, paths
from cognits.server.app import DEFAULT_PORT, AppState, create_app
from cognits.server.browser import open_browser

# ---------------------------------------------------------------------------
# Spinner — bouncing filled square, Knight-Rider style
# ---------------------------------------------------------------------------

SPINNER = [
    "\u25a0 \u25a1 \u25a1 \u25a1 \u25a1 \u25a1 \u25a1",
    "\u25a1 \u25a0 \u25a1 \u25a1 \u25a1 \u25a1 \u25a1",
    "\u25a1 \u25a1 \u25a0 \u25a1 \u25a1 \u25a1 \u25a1",
    "\u25a1 \u25a1 \u25a1 \u25a0 \u25a1 \u25a1 \u25a1",
    "\u25a1 \u25a1 \u25a1 \u25a1 \u25a0 \u25a1 \u25a1",
    "\u25a1 \u25a1 \u25a1 \u25a1 \u25a1 \u25a0 \u25a1",
    "\u25a1 \u25a1 \u25a1 \u25a1 \u25a1 \u25a1 \u25a0",
    "\u25a1 \u25a1 \u25a1 \u25a1 \u25a1 \u25a0 \u25a1",
    "\u25a1 \u25a1 \u25a1 \u25a1 \u25a0 \u25a1 \u25a1",
    "\u25a1 \u25a1 \u25a1 \u25a0 \u25a1 \u25a1 \u25a1",
    "\u25a1 \u25a1 \u25a0 \u25a1 \u25a1 \u25a1 \u25a1",
    "\u25a1 \u25a0 \u25a1 \u25a1 \u25a1 \u25a1 \u25a1",
]

# ---------------------------------------------------------------------------
# Custom dark theme — matches the web UI
# ---------------------------------------------------------------------------

COGNITS_THEME = Theme(
    name="cognits-dark",
    primary="#666666",
    secondary="#444444",
    accent="#888888",
    foreground="#CCCCCC",
    background="#0D0D0D",
    surface="#111111",
    panel="#1A1A1A",
    dark=True,
    variables={
        "block-cursor-background": "#2A2A2A",
        "block-cursor-foreground": "#FFFFFF",
        "block-cursor-text-style": "bold",
        "block-cursor-blurred-background": "#222222",
        "border": "#555555",
        "border-blurred": "#333333",
        "footer-background": "#111111",
    },
)

# ---------------------------------------------------------------------------
# Styles
# ---------------------------------------------------------------------------

CSS = """
Screen {
    align: center middle;
    background: #0D0D0D;
}

#main-panel {
    border: solid #555;
    padding: 1 3;
    width: 56;
    max-height: 90vh;
    background: #111111;
}

#header {
    text-align: center;
    width: 100%;
    padding-bottom: 1;
}

#loading-container, #ready-container, #menu-container, #running-container {
    align: center middle;
    width: 100%;
}

#loading-label, #ready-label, #running-label, #loading-indicator, #download-label {
    text-align: center;
    width: 100%;
}

#loading-indicator {
    padding-bottom: 1;
}

#menu {
    margin-top: 1;
}

#menu-hint {
    padding-top: 1;
    padding-left: 2;
}

.hidden {
    display: none;
}
"""


# ---------------------------------------------------------------------------
# Uvicorn server wrapper
# ---------------------------------------------------------------------------

class _Server(uvicorn.Server):
    def install_signal_handlers(self) -> None:
        pass


class CognitsTUI(App):
    """Single-screen TUI: progress bar → interactive menu inside a bordered panel."""

    CSS = CSS
    ENABLE_COMMAND_PALETTE = False
    NOTIFICATION_TIMEOUT = 0
    # Override Textual's default: Ctrl+C shows a "press Ctrl+Q" hint. For a
    # single-user local TUI, Ctrl+C should quit — it's the reflexive exit key.
    BINDINGS = [
        Binding("ctrl+q", "quit", "Quit", show=False, priority=True),
        Binding("ctrl+c", "quit", "Quit", show=False, priority=True),
    ]

    def on_print(self, event: events.Print) -> None:
        event.stop()

    def __init__(self, state: AppState, server: _Server, port: int) -> None:
        self._state = state
        self._server = server
        self._port = port
        self._url = f"http://localhost:{port}"
        self._server_thread: threading.Thread | None = None
        super().__init__()

    # -- Composition ---------------------------------------------------------

    def compose(self) -> ComposeResult:
        with VerticalGroup(id="main-panel"):
            yield Static(
                f"[bold]Cognits[/bold] [dim italic]v{__version__}[/dim italic]\n"
                "[dim]Context-Oriented Generation for\n"
                "Neural Intelligent Tutoring Systems[/dim]",
                id="header",
            )

            with VerticalGroup(id="loading-container"):
                yield Static("", id="loading-indicator")
                yield Label("Downloading\u2026", id="download-label")

            with VerticalGroup(id="ready-container", classes="hidden"):
                yield Static(
                    f"  [bold green]\u2713[/bold green]  Ready    "
                    f"[dim italic]v{__version__}[/dim italic]",
                    id="ready-label",
                )

            with VerticalGroup(id="menu-container", classes="hidden"):
                yield OptionList(
                    Option("Open Web", id="open"),
                    Option("Close",   id="close"),
                    id="menu",
                )
                yield Static("[dim]  (↑↓ arrows, Enter to select)[/dim]", id="menu-hint")

            with VerticalGroup(id="running-container", classes="hidden"):
                yield Static(
                    "Server running\n\nPress [bold]Ctrl+Q[/bold] to stop",
                    id="running-label",
                )

    # -- Lifecycle -----------------------------------------------------------

    def on_mount(self) -> None:
        self.register_theme(COGNITS_THEME)
        self.theme = "cognits-dark"

        signal.signal(signal.SIGHUP, lambda *_: self.exit())

        # Run uvicorn in its own thread + event loop so serving static
        # assets never blocks Textual's render loop.
        self._server_thread = threading.Thread(
            target=lambda: asyncio.run(self._run_server()),
            daemon=False,
        )
        self._server_thread.start()

        self.run_worker(self._check_rag())

    # -- Server --------------------------------------------------------------

    async def _run_server(self) -> None:
        await self._server.serve()

    # -- Loading phase -------------------------------------------------------

    async def _check_rag(self) -> None:
        old_switch = sys.getswitchinterval()
        sys.setswitchinterval(0.001)
        spinner_frame = 0
        try:
            rag = self._state.rag
            if rag is None:
                while self._state.rag is None:
                    await asyncio.sleep(0.1)
                rag = self._state.rag
            if rag is not None:
                # Phase 1: download
                while not rag.ready.is_set() and not rag.error:
                    self.query_one("#download-label", Label).update(
                        "Downloading BGE-M3\u2026"
                    )
                    spinner_frame = (spinner_frame + 1) % len(SPINNER)
                    self.query_one("#loading-indicator", Static).update(
                        SPINNER[spinner_frame]
                    )
                    await asyncio.sleep(1 / 12)
                # Phase 2: ONNX model load
                while not rag.ready.is_set() and not rag.error:
                    self.query_one("#download-label", Label).update("Loading model\u2026")
                    spinner_frame = (spinner_frame + 1) % len(SPINNER)
                    self.query_one("#loading-indicator", Static).update(SPINNER[spinner_frame])
                    await asyncio.sleep(1 / 12)
                if rag.error:
                    self.query_one("#loading-indicator", Static).update("")
                    self.query_one("#download-label", Label).update(
                        f"[bold red]Error:[/bold red] {rag.error}"
                    )
                    return
            # Phase 3: Docling models download
            dl = self._state.docling_engine
            if dl is None:
                while self._state.docling_engine is None:
                    await asyncio.sleep(0.1)
                dl = self._state.docling_engine
            if dl is not None:
                while not dl.ready.is_set() and not dl.error:
                    self.query_one("#download-label", Label).update(
                        "Loading Docling models\u2026"
                    )
                    spinner_frame = (spinner_frame + 1) % len(SPINNER)
                    self.query_one("#loading-indicator", Static).update(
                        SPINNER[spinner_frame]
                    )
                    await asyncio.sleep(1 / 12)
                if dl.error:
                    self.query_one("#loading-indicator", Static).update("")
                    self.query_one("#download-label", Label).update(
                        f"[bold yellow]Docling:[/bold yellow] {dl.error}"
                    )
            await asyncio.sleep(0.3)
        finally:
            sys.setswitchinterval(old_switch)
        self._show_ready()

    def _show_ready(self) -> None:
        self.query_one("#loading-container").add_class("hidden")
        self._show_menu()

    def _show_menu(self) -> None:
        self.query_one("#menu-container").remove_class("hidden")
        self.call_after_refresh(
            self.query_one("#menu", OptionList).focus
        )

    # -- Menu actions --------------------------------------------------------

    @on(OptionList.OptionSelected)
    def _on_menu(self, event: OptionList.OptionSelected) -> None:
        if event.option_id == "open":
            open_browser(self._url)
            self.query_one("#menu-container").add_class("hidden")
            self.query_one("#running-container").remove_class("hidden")
            self.set_focus(None)
        elif event.option_id == "close":
            self.exit()

    # -- Cleanup -------------------------------------------------------------

    async def _shutdown(self) -> None:
        # Textual calls _shutdown() in the finally block of run_async — this
        # fires on both normal exit (Ctrl+Q / menu Close) and Ctrl+C (rebound
        # to quit via BINDINGS). The old _on_exit method was never called by
        # Textual (it doesn't exist as a handler), so cleanup never ran.
        if self._server_thread is not None:
            self._server.should_exit = True
            self._server_thread.join(timeout=8)
            if self._server_thread.is_alive():
                self._server.force_exit = True
                self._server_thread.join(timeout=2)
        # The lifespan finally block should have called these, but if the
        # server-thread join timed out the lifespan may not have completed.
        # shutdown() is idempotent and terminates the warm-cache subprocess.
        if self._state.rag is not None:
            self._state.rag.shutdown()
        if self._state.docling_engine is not None:
            self._state.docling_engine.shutdown()
        await super()._shutdown()
        # Belt-and-suspenders: the lifespan finally block should have called
        # these, but if the server thread join timed out the lifespan may not
        # have completed. shutdown() is idempotent and also terminates the
        # warm-cache subprocess so atexit doesn't hang on thread.join.
        if self._state.rag is not None:
            self._state.rag.shutdown()
        if self._state.docling_engine is not None:
            self._state.docling_engine.shutdown()


def _interactive_uninstall(skip_confirm: bool = False) -> None:
    """Interactive full uninstall: model caches + project data."""
    is_tty = sys.stdin.isatty()

    def ask(prompt: str) -> bool:
        if skip_confirm:
            return True
        if not is_tty:
            print(f"(no TTY, skipping) {prompt}", file=sys.stderr, flush=True)
            return False
        try:
            answer = input(f"{prompt} [y/N] ").strip().lower()
            return answer in ("y", "yes")
        except (EOFError, KeyboardInterrupt):
            print()
            return False

    print("\nCognits -- Full Uninstall\n" + "=" * 40)

    remove_models = ask(
        "\nRemove downloaded AI models?\n"
        "  ~/.cache/docling/  (~1.5 GB)\n"
        "  ~/.cache/fastembed/ (~2.3 GB)"
    )

    remove_data = ask(
        "\nRemove project data?\n"
        "  .cognits/ and .learnit/ in this directory"
    )

    if not remove_models and not remove_data:
        print("\nNothing to remove.", flush=True)
        _print_uninstall_hint()
        return

    print(
        f"\n{'─' * 40}\n"
        f"  Model caches:   {'yes' if remove_models else 'no'}\n"
        f"  Project data:    {'yes' if remove_data else 'no'}"
    )

    if not ask("\nProceed?"):
        print("Cancelled.", flush=True)
        return

    home = Path.home()

    if remove_models:
        for d in [home / ".cache" / "docling", home / ".cache" / "fastembed"]:
            if d.is_dir():
                try:
                    shutil.rmtree(d)
                    print(f"  Removed {d}", flush=True)
                except OSError as e:
                    print(f"  Failed to remove {d}: {e}", flush=True)
            else:
                print(f"  Not found: {d}", flush=True)

    if remove_data:
        cwd = Path.cwd()
        for name in (paths.DATA_DIR_NAME, paths.LEGACY_DATA_DIR_NAME):
            d = cwd / name
            if d.is_dir():
                try:
                    shutil.rmtree(d)
                    print(f"  Removed {d}", flush=True)
                except OSError as e:
                    print(f"  Failed to remove {d}: {e}", flush=True)
            else:
                print(f"  Not found: {d}", flush=True)

    _print_uninstall_hint()


def _print_uninstall_hint() -> None:
    print("\nTo complete uninstall, run:\n  uv tool uninstall cognits", flush=True)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    os.environ.setdefault("ORT_LOG_LEVEL", "ERROR")

    # Silence uvicorn / starlette / httpx loggers — NullHandler swallows
    # everything regardless of level.
    for name in ("uvicorn", "uvicorn.access", "uvicorn.error", "starlette", "httpx"):
        logger = logging.getLogger(name)
        logger.handlers.clear()
        logger.addHandler(logging.NullHandler())
        logger.propagate = False

    if "-fresh" in sys.argv:
        print("Use --fresh (two dashes), not -fresh", file=sys.stderr)
        raise SystemExit(1)

    parser = argparse.ArgumentParser(
        prog="cognits",
        description="Cognits — Context-Oriented Generation for Neural Intelligent Tutoring Systems",
    )
    parser.add_argument(
        "--version", "-V", action="version",
        version=f"Cognits {__version__}",
    )
    parser.add_argument(
        "--fresh", action="store_true",
        help="Remove all local data and start fresh",
    )
    parser.add_argument(
        "--port", type=int,
        help="HTTP server port (default: %(default)s, overridden by PORT env var)",
        default=DEFAULT_PORT,
    )
    parser.add_argument(
        "--force-port", type=int,
        help="HTTP port, kill existing process, ignores PORT env var",
    )
    parser.add_argument(
        "--uninstall", action="store_true",
        help="Print instructions to uninstall Cognits",
    )
    parser.add_argument(
        "--full-uninstall", action="store_true",
        help="Remove model caches and project data interactively",
    )
    parser.add_argument(
        "--yes", "-y", action="store_true",
        help="Skip confirmation prompts (for --full-uninstall)",
    )

    args = parser.parse_args()

    if args.full_uninstall:
        _interactive_uninstall(skip_confirm=args.yes)
        raise SystemExit(0)

    if args.uninstall:
        print("To uninstall Cognits, run:\n  uv tool uninstall cognits")
        raise SystemExit(0)

    if args.fresh:
        cwd = Path.cwd()
        for name in (paths.DATA_DIR_NAME, paths.LEGACY_DATA_DIR_NAME):
            d = cwd / name
            if d.is_dir():
                shutil.rmtree(d)
                print(f"Removed {d}", flush=True)
        print("Fresh start.", flush=True)

    force = args.force_port is not None
    port = args.force_port if force else args.port

    # Env var overrides --port but not --force-port.
    if not force:
        port_env = os.environ.get("PORT", "")
        if port_env:
            try:
                port = int(port_env)
            except ValueError:
                print(f"invalid PORT: {port_env!r}", file=sys.stderr)
                raise SystemExit(1)

    host = (
        os.environ.get("COGNITS_HOST")
        or os.environ.get("LEARNIT_HOST")
        or "127.0.0.1"
    )

    if args.fresh or force:
        _kill_port(port)
        time.sleep(0.5)

    if not _port_available(host, port):
        # Retry up to 4s — the killed process may still be in TIME_WAIT.
        for _ in range(8):
            time.sleep(0.5)
            if _port_available(host, port):
                break
        else:
            print(f"Port {port} already in use — is Cognits already running?",
                  file=sys.stderr)
            raise SystemExit(1)

    _cleanup_legacy_sidecar()

    # onnxruntime emits a hard-coded C++ warning to fd 2 during import
    # (GPU device discovery) that ORT_LOG_LEVEL=ERROR cannot suppress
    # (confirmed bug in onnxruntime_pybind_module.cc).  Redirect fd 2
    # to /dev/null during the import, then restore immediately so
    # Textual can use the terminal normally.
    _saved_stderr = os.dup(2)
    devnull = os.open(os.devnull, os.O_WRONLY)
    os.dup2(devnull, 2)
    os.close(devnull)
    try:
        import onnxruntime  # noqa: F401 — force import during silence
    finally:
        os.dup2(_saved_stderr, 2)
        os.close(_saved_stderr)

    state = AppState()
    app = create_app(state)

    # Red de seguridad: si un KeyboardInterrupt escapa del event loop de
    # Textual (p.ej. durante la carga antes de que el loop arranque), los
    # atexit handlers de concurrent.futures y multiprocessing intentarán
    # join() del executor thread y del warm-cache subprocess → hang. Nuestro
    # handler corre ANTES (LIFO) y llama shutdown() para terminarlos.
    def _cleanup_engines() -> None:
        if state.rag is not None:
            state.rag.shutdown()
        if state.docling_engine is not None:
            state.docling_engine.shutdown()

    atexit.register(_cleanup_engines)

    config = uvicorn.Config(
        app,
        host=host,
        port=port,
        log_level="error",
        access_log=False,
    )
    server = _Server(config)

    CognitsTUI(state, server, port).run()


def _cleanup_legacy_sidecar() -> None:
    rag_dir = paths.data_dir(create=False) / "rag"
    shutil.rmtree(rag_dir / "venv", ignore_errors=True)
    for name in ("sidecar.py", "requirements.txt"):
        try:
            (rag_dir / name).unlink()
        except OSError:
            pass


def _port_available(host: str, port: int) -> bool:
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        s.bind((host, port))
    except OSError:
        return False
    finally:
        s.close()
    return True


def _kill_port(port: int) -> bool:
    """Kill the process listening on `port`. Returns True on success."""
    import platform
    import subprocess
    try:
        if platform.system() == "Windows":
            out = subprocess.check_output(
                f"netstat -ano | findstr :{port}",
                shell=True, text=True,
            )
            for line in out.strip().split("\n"):
                if "LISTENING" not in line:
                    continue
                parts = line.strip().split()
                if len(parts) >= 5:
                    subprocess.run(
                        ["taskkill", "/F", "/PID", parts[-1]],
                        capture_output=True,
                    )
        else:
            result = subprocess.run(
                f"fuser -k {port}/tcp",
                shell=True, capture_output=True, timeout=5,
            )
            if result.returncode != 0:
                subprocess.run(
                    f"lsof -ti :{port} | xargs kill -9",
                    shell=True, capture_output=True,
                )
        return True
    except Exception:
        return False


if __name__ == "__main__":
    main()
