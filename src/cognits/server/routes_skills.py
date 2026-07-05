"""Skill tree and learner model read-only REST endpoints.

Follows the routes_notes.py / routes_reports.py pattern: every ReportStore
call goes through asyncio.to_thread so the event loop stays free.
"""

from __future__ import annotations

import asyncio

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from cognits.server.exceptions import NotFoundError, StorageError


def register(app: FastAPI, st) -> None:
    def _ensure_db():
        if st.db is None:
            raise StorageError("storage not available")

    @app.get("/api/skills")
    async def list_skills(request: Request):
        _ensure_db()

        domain = request.query_params.get("domain") or None
        try:
            skills = await asyncio.to_thread(st.skills.list_active, domain)
        except Exception as e:
            raise StorageError(str(e))

        return JSONResponse({"skills": [s.to_json() for s in skills]})

    @app.get("/api/skills/tree")
    async def get_skill_tree():
        _ensure_db()

        try:
            tree = await asyncio.to_thread(st.skills.get_tree)
            tv = await asyncio.to_thread(st.skills.get_tree_version)
        except Exception as e:
            raise StorageError(str(e))

        tree["treeVersion"] = tv
        return JSONResponse(tree)

    @app.get("/api/skills/{skill_id}/state")
    async def get_learner_state(skill_id: str):
        _ensure_db()

        try:
            state = await asyncio.to_thread(
                st.learner_state.get, skill_id
            )
        except Exception as e:
            raise StorageError(str(e))

        if state is None:
            raise NotFoundError("skill state not found")

        return JSONResponse(state.to_json())