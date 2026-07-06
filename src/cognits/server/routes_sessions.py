"""Port of internal/server/sessions.go."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

from cognits.constants import MAX_NAME_LENGTH
from cognits.server.exceptions import NotFoundError, StorageError, SessionNotFound
from cognits.storage.files import Session

log = logging.getLogger("cognits.sessions")


def register(app: FastAPI, st) -> None:
    def ensure_sessions():
        if st.store is None:
            raise StorageError("storage not available")
        return None

    @app.post("/api/sessions")
    async def create_session():
        if (err := ensure_sessions()) is not None:
            return err

        now = datetime.now().astimezone()
        sid = now.strftime("%Y-%m-%dT%H-%M-%S")
        session = Session(id=sid, name=sid, created_at=now.isoformat(timespec="seconds"))

        try:
            await asyncio.to_thread(st.store.save_session, session)
        except OSError as e:
            raise StorageError(f"write session: {e}")

        return JSONResponse(session.to_json())

    @app.get("/api/sessions")
    async def list_sessions(include_hidden: bool = False):
        if (err := ensure_sessions()) is not None:
            return err
        try:
            sessions = await asyncio.to_thread(st.store.list_sessions, include_hidden)
        except OSError as e:
            raise StorageError(str(e))
        return JSONResponse([s.to_json() for s in sessions])

    @app.put("/api/sessions/{session_id}")
    async def rename_session(session_id: str, request: Request):
        if (err := ensure_sessions()) is not None:
            return err

        try:
            body = await request.json()
            if not isinstance(body, dict):
                raise ValueError("body")
        except (json.JSONDecodeError, ValueError, UnicodeDecodeError):
            raise StorageError("invalid body")

        name = body.get("name")
        hidden = body.get("hidden")
        if name is None and hidden is None:
            raise StorageError("name or hidden is required")

        if name is not None:
            if not isinstance(name, str):
                raise StorageError("invalid name")
            if len(name) > MAX_NAME_LENGTH:
                raise StorageError("name too long")

        if hidden is not None and not isinstance(hidden, bool):
            raise StorageError("hidden must be a boolean")

        try:
            if name is not None:
                await asyncio.to_thread(st.store.rename_session, session_id, name)
            if hidden is not None:
                if hidden:
                    await asyncio.to_thread(st.store.hide_session, session_id)
                else:
                    await asyncio.to_thread(st.store.unhide_session, session_id)
        except FileNotFoundError:
            raise SessionNotFound(session_id)
        except (OSError, json.JSONDecodeError) as e:
            raise StorageError(str(e))

        return Response(status_code=204)

    @app.delete("/api/sessions/{session_id}")
    async def delete_session(session_id: str):
        if (err := ensure_sessions()) is not None:
            return err

        try:
            await asyncio.to_thread(st.store.delete_session, session_id)
        except OSError as e:
            raise StorageError(str(e))

        if st.db is not None:
            try:
                await asyncio.to_thread(st.messages.delete_by_session, session_id)
            except Exception as e:
                log.error("sessions: delete messages (session %s): %s", session_id, e)
            try:
                await asyncio.to_thread(st.session_config.delete, session_id)
            except Exception as e:
                log.error("sessions: delete session config (session %s): %s", session_id, e)

        return Response(status_code=204)

    @app.put("/api/sessions/reorder")
    async def reorder_sessions(request: Request):
        if (err := ensure_sessions()) is not None:
            return err

        try:
            body = await request.json()
            order = body.get("order", []) if isinstance(body, dict) else []
            if not isinstance(order, list) or not all(isinstance(x, str) for x in order):
                raise ValueError("order")
        except (json.JSONDecodeError, ValueError, UnicodeDecodeError):
            raise StorageError("invalid body")

        try:
            await asyncio.to_thread(st.store.reorder_sessions, order)
        except OSError as e:
            raise StorageError(str(e))

        return Response(status_code=204)
