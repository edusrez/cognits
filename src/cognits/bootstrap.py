"""Server wrapper, logging setup, and port helpers."""

from __future__ import annotations

import logging
import logging.handlers
import os
import shutil
import sys
from pathlib import Path

import uvicorn

from cognits import paths

_log_file: Path | None = None
_log_handler: logging.Handler | None = None


def _setup_file_logging() -> None:
    global _log_file, _log_handler
    try:
        data_dir = paths.data_dir(create=True)
        _log_file = data_dir / "cognits.log"
        _log_handler = logging.FileHandler(str(_log_file), delay=True)
        _log_handler.setLevel(logging.DEBUG)
        _log_handler.setFormatter(logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S",
        ))
        root = logging.getLogger()
        root.addHandler(_log_handler)
        root.setLevel(logging.DEBUG)
    except Exception:
        pass


def _log_exception(msg: str, exc: Exception) -> None:
    import traceback
    try:
        traceback.print_exc()
    except Exception:
        pass
    if _log_handler is not None:
        try:
            _log_handler.emit(logging.LogRecord(
                "cognits", logging.ERROR, "", 0, msg, (), exc,
            ))
        except Exception:
            pass


class _Server(uvicorn.Server):
    def install_signal_handlers(self) -> None:
        pass


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
