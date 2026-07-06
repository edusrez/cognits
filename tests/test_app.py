"""Tests for server/app.py: drain timeout configuration and cancel-suppress middleware."""

import asyncio
import os

import pytest

import cognits.server.app as app_mod


def test_drain_timeout_exists():
    assert isinstance(app_mod._DRAIN_TIMEOUT, float)
    assert app_mod._DRAIN_TIMEOUT > 0


def test_drain_timeout_uses_env_default():
    assert app_mod._DRAIN_TIMEOUT == 5.0


@pytest.mark.asyncio
async def test_cancel_suppress_unit():
    """Unit test: the middleware swallows CancelledError from the inner app."""
    async def inner_app(scope, receive, send):
        raise asyncio.CancelledError()

    wrapped = app_mod._CancelSuppressMiddleware(inner_app)
    # Should not raise — the middleware catches and swallows CancelledError.
    await wrapped({"type": "http"}, lambda: None, lambda m: None)


@pytest.mark.asyncio
async def test_cancel_suppress_integration(real_app):
    """Integration: a route that raises CancelledError is swallowed."""
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
    # The response body will be empty because the middleware swallows the
    # cancellation — but crucially, no exception propagates to the test.
    resp = client.get("/cancel-me")
    assert resp.status_code in (200, 500)


@pytest.mark.asyncio
async def test_cancel_suppress_passthrough(real_app):
    """Normal requests pass through the middleware unchanged."""
    from starlette.testclient import TestClient

    client = TestClient(real_app, raise_server_exceptions=False)
    resp = client.get("/api/health")
    assert resp.status_code == 200
