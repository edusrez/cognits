"""Port de internal/llm/deepseek.go: cliente streaming de DeepSeek.

El watchdog de inactividad de Go (120s) se obtiene gratis con el read timeout
de httpx, que aplica a cada operación de lectura del socket, no al stream
completo: si la API se queda muda sin FIN (NAT, wifi caída), salta ReadTimeout.
"""

from __future__ import annotations

import json
from collections.abc import Callable

import httpx

from cognits.llm.types import Message

# Si la API deja de enviar datos este tiempo, el stream se da por muerto.
STREAM_IDLE_TIMEOUT = 120.0

BASE_URL = "https://api.deepseek.com/chat/completions"


class DeepSeekError(Exception):
    pass


class DeepSeekClient:
    def __init__(self, api_key: str):
        self.api_key = api_key
        # Timeouts por fase y nunca uno global: un timeout total cortaría
        # streams legítimos de varios minutos.
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
    ) -> None:
        # La API de thinking es binaria: "high"/"max" → enabled. Con tools se
        # omite el parámetro (la API lo rechaza en esa combinación).
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

        try:
            async with self._client.stream(
                "POST",
                BASE_URL,
                json=body,
                headers={"Authorization": f"Bearer {self.api_key}"},
            ) as resp:
                if resp.status_code != 200:
                    # Limitar la lectura (un cuerpo enorme inflaría logs/chat) y
                    # extraer el mensaje del JSON de error de la API si lo trae.
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
                f"deepseek: stream inactivo durante {int(STREAM_IDLE_TIMEOUT)}s"
            ) from e
        except httpx.HTTPError as e:
            raise DeepSeekError(f"deepseek: request: {e}") from e
