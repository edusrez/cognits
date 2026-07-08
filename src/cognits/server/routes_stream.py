"""Port of internal/server/session_stream.go: the exact SSE wire format.

- `history` always first (snapshot atomic with the subscription).
- Tokens WITHOUT an `event:` line, in OpenAI delta format.
- Keepalive as a `: keepalive` comment every 15s.
- When the run ends, the pending queue is drained and `done` is emitted
  (data: null on the live route, data: {} on the snapshot route — both
  variants exist in the original Go).
"""

from __future__ import annotations

import asyncio
import json

from fastapi import FastAPI
from fastapi.responses import Response, StreamingResponse

from cognits.server.session_agent import SessionAgent
from cognits.server.exceptions import StorageError
from cognits.constants import KEEPALIVE_SECONDS
from cognits.storage.models import MessageRow

SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "X-Accel-Buffering": "no",
}


def _dumps(data) -> str:
    return json.dumps(data, ensure_ascii=False)


def _message_dict(m: MessageRow) -> dict:
    result = {
        "role": m.role,
        "content": m.content,
        "reasoning": m.reasoning,
    }
    if m.reports:
        try:
            result["reports"] = json.loads(m.reports)
        except (json.JSONDecodeError, TypeError):
            pass
    return result


def _format_event(ev: dict) -> str:
    t = ev["type"]
    data = ev.get("data")
    if t == "token":
        payload = {"choices": [{"delta": {"content": data}}]}
        return f"data: {_dumps(payload)}\n\n"
    if t == "reasoning":
        return f"event: reasoning\ndata: {_dumps({'content': data})}\n\n"
    if t == "error":
        return f"event: error\ndata: {_dumps({'message': data})}\n\n"
    if t in ("tool_start", "tool_end", "tool_progress", "subagent_end",
             "usage", "session_renamed", "ui_action", "setup_complete",
             "create_learning_session", "study_plan_updated"):
        return f"event: {t}\ndata: {_dumps(data)}\n\n"
    return ""


def register(app: FastAPI, st) -> None:
    @app.get("/api/sessions/{session_id}/stream")
    async def session_stream(session_id: str):
        sa: SessionAgent | None = st.active_agents.get(session_id)
        if sa is None:
            return await _messages_snapshot(st, session_id)

        # Subscription and snapshot are atomic (synchronous section): no
        # event can be both inside the snapshot and pending in the queue
        # (that would duplicate tokens).
        queue, snap = sa.subscribe_with_snapshot()

        history = {
            "messages": [_message_dict(m) for m in snap.messages],
            "toolStatus": snap.tool_status,
            "toolFavicons": snap.tool_favicons,
            "toolLog": snap.tool_log,
            "liveContent": snap.live_content,
            "liveReasoning": snap.live_reasoning,
            "liveReports": snap.live_reports,
            "agentActive": True,
        }

        async def gen():
            try:
                yield f"event: history\ndata: {_dumps(history)}\n\n"
                while True:
                    if sa.done_event.is_set():
                        # Drain pending events before closing.
                        while True:
                            try:
                                ev = queue.get_nowait()
                            except asyncio.QueueEmpty:
                                yield "event: done\ndata: null\n\n"
                                return
                            if ev is not None:
                                out = _format_event(ev)
                                if out:
                                    yield out
                    try:
                        ev = await asyncio.wait_for(queue.get(), timeout=KEEPALIVE_SECONDS)
                    except TimeoutError:
                        # Detects dead clients on write; without this a
                        # disconnected client would hold the generator open.
                        yield ": keepalive\n\n"
                        continue
                    if ev is None:
                        continue  # close() sentinel: back to the done check
                    out = _format_event(ev)
                    if out:
                        yield out
            finally:
                sa.unsubscribe(queue)

        return StreamingResponse(
            gen(), media_type="text/event-stream", headers=SSE_HEADERS
        )


async def _messages_snapshot(st, session_id: str) -> Response:
    if st.db is None:
        raise StorageError("db not available")

    try:
        rows = await asyncio.to_thread(st.messages.load, session_id)
    except Exception as e:
        raise StorageError(str(e))

    history = {"messages": [_message_dict(m) for m in rows]}
    body = f"event: history\ndata: {_dumps(history)}\n\nevent: done\ndata: {{}}\n\n"
    return Response(
        content=body,
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
