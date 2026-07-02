"""Notebook CRUD routes — notes (sheets) that live in SQLite."""

from __future__ import annotations

import asyncio
import json

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

from cognits.server.util import text_error


def register(app: FastAPI, st) -> None:
    def ensure_db():
        if st.db is None:
            return text_error("storage not available", 503)
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
            return text_error("invalid body", 400)
        if not title:
            return text_error("title is required", 400)
        if len(title) > 120:
            return text_error("title too long", 400)

        try:
            note = await asyncio.to_thread(st.notes.create, title)
        except Exception as e:
            return text_error(f"storage: create note: {e}", 500)

        return JSONResponse(note.to_json())

    @app.get("/api/notes")
    async def list_notes():
        if (err := ensure_db()) is not None:
            return err
        try:
            notes = await asyncio.to_thread(st.notes.list_all)
        except Exception as e:
            return text_error(str(e), 500)
        return JSONResponse([n.to_json() for n in notes])

    @app.get("/api/notes/{note_id}")
    async def get_note(note_id: str):
        if (err := ensure_db()) is not None:
            return err
        try:
            note = await asyncio.to_thread(st.notes.get, note_id)
        except Exception as e:
            return text_error(str(e), 500)
        if note is None:
            return text_error("note not found", 404)
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
            return text_error("invalid body", 400)

        name = body.get("name", None)
        content = body.get("content", None)

        if name is not None:
            if not isinstance(name, str):
                return text_error("invalid name", 400)
            name = name.strip()
            if not name:
                return text_error("name is required", 400)
            if len(name) > 120:
                return text_error("name too long", 400)

        if content is not None:
            if not isinstance(content, str):
                return text_error("invalid content", 400)

        try:
            if name is not None:
                await asyncio.to_thread(st.notes.rename, note_id, name)
            if content is not None:
                await asyncio.to_thread(st.notes.save_content, note_id, content)
        except Exception as e:
            return text_error(str(e), 500)

        return Response(status_code=204)

    @app.delete("/api/notes/{note_id}")
    async def delete_note(note_id: str):
        if (err := ensure_db()) is not None:
            return err

        try:
            await asyncio.to_thread(st.notes.delete, note_id)
        except Exception as e:
            return text_error(str(e), 500)

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
            return text_error("invalid body", 400)

        try:
            await asyncio.to_thread(st.notes.reorder, order)
        except Exception as e:
            return text_error(str(e), 500)

        return Response(status_code=204)
