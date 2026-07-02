"""HTTP tests for routes_notes.py: CRUD + reorder."""

import asyncio

import httpx


async def _create_note(app, title="test note"):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
        resp = await client.post("/api/notes", json={"title": title})
        assert resp.status_code == 200
        return resp.json()["id"]


def test_create_and_get_note(real_state):
    state, app = real_state
    nid = asyncio.run(_create_note(app))

    async def get():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
            resp = await client.get(f"/api/notes/{nid}")
            assert resp.status_code == 200
            assert resp.json()["title"] == "test note"
    asyncio.run(get())


def test_list_notes(real_state):
    state, app = real_state
    asyncio.run(_create_note(app, "note1"))
    asyncio.run(_create_note(app, "note2"))

    async def list_all():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
            resp = await client.get("/api/notes")
            assert resp.status_code == 200
            assert len(resp.json()) == 2
    asyncio.run(list_all())


def test_delete_note(real_state):
    state, app = real_state
    nid = asyncio.run(_create_note(app))

    async def delete():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
            resp = await client.delete(f"/api/notes/{nid}")
            assert resp.status_code == 204
            assert state.notes.get(nid) is None
    asyncio.run(delete())
