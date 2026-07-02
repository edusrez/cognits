"""HTTP tests for routes_sessions.py: CRUD, reorder, delete cascade."""

import asyncio

import httpx


async def _create_session(app):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
        resp = await client.post("/api/sessions", json={"name": "test"})
        assert resp.status_code == 200
        data = resp.json()
        assert "id" in data
        return data["id"]


def test_create_and_list_sessions(real_app):
    sid = asyncio.run(_create_session(real_app))

    async def list_sessions():
        transport = httpx.ASGITransport(app=real_app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
            resp = await client.get("/api/sessions")
            assert resp.status_code == 200
            sessions = resp.json()
            assert any(s["id"] == sid for s in sessions)
    asyncio.run(list_sessions())


def test_rename_session(real_app):
    sid = asyncio.run(_create_session(real_app))

    async def rename():
        transport = httpx.ASGITransport(app=real_app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
            resp = await client.put(f"/api/sessions/{sid}", json={"name": "renamed"})
            assert resp.status_code == 204
    asyncio.run(rename())


def test_delete_session_cascade(real_state):
    state, app = real_state
    sid = asyncio.run(_create_session(app))
    # Seed a message so we can verify cascade
    from cognits.storage.models import MessageRow
    state.messages.save(sid, [MessageRow(role="user", content="hi")])

    async def delete():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
            resp = await client.delete(f"/api/sessions/{sid}")
            assert resp.status_code == 204
            msgs = state.messages.load(sid)
            assert len(msgs) == 0
    asyncio.run(delete())
