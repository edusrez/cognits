"""FastAPI dependency injection helpers.

Provides a get_app_state dependency that FastAPI route handlers can use
instead of the register(app, st) pattern.
"""

from __future__ import annotations

from fastapi import Request


def get_app_state(request: Request):
    """FastAPI dependency: returns the AppState from app.state.ctx."""
    return request.app.state.ctx
