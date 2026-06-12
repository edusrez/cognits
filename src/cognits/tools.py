"""Port de internal/tools/tools.go: registry de herramientas del agente."""

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
        """Recibe los argumentos como JSON crudo (puede venir malformado del
        LLM); los errores de uso se devuelven como JSON {"error": ...}, no
        como excepción, para que el modelo pueda corregirse."""


class Registry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def definitions(self) -> list[dict]:
        # Orden estable (por nombre): un orden variable cambiaría el prompt
        # entre peticiones y rompería el prefix-cache de DeepSeek.
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
