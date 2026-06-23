"""Entry point for Cognits.

Starts the local HTTP server inside a Textual TUI: progress bar + menu
(Open Web / Close) → running state, all inside a single bordered panel.
"""

from __future__ import annotations

import argparse
import asyncio
import atexit
import json
import logging
import os
import shutil
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import uvicorn
from textual import on, events
from textual.app import App, ComposeResult, Screen
from textual.binding import Binding
from textual.containers import HorizontalGroup, VerticalGroup
from textual.theme import Theme
from textual.widgets import Button, Footer, Input, Label, OptionList, RichLog, Static
from textual.widgets.option_list import Option

from cognits import __version__, paths
from cognits.agent.agent import Agent, AgentConfig
from cognits.agent.prompts import ONBOARDING_SYSTEM_PROMPT
from cognits.agent.subagents import directory_reader_config, researcher_config
from cognits.agent.tool_deploy import DeploySubagent
from cognits.llm.deepseek import DeepSeekClient
from cognits.llm.types import ROLE_ASSISTANT, ROLE_SYSTEM, ROLE_USER, Message
from cognits.server.app import DEFAULT_PORT, AppState, create_app
from cognits.server.browser import open_browser
from cognits.storage.files import Config, StudentProfile
from cognits.tinyfish import TinyfishClient
from cognits.tools import Registry

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


# ---------------------------------------------------------------------------
# Setup Wizard Screen
# ---------------------------------------------------------------------------

SETUP_CSS = """
SetupScreen {
    align: center middle;
    background: #0D0D0D;
}

#setup-panel {
    border: solid #555;
    padding: 1 2;
    width: 70;
    max-height: 90vh;
    background: #111111;
}

#setup-header {
    text-align: center;
    width: 100%;
    padding-bottom: 1;
}

.setup-step {
    width: 100%;
}

.setup-label {
    width: 100%;
    padding-top: 1;
    padding-bottom: 1;
}

.setup-input {
    width: 100%;
    margin-bottom: 1;
}

.setup-buttons {
    width: 100%;
    padding-top: 1;
}

.setup-buttons Button {
    margin-right: 1;
}

#onboarding-log {
    height: 1fr;
    border: solid #333;
    margin-bottom: 1;
    overflow-y: auto;
}

.hidden {
    display: none;
}
"""


