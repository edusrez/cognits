"""LLM client protocol: async streaming interface for any LLM provider.

Implementations: DeepSeekClient (llm/deepseek.py), future OpenAI, Anthropic.
"""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class LLMClient(Protocol):
    """Async streaming chat completions client.

    Every LLM provider must implement this protocol.
    """

    async def chat_completion_stream(
        self,
        messages: list[Any],
        tools: list[dict] | None,
        model: str,
        reasoning: str,
        on_chunk: Callable[[dict], None],
        max_tokens: int | None = None,
        temperature: float | None = None,
        top_p: float | None = None,
    ) -> None: ...

    async def aclose(self) -> None: ...
