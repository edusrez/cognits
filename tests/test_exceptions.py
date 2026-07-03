"""Tests for server/exceptions.py: CognitsError hierarchy + handler shape."""

import json

import httpx
import pytest


def test_cognits_error_base():
    from cognits.server.exceptions import CognitsError
    e = CognitsError("msg")
    assert e.message == "msg"
    assert e.code == "INTERNAL_ERROR"
    assert e.http_status == 500
    assert e.details == {}


def test_not_found_error():
    from cognits.server.exceptions import NotFoundError
    e = NotFoundError("missing")
    assert e.code == "NOT_FOUND"
    assert e.http_status == 404


def test_session_not_found():
    from cognits.server.exceptions import SessionNotFound
    e = SessionNotFound("s1")
    assert e.code == "NOT_FOUND"
    assert e.http_status == 404
    assert e.details.get("session_id") == "s1"


def test_agent_busy():
    from cognits.server.exceptions import AgentBusy
    e = AgentBusy("s1")
    assert e.code == "AGENT_BUSY"
    assert e.http_status == 409


def test_config_error():
    from cognits.server.exceptions import ConfigError
    e = ConfigError("bad", {"field": "x"})
    assert e.code == "CONFIG_ERROR"
    assert e.http_status == 400
    assert e.details["field"] == "x"


def test_storage_error():
    from cognits.server.exceptions import StorageError
    e = StorageError("db fail")
    assert e.code == "STORAGE_ERROR"
    assert e.http_status == 500


def test_session_not_found_is_not_found():
    from cognits.server.exceptions import NotFoundError, SessionNotFound
    assert isinstance(SessionNotFound("x"), NotFoundError)


def test_handler_returns_json(real_app):
    from cognits.server.exceptions import NotFoundError

    async def go():
        transport = httpx.ASGITransport(app=real_app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
            resp = await c.get("/api/reports/nonexistent")
            assert resp.status_code == 404
            data = resp.json()
            assert "error" in data
            assert "message" in data
    import asyncio
    asyncio.run(go())
