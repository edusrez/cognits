"""Notebook CRUD routes — notes (sheets) that live in SQLite."""

from __future__ import annotations

import asyncio
import json

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

from cognits.constants import MAX_NAME_LENGTH
from cognits.server.exceptions import CognitsError, NotFoundError, StorageError



def register(app: FastAPI, st) -> None:
    def ensure_db():
        if st.db is None:
            raise CognitsError("storage not available", "ERROR", 503)
        return None

    @app.post("/api/notes")
    async def create_note(request: Request):
        if (err := ensure_db()) is not None:
            return err

        try:
            body = await request.json()
            title = body.get("title", "") if isinstance(body, dict) else ""
            if not isinstance(title, str):
                raise ValueError("title")
            title = title.strip()
        except (json.JSONDecodeError, ValueError, UnicodeDecodeError):
            raise CognitsError("invalid body", "ERROR", 400)
        if not title:
            raise CognitsError("title is required", "ERROR", 400)
        if len(title) > MAX_NAME_LENGTH:
            raise CognitsError("title too long", "ERROR", 400)

        try:
            note = await asyncio.to_thread(st.notes.create, title)
        except Exception as e:
            raise StorageError(f"create note: {e}")

        return JSONResponse(note.to_json())

    @app.get("/api/notes")
    async def list_notes():
        if (err := ensure_db()) is not None:
            return err
        try:
            notes = await asyncio.to_thread(st.notes.list_all)
        except Exception as e:
            raise StorageError(str(e))
        return JSONResponse([n.to_json() for n in notes])

    @app.get("/api/notes/{note_id}")
    async def get_note(note_id: str):
        if (err := ensure_db()) is not None:
            return err
        try:
            note = await asyncio.to_thread(st.notes.get, note_id)
        except Exception as e:
            raise StorageError(str(e))
        if note is None:
            raise NotFoundError("note not found")
        return JSONResponse(note.to_json())

    @app.put("/api/notes/{note_id}")
    async def update_note(note_id: str, request: Request):
        if (err := ensure_db()) is not None:
            return err

        try:
            body = await request.json()
            if not isinstance(body, dict):
                raise ValueError("body")
        except (json.JSONDecodeError, ValueError, UnicodeDecodeError):
            raise CognitsError("invalid body", "ERROR", 400)

        name = body.get("name", None)
        content = body.get("content", None)

        if name is not None:
            if not isinstance(name, str):
                raise CognitsError("invalid name", "ERROR", 400)
            name = name.strip()
            if not name:
                raise CognitsError("name is required", "ERROR", 400)
            if len(name) > MAX_NAME_LENGTH:
                raise CognitsError("name too long", "ERROR", 400)

        if content is not None:
            if not isinstance(content, str):
                raise CognitsError("invalid content", "ERROR", 400)

        try:
            if name is not None:
                await asyncio.to_thread(st.notes.rename, note_id, name)
            if content is not None:
                await asyncio.to_thread(st.notes.save_content, note_id, content)
        except Exception as e:
            raise StorageError(str(e))

        return Response(status_code=204)

    @app.delete("/api/notes/{note_id}")
    async def delete_note(note_id: str):
        if (err := ensure_db()) is not None:
            return err

        try:
            await asyncio.to_thread(st.notes.delete, note_id)
        except Exception as e:
            raise StorageError(str(e))

        return Response(status_code=204)

    @app.put("/api/notes/reorder")
    async def reorder_notes(request: Request):
        if (err := ensure_db()) is not None:
            return err

        try:
            body = await request.json()
            order = body.get("order", []) if isinstance(body, dict) else []
            if not isinstance(order, list) or not all(isinstance(x, str) for x in order):
                raise ValueError("order")
        except (json.JSONDecodeError, ValueError, UnicodeDecodeError):
            raise CognitsError("invalid body", "ERROR", 400)

        try:
            await asyncio.to_thread(st.notes.reorder, order)
        except Exception as e:
            raise StorageError(str(e))

        return Response(status_code=204)
