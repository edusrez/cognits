"""Entry point: argument parsing, port resolution, server launch, uninstall."""

from __future__ import annotations

import argparse
import atexit
import logging
import os
import shutil
import sys
import time
from pathlib import Path

import uvicorn

from cognits import __version__, paths
from cognits.bootstrap import (
    _Server,
    _cleanup_legacy_sidecar,
    _kill_port,
    _port_available,
    _setup_file_logging,
)
from cognits.server.app import DEFAULT_PORT, AppState, create_app
from cognits.tui import CognitsTUI


def _interactive_uninstall(skip_confirm: bool = False) -> None:
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


def main() -> None:
    os.environ.setdefault("ORT_LOG_LEVEL", "ERROR")

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
        for _ in range(8):
            time.sleep(0.5)
            if _port_available(host, port):
                break
        else:
            print(f"Port {port} already in use — is Cognits already running?",
                  file=sys.stderr)
            raise SystemExit(1)

    _cleanup_legacy_sidecar()
    _setup_file_logging()

    try:
        with open(f"/proc/{os.getpid()}/oom_score_adj", "w") as f:
            f.write("-500")
    except Exception:
        pass

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

    def _cleanup_engines() -> None:
        if state.report_store is not None:
            try:
                state.report_store.shutdown()
            except Exception:
                pass
        if state.rag is not None:
            state.rag.shutdown()
        if state.docling_engine is not None:
            state.docling_engine.shutdown()

    atexit.register(_cleanup_engines)

    config = uvicorn.Config(
        app,
        host=host,
        port=port,
        log_level="warning",
        access_log=False,
    )
    server = _Server(config)

    CognitsTUI(state, server, port).run()


if __name__ == "__main__":
    main()