class SetupScreen(Screen):
    CSS = SETUP_CSS

    BINDINGS = [
        Binding("ctrl+c", "quit", "Quit", show=False, priority=True),
        Binding("escape", "quit", "Quit", show=False, priority=True),
    ]

    def __init__(self, state: AppState) -> None:
        super().__init__()
        self._state = state
        self._api_key: str = ""
        self._tinyfish_key: str = ""
        self._project_goal: str = ""
        self._agent: Agent | None = None
        self._llm_client: DeepSeekClient | None = None
        self._messages: list[Message] = []
        self._current_response: str = ""
        self._profile_complete: bool = False
        self._declared: dict = {}

    def compose(self) -> ComposeResult:
        with VerticalGroup(id="setup-panel"):
            yield Static(
                f"[bold]Cognits[/bold] [dim italic]v{__version__}[/dim italic]\n"
                "[dim]Initial Setup[/dim]",
                id="setup-header",
            )

            with VerticalGroup(id="step-api-keys", classes="setup-step"):
                yield Label(
                    "First, configure your AI provider API key.\n"
                    "This key is encrypted and stored locally.",
                    classes="setup-label",
                )
                yield Input(
                    placeholder="DeepSeek API Key (required)",
                    password=True,
                    id="input-api-key",
                    classes="setup-input",
                )
                yield Input(
                    placeholder="TinyFish API Key (optional, for web search)",
                    password=True,
                    id="input-tinyfish-key",
                    classes="setup-input",
                )
                with HorizontalGroup(classes="setup-buttons"):
                    yield Button("Continue \u2192", id="btn-api-continue", variant="primary")
                    yield Button("Skip setup", id="btn-skip", variant="default")

            with VerticalGroup(id="step-project", classes="setup-step hidden"):
                yield Label(
                    "What do you want to learn or build?\n"
                    "Describe your project or learning goal.",
                    classes="setup-label",
                )
                yield Input(
                    placeholder="e.g., Learn Rust to build a CLI tool",
                    id="input-project",
                    classes="setup-input",
                )
                with HorizontalGroup(classes="setup-buttons"):
                    yield Button("\u2190 Back", id="btn-project-back", variant="default")
                    yield Button("Start Onboarding \u2192", id="btn-project-continue", variant="primary")

            with VerticalGroup(id="step-onboarding", classes="setup-step hidden"):
                yield RichLog(id="onboarding-log", highlight=True, markup=True, wrap=True)
                yield Input(
                    placeholder="Type your answer... (Ctrl+D when done)",
                    id="onboarding-input",
                    classes="setup-input",
                    disabled=True,
                )

            with VerticalGroup(id="step-summary", classes="setup-step hidden"):
                yield Static(id="summary-text", classes="setup-label")
                with HorizontalGroup(classes="setup-buttons"):
                    yield Button("Save & Launch \u2192", id="btn-launch", variant="primary")

    def on_mount(self) -> None:
        self.query_one("#input-api-key", Input).focus()

    # -- Step 1: API Keys ---------------------------------------------------

    @on(Button.Pressed, "#btn-api-continue")
    def _on_api_continue(self) -> None:
        self._api_key = self.query_one("#input-api-key", Input).value.strip()
        self._tinyfish_key = self.query_one("#input-tinyfish-key", Input).value.strip()
        if not self._api_key:
            self.notify("API key is required to continue", severity="error")
            return
        self._show_step("step-project")
        self.query_one("#input-project", Input).focus()

    @on(Button.Pressed, "#btn-skip")
    def _on_skip(self) -> None:
        self.dismiss(False)

    # -- Step 2: Project Goal -----------------------------------------------

    @on(Button.Pressed, "#btn-project-back")
    def _on_project_back(self) -> None:
        self._show_step("step-api-keys")
        self.query_one("#input-api-key", Input).focus()

    @on(Button.Pressed, "#btn-project-continue")
    def _on_project_continue(self) -> None:
        goal = self.query_one("#input-project", Input).value.strip()
        if not goal:
            self.notify("Please describe your project or goal", severity="error")
            return
        self._project_goal = goal
        self._show_step("step-onboarding")
        self._start_onboarding()

    # -- Step 3: Onboarding --------------------------------------------------

    def _start_onboarding(self) -> None:
        self._llm_client = DeepSeekClient(self._api_key)

        subagent_map: dict[str, AgentConfig] = {
            "directory_reader": directory_reader_config(
                "deepseek-v4-flash", "high", 50,
                docling_engine=self._state.docling_engine if self._state.docling_engine is not None and self._state.docling_engine.error is None else None,
                docling_config=self._state.cached_config.docling_config if self._state.cached_config else None,
            ),
        }

        if self._tinyfish_key:
            tf_client = TinyfishClient(self._tinyfish_key)
            subagent_map["web_researcher"] = researcher_config(
                "deepseek-v4-flash", "high", 100, tf_client,
            )

        deploy_tool = DeploySubagent(
            llm_client=self._llm_client,
            report_store=None,
            subagents=subagent_map,
            session_id=None,
            emit=None,
            rag_engine=None,
            tinyfish_api_key=self._tinyfish_key,
        )
        registry = Registry()
        registry.register(deploy_tool)

        cfg = AgentConfig(
            name="onboarding",
            model="deepseek-v4-pro",
            reasoning="max",
            max_steps=999,
            system_prompt=ONBOARDING_SYSTEM_PROMPT,
            tools=registry,
            subagents=subagent_map,
        )
        self._agent = Agent(cfg, self._llm_client)
        self._messages = []
        self._current_response = ""
        self._profile_complete = False

        log = self.query_one("#onboarding-log", RichLog)
        log.clear()
        cwd_name = Path.cwd().name
        first_msg = (
            f"The project directory is named '{cwd_name}'. "
            f"The user described their goal as: {self._project_goal}. "
            f"Start the onboarding interview. Ask your first question."
        )
        self._messages = [Message(role=ROLE_SYSTEM, content=ONBOARDING_SYSTEM_PROMPT)]
        self._messages.append(Message(role=ROLE_USER, content=first_msg))

        self.run_worker(self._onboarding_turn(), exclusive=True)

    def _onboarding_emit(self, ev: dict) -> None:
        if ev["type"] == "token" and isinstance(ev.get("data"), str):
            self._current_response += ev["data"]

    async def _onboarding_turn(self) -> None:
        log = self.query_one("#onboarding-log", RichLog)
        inp = self.query_one("#onboarding-input", Input)
        inp.disabled = True

        try:
            self._current_response = ""
            await self._agent.run(self._messages, self._onboarding_emit)  # type: ignore[arg-type]
        except Exception as e:
            log.write(f"\n[bold red]Error:[/bold red] {e}\n")
            inp.disabled = False
            inp.focus()
            return

        response = self._current_response.strip()
        if response:
            log.write(f"\n[bold]Tutor:[/bold] {response}\n")
            self._messages.append(Message(role=ROLE_ASSISTANT, content=response))

        if "[PROFILE COMPLETE]" in response:
            self._profile_complete = True
            self._extract_profile(response)
            self._show_step("step-summary")
            summary = self._build_summary()
            self.query_one("#summary-text", Static).update(summary)
            return

        inp.disabled = False
        inp.focus()

    @on(Input.Submitted, "#onboarding-input")
    def _on_onboarding_submit(self, event: Input.Submitted) -> None:
        answer = event.value.strip()
        if not answer:
            return
        log = self.query_one("#onboarding-log", RichLog)
        log.write(f"\n[bold]You:[/bold] {answer}\n")
        self._messages.append(Message(role=ROLE_USER, content=answer))
        event.input.value = ""
        event.input.disabled = True
        self.run_worker(self._onboarding_turn(), exclusive=True)

    # -- Step 4: Summary -----------------------------------------------------

    def _extract_profile(self, response: str) -> None:
        lines = response.split("\n")
        current_field = ""
        for line in lines:
            line = line.strip()
            if line.startswith("- Background:") or line.startswith("Background:"):
                self._declared["background"] = line.split(":", 1)[1].strip()
            elif line.startswith("- Project:") or line.startswith("Project:"):
                self._declared["project"] = line.split(":", 1)[1].strip()
            elif line.startswith("- Experience:") or line.startswith("Experience:"):
                self._declared["experience"] = line.split(":", 1)[1].strip()
            elif line.startswith("- Learning style:") or line.startswith("Learning style:"):
                self._declared["learning_style"] = line.split(":", 1)[1].strip()
            elif line.startswith("- Availability:") or line.startswith("Availability:"):
                self._declared["availability"] = line.split(":", 1)[1].strip()
            elif line.startswith("- Goals:") or line.startswith("Goals:"):
                self._declared["goals"] = line.split(":", 1)[1].strip()

        if "background" in self._declared:
            self._declared.setdefault("goals", self._project_goal)

    def _build_summary(self) -> str:
        parts = ["[bold green]Profile created![/bold green]\n"]
        if self._declared.get("background"):
            parts.append(f"[bold]Background:[/bold] {self._declared['background']}")
        if self._declared.get("project"):
            parts.append(f"[bold]Project:[/bold] {self._declared['project']}")
        if self._declared.get("experience"):
            parts.append(f"[bold]Experience:[/bold] {self._declared['experience']}")
        if self._declared.get("learning_style"):
            parts.append(f"[bold]Learning style:[/bold] {self._declared['learning_style']}")
        if self._declared.get("availability"):
            parts.append(f"[bold]Availability:[/bold] {self._declared['availability']}")
        if self._declared.get("goals"):
            parts.append(f"[bold]Goals:[/bold] {self._declared['goals']}")
        parts.append("\n[dim]Press Save & Launch to start Cognits.[/dim]")
        return "\n".join(parts)

    @on(Button.Pressed, "#btn-launch")
    def _on_launch(self) -> None:
        self._save_and_launch()

    def _save_and_launch(self) -> None:
        if self._state.store is not None:
            # Save config
            cfg = self._state.cached_config or Config()
            cfg.llm_api_key = self._api_key
            cfg.llm_provider = "deepseek"
            if self._tinyfish_key:
                cfg.tinyfish_api_key = self._tinyfish_key
            try:
                self._state.store.save_config(cfg)
                self._state.cached_config = cfg
            except Exception:
                pass

            # Save profile
            profile = StudentProfile(
                declared={
                    "background": self._declared.get("background", ""),
                    "goals": [self._declared.get("goals", self._project_goal)],
                    "experience": self._declared.get("experience", ""),
                    "project": self._declared.get("project", self._project_goal),
                    "preferences": {
                        "style": self._declared.get("learning_style", "socratic"),
                    },
                    "availability": self._declared.get("availability", ""),
                },
                meta={
                    "created": datetime.utcnow().isoformat() + "Z",
                    "sessions": 0,
                    "source": "onboarding",
                },
            )
            try:
                self._state.store.save_profile(profile)
            except Exception:
                pass

            # Save onboarding conversation log
            try:
                log_dir = Path(paths.data_dir()) / "onboarding"
                log_dir.mkdir(parents=True, exist_ok=True)
                ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
                log_path = log_dir / f"{ts}.json"
                log_data = {
                    "timestamp": datetime.now(timezone.utc).isoformat() + "Z",
                    "model": "deepseek-v4-pro",
                    "reasoning": "max",
                    "messages": [
                        {"role": m.role, "content": m.content}
                        for m in self._messages
                    ],
                }
                log_path.write_text(json.dumps(log_data, indent=2, ensure_ascii=False), encoding="utf-8")
            except Exception:
                pass

        self.dismiss(True)

    # -- Helpers -------------------------------------------------------------

    def _show_step(self, step_id: str) -> None:
        for sid in ("step-api-keys", "step-project", "step-onboarding", "step-summary"):
            widget = self.query_one(f"#{sid}")
            if sid == step_id:
                widget.remove_class("hidden")
            else:
                widget.add_class("hidden")


