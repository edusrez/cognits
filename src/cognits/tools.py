"""Port of internal/tools/tools.go: agent tool registry."""

from __future__ import annotations

import json
from abc import ABC, abstractmethod


def tool_error(msg: str) -> str:
    return json.dumps({"error": msg}, ensure_ascii=False)


class Tool(ABC):
    @property
    @abstractmethod
    def name(self) -> str: ...

    @property
    @abstractmethod
    def description(self) -> str: ...

    @property
    @abstractmethod
    def schema(self) -> dict: ...

    @abstractmethod
    async def execute(self, raw_args: str) -> str:
        """Receives arguments as raw JSON (may come malformed from the LLM);
        usage errors are returned as JSON {"error": ...}, not as an
        exception, so the model can correct itself."""


class Registry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def definitions(self) -> list[dict]:
        # Stable order (by name): a variable order would change the prompt
        # between requests and break DeepSeek's prefix-cache.
        defs = []
        for name in sorted(self._tools):
            t = self._tools[name]
            defs.append(
                {
                    "type": "function",
                    "function": {
                        "name": t.name,
                        "description": t.description,
                        "parameters": t.schema,
                    },
                }
            )
        return defs
