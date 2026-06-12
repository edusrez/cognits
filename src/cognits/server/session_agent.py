"""Port del SessionAgent de internal/server/server.go.

INVARIANTE: todos los métodos de esta clase son síncronos y se llaman solo
desde el event loop. En asyncio una sección sin await es atómica, así que la
pareja "actualizar estado + fan-out" de publish() y la pareja "snapshot +
suscripción" de subscribe_with_snapshot() no pueden intercalarse: un evento o
bien precede a un snapshot (está en él y no en la cola) o bien lo sigue (está
en la cola y no en él) — nunca en ambos, que era la carrera que duplicaba
tokens al suscribirse a mitad de stream. Si algún día hiciera falta publicar
desde un hilo, usar loop.call_soon_threadsafe.
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
        # done_event se activa cuando el run termina; señala fin a los suscriptores.
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
        # El envío dropea eventos si el buffer está lleno (no puede bloquear
        # al agente); un buffer amplio hace los drops improbables y la recarga
        # de DB en "done" sigue siendo la red de seguridad.
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
        """Marca el fin del run y despierta a los lectores bloqueados con un
        sentinela None (equivalente al close(sa.Done) de Go)."""
        self.done_event.set()
        for q in self.subscribers:
            try:
                q.put_nowait(None)
            except asyncio.QueueFull:
                pass
