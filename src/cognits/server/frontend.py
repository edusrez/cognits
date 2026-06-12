"""Port of internal/server/frontend.go: serves the packaged SPA.

Only the index is served uncached; assets carry a hash/cache-buster in
their name and can be cached normally.
"""

from __future__ import annotations

import logging
import re
import time
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, PlainTextResponse, Response

log = logging.getLogger("cognits.frontend")

ASSET_REF = re.compile(rb'="(/assets/[^"?]+)"')

_ALPHABET = "0123456789abcdefghijklmnopqrstuvwxyz"


def _base36(n: int) -> str:
    if n == 0:
        return "0"
    out = []
    while n:
        n, rem = divmod(n, 36)
        out.append(_ALPHABET[rem])
    return "".join(reversed(out))


def frontend_dir() -> Path:
    return Path(__file__).resolve().parent.parent / "frontend_dist"


def load_index_html() -> bytes | None:
    try:
        data = (frontend_dir() / "index.html").read_bytes()
    except OSError as e:
        log.warning("frontend: failed to read index.html: %s", e)
        return None
    v = _base36(time.time_ns()).encode("ascii")
    return ASSET_REF.sub(rb'="\1?v=' + v + rb'"', data)


def register_prod_frontend(app: FastAPI) -> None:
    root = frontend_dir()
    html = load_index_html()

    @app.get("/{path:path}", include_in_schema=False)
    async def serve_frontend(path: str) -> Response:
        if path in ("", "index.html") and html is not None:
            return Response(
                content=html,
                media_type="text/html; charset=utf-8",
                headers={"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"},
            )
        target = (root / path).resolve()
        # Never serve outside the packaged directory.
        if not target.is_relative_to(root) or not target.is_file():
            return PlainTextResponse("404 page not found\n", status_code=404)
        return FileResponse(target)
