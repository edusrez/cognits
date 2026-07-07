"""HTTP tests for routes_study.py: GET + POST study plan endpoints."""

from __future__ import annotations

import asyncio

import httpx

from cognits.constants import MASTERY_PROFICIENT_P, STUDY_PLAN_MAX_ITEMS
from cognits.storage.models import LearnerState, Skill


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _seed_mini_tree(skills_repo, learner_state_repo):
    """Seed a 3-skill chain: Addition -> Subtraction -> Multiplication."""
    sk_a = Skill(id="k_test_a", name="Addition", domain="math",
                 description="Adding numbers", bloom_level="apply",
                 difficulty=0.3)
    sk_b = Skill(id="k_test_b", name="Subtraction", domain="math",
                 description="Subtracting numbers", bloom_level="apply",
                 difficulty=0.4)
    sk_c = Skill(id="k_test_c", name="Multiplication", domain="math",
                 description="Multiplying numbers", bloom_level="apply",
                 difficulty=0.5)

    skills_repo.upsert(sk_a)
    skills_repo.upsert(sk_b)
    skills_repo.upsert(sk_c)

    skills_repo.add_edge("k_test_b", "k_test_a", edge_type="prereq")
    skills_repo.add_edge("k_test_c", "k_test_b", edge_type="prereq")

    # Mark Addition as mastered (prereq satisfied) so Subtraction is frontier.
    learner_state_repo.upsert(LearnerState(
        skill_id="k_test_a", p_mastery=MASTERY_PROFICIENT_P + 0.05,
        status_enum="mastered",
    ))


# ---------------------------------------------------------------------------
# tests
# ---------------------------------------------------------------------------

def test_get_study_plan_empty(real_state):
    """No plan exists → returns plan=None, items=[]."""
    _, app = real_state

    async def do():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
            resp = await client.get("/api/study_plan")
            assert resp.status_code == 200
            body = resp.json()
            assert body["plan"] is None
            assert body["items"] == []
    asyncio.run(do())


def test_post_study_plan_no_tree(real_state):
    """No skills in DB → 409 with a clear message."""
    _, app = real_state

    async def do():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
            resp = await client.post("/api/study_plan", json={"goal": "Addition"})
            assert resp.status_code == 409
            body = resp.json()
            assert "onboarding" in body["message"].lower()
    asyncio.run(do())


def test_post_and_get_study_plan(real_state):
    """POST a plan with a seeded tree → 201 + items; GET returns same plan."""
    state, app = real_state
    _seed_mini_tree(state.skills, state.learner_state)

    async def do():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
            # POST — create plan
            resp = await client.post("/api/study_plan", json={
                "goal": "Multiplication",
                "max_items": 5,
            })
            assert resp.status_code == 201, resp.text
            body = resp.json()
            assert body["plan_id"]
            assert body["goal"] == "Multiplication"
            assert len(body["items"]) >= 1
            assert body["frontier_size"] >= 1

            plan_id = body["plan_id"]

            # GET — retrieve active plan
            resp = await client.get("/api/study_plan")
            assert resp.status_code == 200
            body = resp.json()
            assert body["plan"] is not None
            assert body["plan"]["id"] == plan_id
            assert body["plan"]["goal"] == "Multiplication"
            assert len(body["items"]) >= 1
    asyncio.run(do())


def test_post_supersedes_old(real_state):
    """POST plan A, POST plan B → GET returns only plan B."""
    state, app = real_state
    _seed_mini_tree(state.skills, state.learner_state)

    async def do():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
            # First plan
            resp_a = await client.post("/api/study_plan", json={"goal": "Addition"})
            assert resp_a.status_code == 201
            plan_a_id = resp_a.json()["plan_id"]

            # Second plan (supersedes)
            resp_b = await client.post("/api/study_plan", json={"goal": "Subtraction"})
            assert resp_b.status_code == 201
            plan_b_id = resp_b.json()["plan_id"]

            assert plan_a_id != plan_b_id

            # GET returns only plan B
            resp = await client.get("/api/study_plan")
            assert resp.status_code == 200
            body = resp.json()
            assert body["plan"]["id"] == plan_b_id
            assert body["plan"]["goal"] == "Subtraction"
    asyncio.run(do())


def test_post_validates_body(real_state):
    """Invalid body → 422-style CognitsError."""
    _, app = real_state

    async def do():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
            # Empty goal
            resp = await client.post("/api/study_plan", json={"goal": ""})
            assert resp.status_code == 400
            assert "required" in resp.json()["message"].lower()

            # Missing goal
            resp = await client.post("/api/study_plan", json={})
            assert resp.status_code == 400

            # max_items = 0
            resp = await client.post("/api/study_plan", json={
                "goal": "test", "max_items": 0,
            })
            assert resp.status_code == 400

            # max_items = 999 (> STUDY_PLAN_MAX_ITEMS)
            resp = await client.post("/api/study_plan", json={
                "goal": "test", "max_items": 999,
            })
            assert resp.status_code == 400

            # priorities not a list
            resp = await client.post("/api/study_plan", json={
                "goal": "test", "priorities": "not_a_list",
            })
            assert resp.status_code == 400
    asyncio.run(do())
