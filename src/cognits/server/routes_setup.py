"""Setup wizard SSE endpoint: streaming agentic onboarding chat."""

from __future__ import annotations

import asyncio
import contextlib
import datetime
import json
import logging

from fastapi import FastAPI, Request, Response
from fastapi.responses import StreamingResponse

from cognits.agent.agent import Agent, AgentConfig
from cognits.agent.prompts import ONBOARDING_SYSTEM_PROMPT
from cognits.agent.subagents import directory_reader_config, researcher_config
from cognits.agent.tool_deploy import DeploySubagent
from cognits.llm.deepseek import DeepSeekClient
from cognits.llm.types import ROLE_ASSISTANT, ROLE_SYSTEM, ROLE_USER, Message
from cognits.server.util import text_error
from cognits.storage.files import StudentProfile
from cognits.tinyfish import TinyfishClient
from cognits.tools import Registry

log = logging.getLogger("cognits.setup")

SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "X-Accel-Buffering": "no",
}

KEEPALIVE_SECONDS = 15


def _dumps(data) -> str:
    return json.dumps(data, ensure_ascii=False)


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
    if t in ("tool_start", "tool_end", "tool_progress", "subagent_end", "usage"):
        return f"event: {t}\ndata: {_dumps(data)}\n\n"
    return ""


def _extract_declared(text: str) -> dict:
    declared: dict = {}
    lines = text.split("\n")
    for line in lines:
        line = line.strip()
        if line.startswith("- Background:") or line.startswith("Background:"):
            declared["background"] = line.split(":", 1)[1].strip()
        elif line.startswith("- Project:") or line.startswith("Project:"):
            declared["project"] = line.split(":", 1)[1].strip()
        elif line.startswith("- Experience:") or line.startswith("Experience:"):
            declared["experience"] = line.split(":", 1)[1].strip()
        elif line.startswith("- Learning style:") or line.startswith("Learning style:"):
            declared["learning_style"] = line.split(":", 1)[1].strip()
        elif line.startswith("- Availability:") or line.startswith("Availability:"):
            declared["availability"] = line.split(":", 1)[1].strip()
        elif line.startswith("- Goals:") or line.startswith("Goals:"):
            declared["goals"] = line.split(":", 1)[1].strip()
    return declared


def register(app: FastAPI, st) -> None:
    @app.post("/api/setup/chat")
    async def setup_chat(request: Request):
        cfg = st.cached_config
        if cfg is None:
            return text_error("config not available", 500)
        if not cfg.llm_api_key:
            return text_error("API key not configured", 401)

        try:
            body = await request.json()
            if not isinstance(body, dict):
                raise ValueError("body")
            incoming = body.get("messages") or []
            if not isinstance(incoming, list):
                raise ValueError("messages")
        except (json.JSONDecodeError, ValueError, UnicodeDecodeError):
            return text_error("invalid body", 400)

        llm_client = DeepSeekClient(cfg.llm_api_key)
        tf_client = TinyfishClient(cfg.tinyfish_api_key)

        subagent_map: dict[str, AgentConfig] = {
            "directory_reader": directory_reader_config(
                "deepseek-v4-flash", "high", 50,
                docling_engine=st.docling_engine if st.docling_engine is not None and st.docling_engine.error is None else None,
                docling_config=cfg.docling_config,
            ),
        }
        if cfg.tinyfish_api_key:
            subagent_map["web_researcher"] = researcher_config(
                "deepseek-v4-flash", "high", 100, tf_client,
            )

        registry = Registry()
        deploy_tool = DeploySubagent(
            llm_client=llm_client,
            report_store=None,
            subagents=subagent_map,
            session_id=None,
            emit=None,
            rag_engine=None,
            tinyfish_api_key=cfg.tinyfish_api_key,
        )
        registry.register(deploy_tool)

        system_prompt = ONBOARDING_SYSTEM_PROMPT

        agent_cfg = AgentConfig(
            name="onboarding",
            model="deepseek-v4-pro",
            reasoning="max",
            max_steps=999,
            system_prompt=system_prompt,
            tools=registry,
            subagents=subagent_map,
        )
        agent = Agent(agent_cfg, llm_client)

        messages: list[Message] = []
        for m in incoming:
            role = m.get("role", "")
            content = m.get("content") or ""
            if role in (ROLE_USER, ROLE_ASSISTANT):
                messages.append(Message(role=role, content=content))

        if not any(m.role == ROLE_SYSTEM for m in messages):
            messages.insert(0, Message(role=ROLE_SYSTEM, content=system_prompt))

        response_content = ""
        profile_complete = False
        done_event = asyncio.Event()
        queue: asyncio.Queue[dict | None] = asyncio.Queue(maxsize=1024)

        def emit(ev: dict) -> None:
            nonlocal response_content
            t = ev.get("type")
            if t == "token" and isinstance(ev.get("data"), str):
                response_content += ev["data"]
            try:
                queue.put_nowait(ev)
            except asyncio.QueueFull:
                pass

        async def agent_runner():
            nonlocal profile_complete, response_content
            try:
                await agent.run(messages, emit)
            except asyncio.CancelledError:
                pass
            except Exception as e:
                log.error("setup agent: %s", e)
                try:
                    queue.put_nowait({"type": "error", "data": str(e)})
                except asyncio.QueueFull:
                    pass
            finally:
                if "[PROFILE COMPLETE]" in response_content:
                    profile_complete = True
                done_event.set()

        runner_task = asyncio.create_task(agent_runner())

        async def gen():
            try:
                yield f"event: history\ndata: {_dumps({'messages': incoming, 'agentActive': True})}\n\n"
                while True:
                    if done_event.is_set():
                        while True:
                            try:
                                ev = queue.get_nowait()
                            except asyncio.QueueEmpty:
                                break
                            if ev is not None:
                                out = _format_event(ev)
                                if out:
                                    yield out
                        yield "event: done\ndata: null\n\n"
                        return
                    try:
                        ev = await asyncio.wait_for(queue.get(), timeout=KEEPALIVE_SECONDS)
                    except TimeoutError:
                        yield ": keepalive\n\n"
                        continue
                    if ev is None:
                        continue
                    out = _format_event(ev)
                    if out:
                        yield out
            finally:
                runner_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await runner_task
                with contextlib.suppress(Exception):
                    await llm_client.aclose()
                with contextlib.suppress(Exception):
                    await tf_client.aclose()

                if profile_complete and st.store is not None:
                    declared = _extract_declared(response_content)
                    import datetime
                    profile = StudentProfile(
                        declared={
                            "background": declared.get("background", ""),
                            "goals": [declared.get("goals", "")],
                            "experience": declared.get("experience", ""),
                            "project": declared.get("project", ""),
                            "preferences": {
                                "style": declared.get("learning_style", "socratic"),
                            },
                            "availability": declared.get("availability", ""),
                        },
                        meta={
                            "created": datetime.datetime.now(datetime.timezone.utc).isoformat() + "Z",
                            "sessions": 0,
                            "source": "onboarding",
                        },
                    )
                    try:
                        await asyncio.to_thread(st.store.save_profile, profile)
                    except Exception as e:
                        log.error("setup save profile: %s", e)

        return StreamingResponse(
            gen(), media_type="text/event-stream", headers=SSE_HEADERS
        )
