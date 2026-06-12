"""Port de internal/server/sessions.go."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

from cognits.server.util import text_error
from cognits.storage.files import Session

log = logging.getLogger("cognits.sessions")


def register(app: FastAPI, st) -> None:
    def ensure_sessions():
        if st.store is None:
            return text_error("almacenamiento no disponible", 503)
        return None

    @app.post("/api/sessions")
    async def create_session():
        if (err := ensure_sessions()) is not None:
            return err

        now = datetime.now().astimezone()
        sid = now.strftime("%Y-%m-%dT%H-%M")
        session = Session(id=sid, name=sid, created_at=now.isoformat(timespec="seconds"))

        try:
            await asyncio.to_thread(st.store.save_session, session)
        except OSError as e:
            return text_error(f"storage: write session: {e}", 500)

        return JSONResponse(session.to_json())

    @app.get("/api/sessions")
    async def list_sessions():
        if (err := ensure_sessions()) is not None:
            return err
        try:
            sessions = await asyncio.to_thread(st.store.list_sessions)
        except OSError as e:
            return text_error(str(e), 500)
        return JSONResponse([s.to_json() for s in sessions])

    @app.put("/api/sessions/{session_id}")
    async def rename_session(session_id: str, request: Request):
        if (err := ensure_sessions()) is not None:
            return err

        try:
            body = await request.json()
            name = body.get("name", "") if isinstance(body, dict) else ""
            if not isinstance(name, str):
                raise ValueError("name")
        except (json.JSONDecodeError, ValueError, UnicodeDecodeError):
            return text_error("invalid body", 400)
        if len(name) > 120:
            return text_error("name too long", 400)

        try:
            await asyncio.to_thread(st.store.rename_session, session_id, name)
        except (OSError, json.JSONDecodeError) as e:
            return text_error(str(e), 500)

        return Response(status_code=204)

    @app.delete("/api/sessions/{session_id}")
    async def delete_session(session_id: str):
        if (err := ensure_sessions()) is not None:
            return err

        try:
            await asyncio.to_thread(st.store.delete_session, session_id)
        except OSError as e:
            return text_error(str(e), 500)

        # Los informes se conservan: son biblioteca transversal en la vista Learn It.
        if st.report_store is not None:
            try:
                await asyncio.to_thread(st.report_store.delete_messages_by_session, session_id)
            except Exception as e:
                log.error("sessions: delete messages (session %s): %s", session_id, e)
            try:
                await asyncio.to_thread(st.report_store.delete_session_config, session_id)
            except Exception as e:
                log.error("sessions: delete session config (session %s): %s", session_id, e)

        return Response(status_code=204)
