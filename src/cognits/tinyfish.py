"""Port of internal/tinyfish/client.go: web search and fetch."""

from __future__ import annotations

import httpx

SEARCH_URL = "https://api.search.tinyfish.ai"
FETCH_URL = "https://api.fetch.tinyfish.ai"


class TinyfishError(Exception):
    pass


class TinyfishClient:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self._client = httpx.AsyncClient(timeout=150.0, limits=httpx.Limits(max_connections=10, max_keepalive_connections=4))

    async def aclose(self) -> None:
        await self._client.aclose()

    async def search(self, query: str) -> dict:
        try:
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
