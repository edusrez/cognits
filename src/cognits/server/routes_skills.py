"""Skill tree and learner model read-only REST endpoints.

Follows the routes_notes.py / routes_reports.py pattern: every ReportStore
call goes through asyncio.to_thread so the event loop stays free.
"""

from __future__ import annotations

import asyncio

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from cognits.server.util import text_error


def register(app: FastAPI, st) -> None:
    def _ensure_db():
        if st.db is None:
            return text_error("storage not available", 503)
        return None

    @app.get("/api/skills")
    async def list_skills(request: Request):
        if (err := _ensure_db()) is not None:
            return err

        domain = request.query_params.get("domain") or None
        try:
            skills = await asyncio.to_thread(st.skills.list_active, domain)
        except Exception as e:
            return text_error(str(e), 500)

        return JSONResponse({"skills": [s.to_json() for s in skills]})

    @app.get("/api/skills/tree")
    async def get_skill_tree():
        if (err := _ensure_db()) is not None:
            return err

        try:
            tree = await asyncio.to_thread(st.skills.get_tree)
            tv = await asyncio.to_thread(st.skills.get_tree_version)
        except Exception as e:
            return text_error(str(e), 500)

        tree["treeVersion"] = tv
        return JSONResponse(tree)

    @app.get("/api/skills/{skill_id}/state")
    async def get_learner_state(skill_id: str):
        if (err := _ensure_db()) is not None:
            return err

        try:
            state = await asyncio.to_thread(
                st.learner_state.get, skill_id
            )
        except Exception as e:
            return text_error(str(e), 500)

        if state is None:
            return text_error("skill state not found", 404)

        return JSONResponse(state.to_json())