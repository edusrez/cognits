"""HTTP tests for routes_config.py: config/profile CRUD, masking."""

import asyncio

import httpx


def test_get_config_default(real_state):
    state, app = real_state

    async def go():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
            resp = await client.get("/api/config")
            assert resp.status_code == 200
            data = resp.json()
            assert "llmProvider" in data or "model" in data
    asyncio.run(go())


def test_put_config_validation(real_state):
    state, app = real_state

    async def go():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
            resp = await client.put("/api/config", json={"maxSteps": -1})
            assert resp.status_code == 400
            data = resp.json()
            assert data["error"] == "ERROR"
    asyncio.run(go())


def test_get_profile_default(real_state):
    state, app = real_state

    async def go():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
            resp = await client.get("/api/profile")
            assert resp.status_code == 200
    asyncio.run(go())


def test_delete_setup_state(real_state):
    state, app = real_state

    async def go():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
            resp = await client.delete("/api/setup/state")
            assert resp.status_code == 204
        # After delete, config should not be None
        assert state.cached_config is not None
    asyncio.run(go())
