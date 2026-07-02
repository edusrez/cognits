"""REST API tests for /api/skills endpoints.

Uses httpx.AsyncClient against an in-process FastAPI app (same pattern
as test_sse.py). Every test works against a tmp_path DB seeded with
small skill trees.
"""

import asyncio
import json
import os

import httpx
import pytest

from cognits.server.app import AppState, create_app
from cognits.storage.db import ReportStore, Skill, new_skill_id


# --- helpers ---------------------------------------------------------

def _skill(name: str, domain: str = "python") -> Skill:
    return Skill(id=new_skill_id(), domain=domain, name=name, description=name, source="test")


def _seed(store: ReportStore, *skills: Skill):
    for s in skills:
        store.upsert_skill(s)


def _state():
    s = AppState()
    return s


async def _get(client: httpx.AsyncClient, path: str, status: int = 200):
    res = await client.get(path)
    assert res.status_code == status
    return res.json() if status == 200 else None


# --- test suite ------------------------------------------------------

@pytest.fixture
def client_and_store(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    state = _state()
    state.skills = ReportStore(tmp_path / "test.db")
    app = create_app(state)
    async def _inner():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
            yield c, state.skills
    return _inner


def test_list_skills_empty(tmp_path, monkeypatch):
    async def run():
        state = _state()
        state.skills = ReportStore(tmp_path / "db.db")
        app = create_app(state)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
            data = await _get(c, "/api/skills")
            assert data == {"skills": []}
    asyncio.run(run())


def test_list_skills_after_upsert(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    async def run():
        store = ReportStore(tmp_path / "db.db")
        _seed(store, _skill("A"), _skill("B"), _skill("C"))
        state = _state(); state.skills = store
        app = create_app(state)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
            data = await _get(c, "/api/skills")
            assert len(data["skills"]) == 3
            names = {s["name"] for s in data["skills"]}
            assert names == {"A", "B", "C"}
    asyncio.run(run())


def test_list_skills_filter_by_domain(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    async def run():
        store = ReportStore(tmp_path / "db.db")
        _seed(store, _skill("A", "python"), _skill("B", "python"), _skill("C", "godot"))
        state = _state(); state.skills = store
        app = create_app(state)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
            data = await _get(c, "/api/skills?domain=python")
            assert len(data["skills"]) == 2
            names = {s["name"] for s in data["skills"]}
            assert names == {"A", "B"}
            data2 = await _get(c, "/api/skills?domain=godot")
            assert len(data2["skills"]) == 1
    asyncio.run(run())


def test_get_skill_tree(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    async def run():
        store = ReportStore(tmp_path / "db.db")
        a = _skill("A"); store.upsert_skill(a)
        b = _skill("B"); store.upsert_skill(b)
        store.add_edge(b.id, a.id, "soft_prereq", build_id="")
        state = _state(); state.skills = store
        app = create_app(state)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
            data = await _get(c, "/api/skills/tree")
            assert len(data["skills"]) == 2
            assert len(data["edges"]) == 1
            assert data["treeVersion"] == 1
            assert data["edges"][0]["edgeType"] == "soft_prereq"
    asyncio.run(run())


def test_get_tree_version(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    async def run():
        store = ReportStore(tmp_path / "db.db")
        _seed(store, _skill("X"))
        state = _state(); state.skills = store
        app = create_app(state)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
            data = await _get(c, "/api/skills/tree")
            assert data["treeVersion"] == 1
            store.bump_tree_version()
            data2 = await _get(c, "/api/skills/tree")
            assert data2["treeVersion"] == 2
    asyncio.run(run())


def test_get_learner_state_existing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    async def run():
        store = ReportStore(tmp_path / "db.db")
        s = _skill("A"); store.upsert_skill(s)
        state = _state(); state.skills = store
        app = create_app(state)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
            data = await _get(c, f"/api/skills/{s.id}/state")
            assert data["skillId"] == s.id
            assert data["alpha"] == 1.0
            assert data["beta"] == 1.0
            assert data["pMastery"] == 0.5
            assert data["statusEnum"] == "not_seen"
    asyncio.run(run())


def test_get_learner_state_not_found(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    async def run():
        store = ReportStore(tmp_path / "db.db")
        _seed(store, _skill("A"))
        state = _state(); state.skills = store
        app = create_app(state)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
            await _get(c, "/api/skills/k_nonexistent/state", status=404)
    asyncio.run(run())


def test_list_skills_includes_tree_version(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    async def run():
        store = ReportStore(tmp_path / "db.db")
        _seed(store, _skill("A"))
        state = _state(); state.skills = store
        app = create_app(state)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
            data = await _get(c, "/api/skills")
            assert data["skills"][0]["treeVersion"] == 1
    asyncio.run(run())


def test_skills_list_returns_json_fields(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    async def run():
        store = ReportStore(tmp_path / "db.db")
        _seed(store, _skill("A", "python"))
        state = _state(); state.skills = store
        app = create_app(state)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
            data = await _get(c, "/api/skills")
            s = data["skills"][0]
            for k in ("id", "domain", "name", "status", "treeVersion", "bloomLevel", "difficulty"):
                assert k in s, f"missing key {k}"
    asyncio.run(run())