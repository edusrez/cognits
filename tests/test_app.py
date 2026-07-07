"""Tests for server/app.py: drain timeout configuration, cancel-suppress middleware, and rag_or_none."""

import asyncio
import os

import pytest

import cognits.server.app as app_mod
from cognits.rag.engine import RagEngine


def test_drain_timeout_exists():
    assert isinstance(app_mod._DRAIN_TIMEOUT, float)
    assert app_mod._DRAIN_TIMEOUT > 0


def test_drain_timeout_uses_env_default():
    assert app_mod._DRAIN_TIMEOUT == 5.0


@pytest.mark.asyncio
async def test_cancel_suppress_unit():
    """Unit test: CancelledError BEFORE response start re-raises."""
    async def inner_app(scope, receive, send):
        raise asyncio.CancelledError()

    wrapped = app_mod._CancelSuppressMiddleware(inner_app)
    # Response hasn't started — CancelledError should propagate.
    with pytest.raises(asyncio.CancelledError):
        await wrapped({"type": "http"}, lambda: None, lambda m: None)


@pytest.mark.asyncio
async def test_cancel_suppress_after_response_started():
    """Unit test: CancelledError AFTER response start is swallowed."""
    async def inner_app(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        raise asyncio.CancelledError()

    send_messages: list = []

    async def capture_send(message):
        send_messages.append(message)

    wrapped = app_mod._CancelSuppressMiddleware(inner_app)
    # Response started — CancelledError should be swallowed.
    await wrapped({"type": "http"}, lambda: None, capture_send)
    assert send_messages[0]["type"] == "http.response.start"


@pytest.mark.asyncio
async def test_cancel_suppress_integration(real_app):
    """Integration: a route that raises CancelledError before response."""
    from fastapi import FastAPI
    from starlette.middleware import Middleware
    from starlette.testclient import TestClient

    # Build a minimal app with the middleware and a cancelling route.
    inner = FastAPI()
    inner.middleware_stack = None  # force rebuild on next build_middleware_stack call
    inner.user_middleware.insert(0, Middleware(app_mod._CancelSuppressMiddleware))

    @inner.get("/cancel-me")
    async def cancel_me():
        raise asyncio.CancelledError()

    client = TestClient(inner, raise_server_exceptions=False)
    # CancelledError before response start propagates to the ASGI transport,
    # which TestClient catches — the response may be empty/500.
    resp = client.get("/cancel-me")
    assert resp.status_code in (200, 500)


@pytest.mark.asyncio
async def test_cancel_suppress_passthrough(real_app):
    """Normal requests pass through the middleware unchanged."""
    from starlette.testclient import TestClient

    client = TestClient(real_app, raise_server_exceptions=False)
    resp = client.get("/api/health")
    assert resp.status_code == 200


# --- rag_or_none tests ---


def test_rag_or_none_returns_none_when_rag_is_none():
    """rag_or_none returns None when rag is not set."""
    state = app_mod.AppState()
    state.rag = None
    assert state.rag_or_none is None


def test_rag_or_none_returns_none_when_ready_not_set():
    """rag_or_none returns None when RAG engine exists but is not ready."""
    state = app_mod.AppState()
    state.rag = RagEngine()
    assert state.rag.error is None
    assert not state.rag.ready.is_set()
    assert state.rag_or_none is None


def test_rag_or_none_returns_engine_when_ready():
    """rag_or_none returns the engine when ready.is_set() + no error."""
    state = app_mod.AppState()
    state.rag = RagEngine()
    state.rag.ready.set()
    assert state.rag_or_none is state.rag


def test_rag_or_none_returns_none_when_engine_has_error():
    """rag_or_none returns None when ready but error is set (failed init)."""
    state = app_mod.AppState()
    state.rag = RagEngine()
    state.rag.ready.set()
    state.rag.error = "something went wrong"
    assert state.rag_or_none is None
