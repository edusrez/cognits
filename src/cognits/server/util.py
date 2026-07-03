"""Helpers shared by the HTTP handlers."""

from __future__ import annotations

from fastapi.responses import PlainTextResponse


def text_error(msg: str, status_code: int) -> PlainTextResponse:
    # Parity with Go's http.Error: plain text with a trailing newline.
    return PlainTextResponse(msg + "\n", status_code=status_code)


def atoi(s: str | None) -> int:
    # strconv.Atoi with error → 0.
    try:
        return int(s or "")
    except ValueError:
        return 0


def mask_key(key: str) -> str:
    """Keys never leave the API in the clear: GET returns "••••" + the last
    4 chars, and PUT keeps the stored key when that value is echoed back."""
    if not key:
        return ""
    if len(key) <= 4:
        return "••••"
    return "••••" + key[-4:]


# Explicit lists instead of strftime %A/%B: those are locale-dependent.
MONTHS = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]
WEEKDAYS = [
    "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday",
]
