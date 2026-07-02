"""Port of internal/server/{api,agents,messages,session_config,desktops}.go."""

from __future__ import annotations

import asyncio
import json
import os

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

from cognits import paths
from cognits.agent.prompts import DEFAULT_AGENTS
from cognits.constants import DEFAULT_MODEL, TREE_MAX_DEPTH, TREE_MAX_ENTRIES
from cognits.server.util import text_error
from cognits.storage.models import SessionConfigRow
from cognits.storage.files import write_file_atomic
TREE_SKIP_DIRS = {"node_modules", "dist", "vendor"}


def build_tree(dir_path: str, max_depth: int, budget: list[int]) -> dict:
    node: dict = {"name": os.path.basename(dir_path), "path": dir_path, "isDir": True}
    if max_depth <= 0 or budget[0] <= 0:
        return node

    try:
        entries = list(os.scandir(dir_path))
    except OSError:
        return node

    entries.sort(key=lambda e: (not e.is_dir(follow_symlinks=False), e.name.lower()))

    children = []
    for e in entries:
        if budget[0] <= 0:
            break
        name = e.name
        if not name or name.startswith(".") or name in TREE_SKIP_DIRS:
            continue
        if e.is_symlink():
            continue
        budget[0] -= 1
        child: dict = {
            "name": name,
            "path": os.path.join(dir_path, name),
            "isDir": e.is_dir(follow_symlinks=False),
        }
        if child["isDir"]:
            sub = build_tree(child["path"], max_depth - 1, budget).get("children")
            if sub:
                child["children"] = sub
        children.append(child)
    if children:
        node["children"] = children
    return node


def register(app: FastAPI, st) -> None:
    @app.get("/api/health")
    async def health():
        rag_ready = False
        rag_error = None
        if st.rag is not None:
            rag_ready = st.rag.ready.is_set()
            rag_error = st.rag.error
        docling_ready = False
        docling_error = None
        if st.docling_engine is not None:
            docling_ready = st.docling_engine.ready.is_set()
            docling_error = st.docling_engine.error
        return JSONResponse({
            "status": "ok",
            "rag_ready": rag_ready,
            "rag_error": rag_error,
            "docling_ready": docling_ready,
            "docling_error": docling_error,
        })

    @app.get("/api/tree")
    async def tree():
        cwd = os.getcwd()
        budget = [TREE_MAX_ENTRIES]
        return JSONResponse(await asyncio.to_thread(build_tree, cwd, TREE_MAX_DEPTH, budget))

    @app.get("/api/agents")
    async def get_agents():
        return JSONResponse(DEFAULT_AGENTS)

    @app.get("/api/sessions/{session_id}/messages")
    async def get_messages(session_id: str):
        if st.db is None:
            return text_error("db not available", 500)
        try:
            msgs = await asyncio.to_thread(st.messages.load, session_id)
        except Exception as e:
            return text_error(str(e), 500)
        return JSONResponse([m.to_json() for m in msgs])

    @app.get("/api/sessions/{session_id}/config")
    async def get_session_config(session_id: str):
        if st.db is None:
            return text_error("db not available", 500)
        try:
            cfg = await asyncio.to_thread(st.session_config.load, session_id)
        except Exception as e:
            return text_error(str(e), 500)
        if cfg is None:
            cfg = SessionConfigRow(
                session_id=session_id,
                provider="deepseek",
                model=DEFAULT_MODEL,
                reasoning="max",
                agent_id="orchestrator",
            )
        return JSONResponse(cfg.to_json())

    @app.put("/api/sessions/{session_id}/config")
    async def put_session_config(session_id: str, request: Request):
        if st.db is None:
            return text_error("db not available", 500)
        try:
            body = await request.json()
            if not isinstance(body, dict):
                raise ValueError("body")
            cfg = SessionConfigRow.from_json(body)
        except (json.JSONDecodeError, ValueError, TypeError, UnicodeDecodeError):
            return text_error("invalid body", 400)
        cfg.session_id = session_id

        try:
            await asyncio.to_thread(st.session_config.save, cfg)
        except Exception as e:
            return text_error(str(e), 500)
        return Response(status_code=204)

    def desktop_path():
        return paths.data_dir() / "desktops.json"

    @app.get("/api/desktops")
    async def get_desktops():
        async with st.desktop_lock:
            try:
                data = await asyncio.to_thread(desktop_path().read_bytes)
            except OSError:
                return JSONResponse({"desktops": [], "activeIndex": 0})
        return Response(content=data, media_type="application/json")

    @app.put("/api/desktops")
    async def put_desktops(request: Request):
        try:
            body = await request.json()
            if not isinstance(body, dict):
                raise ValueError("body")
            desktops = body.get("desktops") or []
            active_index = body.get("activeIndex") or 0
            if not isinstance(desktops, list) or not isinstance(active_index, int):
                raise ValueError("shape")
        except (json.JSONDecodeError, ValueError, TypeError, UnicodeDecodeError):
            return text_error("invalid body", 400)

        data = json.dumps(
            {"desktops": desktops, "activeIndex": active_index},
            indent=2,
            ensure_ascii=False,
        ).encode("utf-8")

        path = desktop_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        # Two tabs can persist at the same time (BroadcastChannel): serialize
        # and write atomically so the JSON is never left truncated.
        async with st.desktop_lock:
            try:
                await asyncio.to_thread(write_file_atomic, path, data)
            except OSError as e:
                return text_error(str(e), 500)

        return Response(status_code=204)
