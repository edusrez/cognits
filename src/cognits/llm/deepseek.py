"""Port of internal/llm/deepseek.go: DeepSeek streaming client.

The Go inactivity watchdog (120s) comes free with httpx's read timeout,
which applies to each socket read operation, not the whole stream: if the
API goes silent without FIN (NAT, wifi drop), ReadTimeout fires.
"""

from __future__ import annotations

import json
from collections.abc import Callable

import httpx

from cognits.llm.types import Message

# If the API stops sending data for this duration, the stream is considered dead.
STREAM_IDLE_TIMEOUT = 120.0

BASE_URL = "https://api.deepseek.com/chat/completions"


class DeepSeekError(Exception):
    pass


class DeepSeekClient:
    def __init__(self, api_key: str):
        self.api_key = api_key
        # Phase timeouts, never a global one: a total timeout would cut
        # legitimate multi-minute streams short.
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(
                connect=10.0, read=STREAM_IDLE_TIMEOUT, write=30.0, pool=10.0
            )
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def chat_completion_stream(
        self,
        messages: list[Message],
        tools: list[dict],
        model: str,
        reasoning: str,
        on_chunk: Callable[[dict], None],
        max_tokens: int | None = None,
        temperature: float | None = None,
        top_p: float | None = None,
    ) -> None:
        # The thinking API is binary: "high"/"max" → enabled. With tools, omit
        # the parameter (the API rejects that combination).
        body: dict = {
            "model": model,
            "messages": [m.to_payload() for m in messages],
            "stream": True,
        }
        if tools:
            body["tools"] = tools
        else:
            body["thinking"] = {
                "type": "disabled" if reasoning == "disabled" else "enabled"
            }
        if max_tokens is not None and max_tokens > 0:
            body["max_tokens"] = max_tokens
        if temperature is not None:
            body["temperature"] = temperature
        if top_p is not None:
            body["top_p"] = top_p

        try:
            async with self._client.stream(
                "POST",
                BASE_URL,
                json=body,
                headers={"Authorization": f"Bearer {self.api_key}"},
            ) as resp:
                if resp.status_code != 200:
                    # Limit the read (a huge body would bloat logs/chat) and
                    # extract the error message from the API JSON if present.
                    raw = (await resp.aread())[: 8 << 10]
                    msg = raw.decode("utf-8", errors="replace").strip()
                    try:
                        api_msg = json.loads(raw).get("error", {}).get("message", "")
                        if api_msg:
                            msg = api_msg
                    except (json.JSONDecodeError, AttributeError):
                        pass
                    raise DeepSeekError(f"deepseek: HTTP {resp.status_code}: {msg}")

                async for line in resp.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    data = line[len("data: "):]
                    if data == "[DONE]":
                        return
                    try:
                        chunk = json.loads(data)
                    except json.JSONDecodeError:
                        continue
                    on_chunk(chunk)
        except httpx.ReadTimeout as e:
            raise DeepSeekError(
                f"deepseek: stream idle for {int(STREAM_IDLE_TIMEOUT)}s"
            ) from e
        except httpx.HTTPError as e:
            raise DeepSeekError(f"deepseek: request: {e}") from e
