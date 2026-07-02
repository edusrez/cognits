"""Port of registerDevProxy (frontend.go) extended with WebSocket.

In ENV=dev the catch-all proxies to Vite (HMR included); the /api/* routes
are registered first and win. Replaces rebuild.go's auto-rebuild: with
`uvicorn --reload` + Vite dev nothing needs recompiling.
"""

from __future__ import annotations

import asyncio
import logging

import httpx
from fastapi import FastAPI, Request, WebSocket
from fastapi.responses import Response

log = logging.getLogger("cognits.devproxy")

from cognits.constants import VITE_PORT

VITE_PORT = VITE_PORT  # re-export for dev proxy

# Hop-by-hop headers: not forwarded (h11 manages them per connection).
_SKIP_HEADERS = {
    "connection",
    "keep-alive",
    "transfer-encoding",
    "upgrade",
    "content-length",
    "content-encoding",
    "host",
}


def register_dev_proxy(app: FastAPI) -> None:
    client = httpx.AsyncClient(
        base_url=f"http://localhost:{VITE_PORT}", timeout=30.0
    )
    log.info("[frontend] dev mode: proxying to Vite at http://localhost:%d", VITE_PORT)

    @app.websocket("/{path:path}")
    async def ws_proxy(websocket: WebSocket, path: str) -> None:
        import websockets

        uri = f"ws://localhost:{VITE_PORT}/{path}"
        if websocket.url.query:
            uri += f"?{websocket.url.query}"
        requested = websocket.headers.get("sec-websocket-protocol")
        subprotocols = (
            [p.strip() for p in requested.split(",")] if requested else None
        )

        try:
            async with websockets.connect(uri, subprotocols=subprotocols) as upstream:
                await websocket.accept(
                    subprotocol=str(upstream.subprotocol) if upstream.subprotocol else None
                )

                async def client_to_upstream() -> None:
                    while True:
                        msg = await websocket.receive()
                        if msg["type"] == "websocket.disconnect":
                            return
                        if msg.get("text") is not None:
                            await upstream.send(msg["text"])
                        elif msg.get("bytes") is not None:
                            await upstream.send(msg["bytes"])

                async def upstream_to_client() -> None:
                    async for msg in upstream:
                        if isinstance(msg, str):
                            await websocket.send_text(msg)
                        else:
                            await websocket.send_bytes(msg)

                tasks = [
                    asyncio.create_task(client_to_upstream()),
                    asyncio.create_task(upstream_to_client()),
                ]
                _, pending = await asyncio.wait(
                    tasks, return_when=asyncio.FIRST_COMPLETED
                )
                for t in pending:
                    t.cancel()
        except (OSError, websockets.WebSocketException) as e:
            log.debug("devproxy ws: %s", e)

    @app.api_route("/{path:path}", methods=["GET", "HEAD"], include_in_schema=False)
    async def http_proxy(request: Request, path: str) -> Response:
        url = f"/{path}"
        if request.url.query:
            url += f"?{request.url.query}"
        headers = {
            k: v for k, v in request.headers.items() if k.lower() not in _SKIP_HEADERS
        }
        try:
            upstream = await client.request(request.method, url, headers=headers)
        except httpx.HTTPError as e:
            return Response(content=f"vite dev server: {e}\n", status_code=502)
        resp_headers = {
            k: v for k, v in upstream.headers.items() if k.lower() not in _SKIP_HEADERS
        }
        return Response(
            content=upstream.content,
            status_code=upstream.status_code,
            headers=resp_headers,
        )
