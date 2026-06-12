"""Port of internal/llm/llm.go: OpenAI-compatible message types.

Stream chunks are handled as raw JSON dicts; only the message has its own
type because it builds the payload with omitempty semantics.
"""

from __future__ import annotations

from dataclasses import dataclass, field

ROLE_SYSTEM = "system"
ROLE_USER = "user"
ROLE_ASSISTANT = "assistant"
ROLE_TOOL = "tool"


@dataclass
class ToolCall:
    id: str = ""
    type: str = "function"
    name: str = ""
    arguments: str = ""

    def to_payload(self) -> dict:
        return {
            "id": self.id,
            "type": self.type,
            "function": {"name": self.name, "arguments": self.arguments},
        }


@dataclass
class Message:
    role: str
    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_call_id: str = ""
    name: str = ""

    def to_payload(self) -> dict:
        # Parity with Go's omitempty tags: an assistant with tool_calls and
        # no content doesn't include "content".
        payload: dict = {"role": self.role}
        if self.content:
            payload["content"] = self.content
        if self.tool_calls:
            payload["tool_calls"] = [tc.to_payload() for tc in self.tool_calls]
        if self.tool_call_id:
            payload["tool_call_id"] = self.tool_call_id
        if self.name:
            payload["name"] = self.name
        return payload
