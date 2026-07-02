"""HTTP tests for routes_misc.py: health, tree, agents, messages, config, desktops."""

import asyncio

import httpx


def test_health(real_app):
    async def go():
        transport = httpx.ASGITransport(app=real_app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
            resp = await client.get("/api/health")
            assert resp.status_code == 200
            data = resp.json()
            assert data["status"] == "ok"
    asyncio.run(go())


def test_tree(real_app):
    async def go():
        transport = httpx.ASGITransport(app=real_app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
            resp = await client.get("/api/tree")
            assert resp.status_code == 200
            data = resp.json()
            assert "name" in data
    asyncio.run(go())


def test_agents(real_app):
    async def go():
        transport = httpx.ASGITransport(app=real_app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
            resp = await client.get("/api/agents")
            assert resp.status_code == 200
            data = resp.json()
            assert "web_researcher" in data
    asyncio.run(go())


def test_session_config_default(real_app):
    async def go():
        transport = httpx.ASGITransport(app=real_app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
            resp = await client.get("/api/sessions/nonexistent/config")
            assert resp.status_code == 200
            data = resp.json()
            assert "model" in data
    asyncio.run(go())
