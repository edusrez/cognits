"""Study plan REST endpoints — generate and retrieve study plans.

Directly calls ``learner.planner.generate_plan`` (no subagent needed
because the study_planner agent is a thin deterministic wrapper per
``study_planner.md:31-34``).
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

from cognits.constants import STUDY_PLAN_MAX_ITEMS
from cognits.learner import planner
from cognits.server.exceptions import CognitsError, StorageError
from cognits.storage.models import LearnerState, Skill, SkillPrereq


def register(app: FastAPI, st) -> None:
    def ensure_db():
        if st.db is None:
            raise CognitsError("storage not available", "ERROR", 503)

    @app.get("/api/study_plan")
    async def get_study_plan():
        """Retrieve the active study plan (if any)."""
        ensure_db()
        try:
            plan = await asyncio.to_thread(st.study_plans.get_active)
        except Exception as e:
            raise StorageError(str(e))
        if plan is None:
            return JSONResponse({"plan": None, "items": []})
        try:
            items = await asyncio.to_thread(st.study_plans.get_items, plan.id)
        except Exception as e:
            raise StorageError(str(e))
        return JSONResponse({
            "plan": plan.to_json(),
            "items": [i.to_json() for i in items],
        })

    @app.post("/api/study_plan")
    async def create_study_plan(request: Request):
        """Generate a new study plan (supersedes the old active plan)."""
        ensure_db()

        # --- Parse & validate body -------------------------------------------
        try:
            body = await request.json()
            goal = body.get("goal", "") if isinstance(body, dict) else ""
        except (json.JSONDecodeError, ValueError, UnicodeDecodeError):
            raise CognitsError("invalid body", "ERROR", 400)
        if not isinstance(goal, str) or not goal.strip():
            raise CognitsError("goal is required", "ERROR", 400)
        goal = goal.strip()

        priorities_raw = body.get("priorities")
        if priorities_raw is not None:
            if not isinstance(priorities_raw, list) or not all(
                isinstance(p, str) for p in priorities_raw
            ):
                raise CognitsError("priorities must be a list of strings", "ERROR", 400)
            priorities = [p.strip() for p in priorities_raw if p.strip()]
        else:
            priorities = None

        max_items = body.get("max_items", planner.MAX_PLAN_ITEMS)
        if not isinstance(max_items, int) or max_items < 1 or max_items > STUDY_PLAN_MAX_ITEMS:
            raise CognitsError(
                f"max_items must be an integer between 1 and {STUDY_PLAN_MAX_ITEMS}",
                "ERROR", 400,
            )

        # --- Load data & generate plan ---------------------------------------
        try:
            tree = await asyncio.to_thread(st.skills.get_tree)
            skills_raw = tree.get("skills", [])
            edges_raw = tree.get("edges", [])
            tree_version = tree.get("treeVersion", 1)

            if not skills_raw:
                raise CognitsError(
                    "no skill tree — run onboarding first",
                    "NO_SKILL_TREE", 409,
                )

            # Convert raw dicts to dataclasses (mirrors tool_study_plan.py).
            skill_map: dict[str, Skill] = {}
            for d in skills_raw:
                s = Skill(
                    id=d["id"],
                    domain=d.get("domain", ""),
                    name=d.get("name", ""),
                    description=d.get("description", ""),
                    bloom_level=d.get("bloomLevel", ""),
                    difficulty=float(d.get("difficulty", 0.5)),
                )
                skill_map[s.id] = s
            skills = list(skill_map.values())

            edges = [
                SkillPrereq(
                    skill_id=e["skillId"],
                    prereq_id=e["prereqId"],
                    edge_type=e.get("edgeType", "prereq"),
                )
                for e in edges_raw
            ]

            # Load learner states, defaulting missing skills to not_seen.
            all_states = await asyncio.to_thread(st.learner_state.get_all)
            states: dict[str, LearnerState] = {}
            for sid_key in skill_map:
                if sid_key in all_states:
                    states[sid_key] = all_states[sid_key]
                else:
                    states[sid_key] = LearnerState(skill_id=sid_key)

            # Generate plan (synchronous — all data is in memory).
            now_iso = datetime.now(timezone.utc).isoformat()
            items = planner.generate_plan(
                skills=skills, edges=edges, states=states,
                goal=goal, priorities=priorities, max_items=max_items,
                now_iso=now_iso,
            )

            # Supersede old active plan.
            old_plan = await asyncio.to_thread(st.study_plans.get_active)
            if old_plan is not None:
                await asyncio.to_thread(st.study_plans.supersede, old_plan.id)

            # Persist new plan + items.
            plan_id = await asyncio.to_thread(
                st.study_plans.create, tree_version, goal
            )
            await asyncio.to_thread(st.study_plans.replace_items, plan_id, items)

            # Reload to get server-assigned timestamps and item IDs.
            items_reloaded = await asyncio.to_thread(
                st.study_plans.get_items, plan_id
            )

            frontier_size = len(planner.compute_frontier(skills, edges, states))

        except CognitsError:
            raise
        except Exception as e:
            raise StorageError(str(e))

        return JSONResponse(
            {
                "plan_id": plan_id,
                "goal": goal,
                "items": [i.to_json() for i in items_reloaded],
                "frontier_size": frontier_size,
            },
            status_code=201,
        )
