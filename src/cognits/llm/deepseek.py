"""Port of internal/llm/deepseek.go: DeepSeek streaming client.

The Go inactivity watchdog (120s) comes free with httpx's read timeout,
which applies to each socket read operation, not the whole stream: if the
API goes silent without FIN (NAT, wifi drop), ReadTimeout fires.
"""

from __future__ import annotations

import json
from collections.abc import Callable

import httpx

from cognits.constants import (
    HTTPX_MAX_CONNECTIONS,
    HTTPX_MAX_KEEPALIVE,
    LLM_BASE_URL,
    LLM_CONNECT_TIMEOUT,
    LLM_ERROR_BODY_MAX_BYTES,
    LLM_POOL_TIMEOUT,
    LLM_READ_TIMEOUT,
    LLM_WRITE_TIMEOUT,
)
from cognits.llm.types import Message



class DeepSeekError(Exception):
    def __init__(self, message: str, retryable: bool = False):
        super().__init__(message)
        self.retryable = retryable


class DeepSeekClient:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(
                connect=LLM_CONNECT_TIMEOUT, read=LLM_READ_TIMEOUT,
                write=LLM_WRITE_TIMEOUT, pool=LLM_POOL_TIMEOUT,
            ),
            limits=httpx.Limits(
                max_connections=HTTPX_MAX_CONNECTIONS,
                max_keepalive_connections=HTTPX_MAX_KEEPALIVE,
            ),
        )
        self._retries = 0
        self._backoff = 1.0  # seconds, doubles per retry

    async def aclose(self) -> None:
        await self._client.aclose()

    async def chat_completion_stream(
        self,
        messages: list[Message],
        tools: list[dict] | None,
        model: str,
        reasoning: str,
        on_chunk: Callable[[dict], None],
        max_tokens: int | None = None,
        temperature: float | None = None,
        top_p: float | None = None,
    ) -> None:
        await self._stream(messages, tools, model, reasoning,
                           on_chunk, max_tokens, temperature, top_p)

    async def _stream(
        self, messages, tools, model, reasoning, on_chunk,
        max_tokens, temperature, top_p,
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
                LLM_BASE_URL,
                json=body,
                headers={"Authorization": f"Bearer {self.api_key}"},
            ) as resp:
                if resp.status_code != 200:
                    raw = (await resp.aread())[: LLM_ERROR_BODY_MAX_BYTES]
                    msg = raw.decode("utf-8", errors="replace").strip()
                    try:
                        api_msg = json.loads(raw).get("error", {}).get("message", "")
                        if api_msg:
                            msg = api_msg
                    except (json.JSONDecodeError, AttributeError):
                        pass
                    retryable = resp.status_code in (429, 500, 502, 503, 504)
                    raise DeepSeekError(
                        f"deepseek: HTTP {resp.status_code}: {msg}",
                        retryable=retryable,
                    )

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
                f"deepseek: stream idle for {int(LLM_READ_TIMEOUT)}s",
                retryable=True,
            ) from e
        except httpx.HTTPError as e:
            raise DeepSeekError(f"deepseek: request: {e}") from e
