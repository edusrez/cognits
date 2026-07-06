"""Port of internal/tinyfish/client.go: web search and fetch."""

from __future__ import annotations

import asyncio

import httpx

from cognits.constants import (
    HTTPX_MAX_CONNECTIONS,
    HTTPX_MAX_KEEPALIVE,
    TINYFISH_CONCURRENCY,
    TINYFISH_FETCH_URL,
    TINYFISH_SEARCH_URL,
    TINYFISH_TIMEOUT,
)

_tinyfish_sem = asyncio.Semaphore(TINYFISH_CONCURRENCY)

SEARCH_URL = TINYFISH_SEARCH_URL
FETCH_URL = TINYFISH_FETCH_URL


class TinyfishError(Exception):
    pass


class TinyfishClient:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self._client = httpx.AsyncClient(timeout=TINYFISH_TIMEOUT, limits=httpx.Limits(max_connections=HTTPX_MAX_CONNECTIONS, max_keepalive_connections=HTTPX_MAX_KEEPALIVE))

    async def aclose(self) -> None:
        await self._client.aclose()

    async def search(self, query: str) -> dict:
        try:
            async with _tinyfish_sem:
                resp = await self._client.get(
                    SEARCH_URL,
                    params={"query": query},
                    headers={"X-API-Key": self.api_key},
                )
        except httpx.HTTPError as e:
            raise TinyfishError(f"tinyfish search: {e}") from e
        if resp.status_code != 200:
            raise TinyfishError(f"tinyfish search: HTTP {resp.status_code}")
        try:
            return resp.json()
        except ValueError as e:
            raise TinyfishError(f"tinyfish search: decode: {e}") from e

    async def fetch_content(self, urls: list[str]) -> dict:
        try:
            async with _tinyfish_sem:
                resp = await self._client.post(
                    FETCH_URL,
                    json={"urls": urls, "format": "markdown"},
                    headers={"X-API-Key": self.api_key},
                )
        except httpx.HTTPError as e:
            raise TinyfishError(f"tinyfish fetch: {e}") from e
        if resp.status_code != 200:
            raise TinyfishError(f"tinyfish fetch: HTTP {resp.status_code}")
        try:
            return resp.json()
        except ValueError as e:
            raise TinyfishError(f"tinyfish fetch: decode: {e}") from e
