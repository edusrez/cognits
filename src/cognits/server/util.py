"""Helpers compartidos por los handlers HTTP."""

from __future__ import annotations

from fastapi.responses import PlainTextResponse


def text_error(msg: str, status_code: int) -> PlainTextResponse:
    # Paridad con http.Error de Go: texto plano con salto de línea final.
    return PlainTextResponse(msg + "\n", status_code=status_code)


def atoi(s: str | None) -> int:
    # strconv.Atoi con error → 0.
    try:
        return int(s or "")
    except ValueError:
        return 0


def mask_key(key: str) -> str:
    """Las claves nunca salen en claro por la API: GET devuelve "••••" + los
    últimos 4 y PUT conserva la clave guardada si recibe ese valor de vuelta."""
    if not key:
        return ""
    if len(key) <= 4:
        return "••••"
    return "••••" + key[-4:]
