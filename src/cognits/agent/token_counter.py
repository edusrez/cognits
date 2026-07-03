"""Token counter using deepseek-tokenizer (128K byte-level BPE).

Falls back to a heuristic (chars // 4) if the tokenizer is not installed.
"""

from __future__ import annotations

from cognits.llm.types import Message


class TokenCounter:
    def __init__(self):
        self._encoder = None
        try:
            from deepseek_tokenizer import Tokenizer
            self._encoder = Tokenizer()
        except ImportError:
            pass

    def count(self, text: str) -> int:
        if self._encoder is not None:
            return len(self._encoder.encode(text))
        return max(1, int(len(text) / 3.5))

    def count_messages(self, messages: list[Message]) -> int:
        total = 0
        for m in messages:
            total += self.count(m.content or "")
            if m.tool_calls:
                for tc in m.tool_calls:
                    total += self.count(tc.arguments or "")
                    total += self.count(tc.name or "")
        return total
