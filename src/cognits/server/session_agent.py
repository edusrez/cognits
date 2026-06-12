"""Port of the SessionAgent from internal/server/server.go.

INVARIANT: every method of this class is synchronous and called only from
the event loop. In asyncio a section without an await is atomic, so the
"update state + fan-out" pair in publish() and the "snapshot + subscribe"
pair in subscribe_with_snapshot() cannot interleave: an event either
precedes a snapshot (it is in it and not in the queue) or follows it (it is
in the queue and not in it) — never both, which was the race that duplicated
tokens when subscribing mid-stream. If publishing from a thread is ever
needed, use loop.call_soon_threadsafe.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field

from cognits.storage.db import MessageRow

SUBSCRIBER_BUFFER = 1024


@dataclass
class AgentSnapshot:
    messages: list[MessageRow] = field(default_factory=list)
    tool_status: str = ""
    live_content: str = ""
    live_reasoning: str = ""
    live_report_id: str = ""
    live_report_title: str = ""


class SessionAgent:
    def __init__(self, session_id: str, messages: list[MessageRow]):
        self.session_id = session_id
        self.task: asyncio.Task | None = None
        # done_event is set when the run finishes; signals the end to subscribers.
        self.done_event = asyncio.Event()

        self.messages = messages
        self.tool_status = ""
        self.live_content = ""
        self.live_reasoning = ""
        self.live_report_id = ""
        self.live_report_title = ""
        self.subscribers: dict[asyncio.Queue, None] = {}

    def publish(self, event: dict, update: Callable[[], None] | None = None) -> None:
        if update is not None:
            update()
        # The send drops events if the buffer is full (it cannot block the
        # agent); a large buffer makes drops unlikely and the DB reload on
        # "done" remains the safety net.
        for q in self.subscribers:
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                pass

    def subscribe_with_snapshot(self) -> tuple[asyncio.Queue, AgentSnapshot]:
        q: asyncio.Queue = asyncio.Queue(maxsize=SUBSCRIBER_BUFFER)
        self.subscribers[q] = None
        snap = AgentSnapshot(
            messages=list(self.messages),
            tool_status=self.tool_status,
            live_content=self.live_content,
            live_reasoning=self.live_reasoning,
            live_report_id=self.live_report_id,
            live_report_title=self.live_report_title,
        )
        return q, snap

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self.subscribers.pop(q, None)

    def close(self) -> None:
        """Marks the end of the run and wakes blocked readers with a None
        sentinel (equivalent to Go's close(sa.Done))."""
        self.done_event.set()
        for q in self.subscribers:
            try:
                q.put_nowait(None)
            except asyncio.QueueFull:
                pass