# ---------------------------------------------------------------------------
# TUI Application
# ---------------------------------------------------------------------------

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
        # Run uvicorn in its own thread + event loop so serving static
        # assets never blocks Textual's render loop.
        self._server_thread = threading.Thread(
            target=lambda: asyncio.run(self._run_server()),
            daemon=True,
        )
        self._server_thread.start()

        cfg = self._state.cached_config
        if cfg is None or not cfg.llm_api_key:
            self.run_worker(self._check_first_run())
        else:
            self.run_worker(self._check_rag())

    # -- Server --------------------------------------------------------------

    async def _run_server(self) -> None:
        await self._server.serve()

    # -- First-run detection -----------------------------------------------

    async def _check_first_run(self) -> None:
        setup = SetupScreen(self._state)
        completed = await self.push_screen_wait(setup)
        # Whether completed or skipped, continue to loading/menu.
        self._show_loading()
        self.run_worker(self._check_rag())

    def _show_loading(self) -> None:
        self.query_one("#loading-container").remove_class("hidden")
        self.query_one("#menu-container").add_class("hidden")
        self.query_one("#running-container").add_class("hidden")

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
            self._server_thread.join(timeout=5)
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

    if force:
        _kill_port(port)
        time.sleep(0.5)  # let the OS release the port

    if not _port_available(host, port):
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
            try:
                subprocess.run(
                    f"fuser -k {port}/tcp",
                    shell=True, capture_output=True, timeout=5,
                )
            except Exception:
                subprocess.run(
                    f"lsof -ti :{port} | xargs kill -9",
                    shell=True, capture_output=True,
                )
        return True
    except Exception:
        return False


if __name__ == "__main__":
    main()
