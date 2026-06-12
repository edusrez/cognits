"""Port of internal/server/browser.go: opens the system browser."""

from __future__ import annotations

import subprocess
import sys
import time


def _spawn(args: list[str]) -> bool:
    try:
        subprocess.Popen(
            args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        return True
    except OSError:
        return False


def _run_ok(args: list[str]) -> bool:
    try:
        return (
            subprocess.run(
                args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            ).returncode
            == 0
        )
    except OSError:
        return False


def is_wsl() -> bool:
    try:
        with open("/proc/version", encoding="utf-8") as f:
            return "microsoft" in f.read().lower()
    except OSError:
        return False


def open_browser(base_url: str) -> None:
    url = f"{base_url}?v={int(time.time())}"

    if is_wsl():
        for args in (
            ["cmd.exe", "/c", "start", url],
            ["powershell.exe", "-Command", "Start-Process", url],
        ):
            if _run_ok(args):
                return

    if sys.platform.startswith("linux"):
        _spawn(["xdg-open", url])
    elif sys.platform == "darwin":
        _spawn(["open", url])
    elif sys.platform == "win32":
        _spawn(["rundll32", "url.dll,FileProtocolHandler", url])
