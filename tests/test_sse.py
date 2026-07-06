"""Verifies raw SSE framing against the frontend contract:
history first, tokens without event name (OpenAI delta format),
queue drain and both done variants (null / {})."""

import asyncio
import json

import httpx

from cognits.server.app import AppState, create_app
from cognits.server.session_agent import SessionAgent
from cognits.storage.models import MessageRow


def _parse_sse(raw: str) -> list[tuple[str, str]]:
    """Returns (event, data) per frame; '' as event for frames without
    `event:` and None-data for keepalive comments."""
    frames = []
    for block in raw.split("\n\n"):
        if not block.strip():
            continue
        event = ""
        data = None
        for line in block.split("\n"):
            if line.startswith("event: "):
                event = line[len("event: "):]
            elif line.startswith("data: "):
                data = line[len("data: "):]
            elif line.startswith(":"):
                event = "comment"
        frames.append((event, data))
    return frames


def test_stream_agente_activo(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    asyncio.run(_run_active_stream_test())


async def _run_active_stream_test():
    state = AppState()
    app = create_app(state)

    sa = SessionAgent("s1", [MessageRow(role="user", content="hello")])
    sa.live_content = "He"
    state.active_agents["s1"] = sa

    async def publisher():
        await asyncio.sleep(0.05)
        sa.publish({"type": "token", "data": "llo"})
        sa.publish({"type": "reasoning", "data": "thinking"})
        sa.publish({"type": "tool_progress", "data": {"message": "Searching the Web"}})
        sa.publish({"type": "usage", "data": {"prompt_tokens": 7}})
        # Events pending in the queue at close: must drain before done.
        sa.publish({"type": "token", "data": "!"})
        state.active_agents.pop("s1", None)
        sa.close()

    pub = asyncio.create_task(publisher())

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
        async with client.stream("GET", "/api/sessions/s1/stream") as resp:
            assert resp.status_code == 200
            assert resp.headers["content-type"].startswith("text/event-stream")
            raw = (await resp.aread()).decode()

    await pub
    frames = _parse_sse(raw)

    # history ALWAYS first, with the live state from the snapshot.
    assert frames[0][0] == "history"
    history = json.loads(frames[0][1])
    assert history["agentActive"] is True
    assert history["liveContent"] == "He"
    assert history["messages"][0] == {
        "role": "user", "content": "hello", "reasoning": "",
    }
    assert "toolLog" in history
    assert isinstance(history["toolLog"], list)

    # Tokens without event name, OpenAI delta format.
    tokens = [f for f in frames if f[0] == ""]
    assert [json.loads(d)["choices"][0]["delta"]["content"] for _, d in tokens] == ["llo", "!"]

    assert ("reasoning", '{"content": "thinking"}') in [
        (e, d) for e, d in frames if e == "reasoning"
    ]
    assert any(e == "tool_progress" for e, _ in frames)
    assert any(e == "usage" for e, _ in frames)

    # done ALWAYS last, with data null in the live route.
    assert frames[-1] == ("done", "null")


def test_stream_sesion_inactiva(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    asyncio.run(_run_inactive_stream_test())


async def _run_inactive_stream_test():
    state = AppState()
    app = create_app(state)
    state.messages.save(
        "old", [MessageRow(role="user", content="history")]
    )

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
        resp = await client.get("/api/sessions/old/stream")

    frames = _parse_sse(resp.text)
    assert frames[0][0] == "history"
    history = json.loads(frames[0][1])
    assert history["messages"][0]["content"] == "history"
    assert "agentActive" not in history
    # Snapshot variant: data {} (not null).
    assert frames[-1] == ("done", "{}")


def test_chat_409_and_cancellation(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    asyncio.run(_run_409_test())


async def _run_409_test():
    state = AppState()
    app = create_app(state)
    # Configure an API key to pass the 401 check.
    from cognits.storage.files import Config

    state.cached_config = Config(llm_api_key="sk-test")

    # Agent already active → 409.
    sa = SessionAgent("s1", [])
    sa.task = asyncio.create_task(asyncio.sleep(10))
    state.active_agents["s1"] = sa

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
        resp = await client.post(
            "/api/chat?sessionId=s1", json={"messages": [{"role": "user", "content": "x"}]}
        )
        assert resp.status_code == 409

        # DELETE cancels the task but does NOT unregister (the run's finally does that).
        resp = await client.delete("/api/sessions/s1/agent")
        assert resp.status_code == 204
        assert "s1" in state.active_agents
        try:
            await sa.task
        except asyncio.CancelledError:
            pass
        assert sa.task.cancelled()

        # Without API key → 400 (ConfigError); without sessionId → 400.
        state.cached_config = Config()
        resp = await client.post("/api/chat?sessionId=s2", json={"messages": []})
        assert resp.status_code == 400
        state.cached_config = Config(llm_api_key="k")
        resp = await client.post("/api/chat", json={"messages": []})
        assert resp.status_code == 400

    state.active_agents.clear()
