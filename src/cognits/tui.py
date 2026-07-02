"""Textual TUI: spinner, menu, server lifecycle, and graceful shutdown."""

from __future__ import annotations

import asyncio
import logging
import signal
import sys
import threading

from textual import on, events
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import VerticalGroup
from textual.theme import Theme
from textual.widgets import Label, OptionList, Static
from textual.widgets.option_list import Option

from cognits import __version__
from cognits.bootstrap import _Server, _log_exception, _log_handler
from cognits.server.app import AppState
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


class CognitsTUI(App):
    """Single-screen TUI: progress bar → interactive menu inside a bordered panel."""

    CSS = CSS
    ENABLE_COMMAND_PALETTE = False
    NOTIFICATION_TIMEOUT = 0
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
                yield Static("[dim]  (\u2191\u2193 arrows, Enter to select)[/dim]", id="menu-hint")

            with VerticalGroup(id="running-container", classes="hidden"):
                yield Static(
                    "Server running\n\nPress [bold]Ctrl+Q[/bold] to stop",
                    id="running-label",
                )

    def on_mount(self) -> None:
        self.register_theme(COGNITS_THEME)
        self.theme = "cognits-dark"

        _should_exit = False

        def _on_term(signum: int, frame: object) -> None:
            nonlocal _should_exit
            if _should_exit:
                return
            _should_exit = True
            try:
                self.call_later(self.exit)
            except Exception:
                self.exit()

        if hasattr(signal, "SIGHUP"):
            signal.signal(signal.SIGHUP, _on_term)
        signal.signal(signal.SIGTERM, _on_term)

        self._server_thread = threading.Thread(
            target=self._run_server_thread,
            daemon=False,
        )
        self._server_thread.start()

        self.run_worker(self._check_rag())

    def _run_server_thread(self) -> None:
        try:
            asyncio.run(self._run_server())
        except Exception:
            _log_exception("Server thread crashed", sys.exc_info()[1])
            try:
                self.call_from_thread(self.exit)
            except Exception:
                pass

    async def _run_server(self) -> None:
        await self._server.serve()

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
                while not rag.ready.is_set() and not rag.error:
                    self.query_one("#download-label", Label).update(
                        "Downloading BGE-M3\u2026"
                    )
                    spinner_frame = (spinner_frame + 1) % len(SPINNER)
                    self.query_one("#loading-indicator", Static).update(
                        SPINNER[spinner_frame]
                    )
                    await asyncio.sleep(1 / 12)
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
        self.run_worker(self._watch_memory())

    async def _watch_memory(self) -> None:
        import gc
        while True:
            await asyncio.sleep(15)
            try:
                import resource
                rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
                rss_mb = rss // 1024
                from cognits.agent import agent as agent_mod
                agent_mod.set_memory_pressure(rss_mb)
                if _log_handler is not None:
                    _log_handler.emit(logging.LogRecord(
                        "cognits.mem", logging.DEBUG, "", 0,
                        f"RSS memory: {rss_mb} MB", (), None,
                    ))
                if rss_mb > 6200:
                    gc.collect()
                    if _log_handler is not None:
                        _log_handler.emit(logging.LogRecord(
                            "cognits.mem", logging.WARNING, "", 0,
                            f"High memory ({rss_mb} MB) — forced GC", (), None,
                        ))
                if rss_mb > 6800:
                    if _log_handler is not None:
                        _log_handler.emit(logging.LogRecord(
                            "cognits.mem", logging.CRITICAL, "", 0,
                            f"Critical memory ({rss_mb} MB) — near OOM limit", (), None,
                        ))
            except Exception:
                pass

    def _show_ready(self) -> None:
        self.query_one("#loading-container").add_class("hidden")
        self._show_menu()

    def _show_menu(self) -> None:
        self.query_one("#menu-container").remove_class("hidden")
        self.call_after_refresh(
            self.query_one("#menu", OptionList).focus
        )

    @on(OptionList.OptionSelected)
    def _on_menu(self, event: OptionList.OptionSelected) -> None:
        if event.option_id == "open":
            open_browser(self._url)
            self.query_one("#menu-container").add_class("hidden")
            self.query_one("#running-container").remove_class("hidden")
            self.set_focus(None)
        elif event.option_id == "close":
            self.exit()

    async def _shutdown(self) -> None:
        if self._server_thread is not None:
            self._server.should_exit = True
            self._server_thread.join(timeout=8)
            if self._server_thread.is_alive():
                self._server.force_exit = True
                self._server_thread.join(timeout=2)
        try:
            if self._state.report_store is not None:
                self._state.report_store.shutdown()
        except Exception:
            pass
        try:
            if self._state.rag is not None:
                self._state.rag.shutdown()
        except Exception:
            pass
        try:
            if self._state.docling_engine is not None:
                self._state.docling_engine.shutdown()
        except Exception:
            pass
        await super()._shutdown()
