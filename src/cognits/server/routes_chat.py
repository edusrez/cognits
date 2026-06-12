"""Port de internal/server/chat.go: POST /api/chat y DELETE .../agent.

El run del agente es una asyncio.Task; su bloque finally es 100% síncrono
(persistencia de la respuesta parcial incluida) para que una segunda
cancelación no pueda saltarse la limpieza en un await.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from datetime import datetime

from fastapi import FastAPI, Request, Response

from cognits.agent.agent import Agent, AgentConfig
from cognits.agent.prompts import DEFAULT_AGENT_ID, default_agent_prompt
from cognits.agent.subagents import documentalista_config, researcher_config
from cognits.agent.tool_deploy import DeploySubagent
from cognits.llm.deepseek import DeepSeekClient
from cognits.llm.types import ROLE_SYSTEM, Message
from cognits.server.session_agent import SessionAgent
from cognits.server.util import text_error
from cognits.storage.db import MessageRow
from cognits.storage.files import Config
from cognits.tinyfish import TinyfishClient
from cognits.tools import Registry

log = logging.getLogger("cognits.chat")

DEFAULT_MODEL = "deepseek-v4-pro"
DEFAULT_RESEARCHER_MAX_STEPS = 15
ORCHESTRATOR_MAX_STEPS = 25

SPANISH_MONTHS = [
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
]
# Sin acentos, como en el Go original.
SPANISH_WEEKDAYS = [
    "lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo",
]

FORMATTING_RULES = (
    "## Formatting rules\n"
    "- Never use emojis (like ✅, ❌, 🚀, 💡, ⚠️, 🔥) in your responses\n"
    "- For bulleted lists: use • or standard Markdown -\n"
    "- For emphasis: use **bold** or *italic*\n"
    "- For positive/negative indicators: use ✓ and ✗ (Unicode U+2713/U+2717)\n"
    "- For code: use ``` fenced blocks\n"
    "- For tips/notes: use > blockquotes with a bold label\n"
    "- Use plain text and standard Markdown only"
)


def build_chat_messages(
    cfg: Config, incoming: list[dict]
) -> tuple[list[Message], list[MessageRow]]:
    """Separa lo que ve el LLM de lo que se persiste: el historial se guarda
    tal cual llegó y solo el último mensaje del usuario lleva sello de fecha,
    para no invalidar el prefix-cache de DeepSeek en cada turno."""
    llm_messages: list[Message] = []

    if cfg.user_name or cfg.user_location:
        ctx_parts = "## Context\n"
        if cfg.user_name:
            ctx_parts += f"User: {cfg.user_name}\n"
        if cfg.user_location:
            ctx_parts += f"Location: {cfg.user_location}\n"
        llm_messages.append(Message(role=ROLE_SYSTEM, content=ctx_parts))

    llm_messages.append(Message(role=ROLE_SYSTEM, content=FORMATTING_RULES))

    last_user_idx = -1
    for i, m in enumerate(incoming):
        if m.get("role") == "user":
            last_user_idx = i

    now = datetime.now().astimezone()
    tz = now.strftime("%Z") or now.strftime("%z")
    date_str = (
        f"{SPANISH_WEEKDAYS[now.weekday()]}, {now.day} de "
        f"{SPANISH_MONTHS[now.month - 1]} de {now.year}, "
        f"{now.strftime('%H:%M')} {tz}"
    )

    storage_messages: list[MessageRow] = []
    for i, m in enumerate(incoming):
        role = m.get("role", "")
        if role not in ("user", "assistant"):
            continue
        content = m.get("content") or ""
        if i == last_user_idx:
            content = f"[{date_str}]\n{content.strip()}"
        llm_messages.append(Message(role=role, content=content))
        storage_messages.append(
            MessageRow(
                role=role,
                content=m.get("content") or "",
                reasoning=m.get("reasoning") or "",
                report_id=m.get("reportId") or "",
                report_title=m.get("reportTitle") or "",
            )
        )

    return llm_messages, storage_messages


def register(app: FastAPI, st) -> None:
    @app.post("/api/chat")
    async def chat(request: Request):
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

        sid = request.query_params.get("sessionId") or ""
        if not sid:
            return text_error("sessionId required", 400)

        # Resolución de config: sesión → global → default.
        model = cfg.llm_model
        reasoning = cfg.llm_reasoning
        agent_id = cfg.llm_agent_id
        if st.report_store is not None:
            try:
                sess_cfg = await asyncio.to_thread(
                    st.report_store.load_session_config, sid
                )
            except Exception as e:
                log.error("chat: load session config: %s", e)
                sess_cfg = None
            if sess_cfg is not None:
                model = sess_cfg.model or model
                reasoning = sess_cfg.reasoning or reasoning
                agent_id = sess_cfg.agent_id or agent_id
        model = model or DEFAULT_MODEL
        agent_id = agent_id or DEFAULT_AGENT_ID
        system_prompt = cfg.agent_overrides.get(agent_id) or default_agent_prompt(agent_id)

        llm_messages, storage_messages = build_chat_messages(cfg, incoming)

        # Check 409 + registro sin await entre medias: atómico en el loop.
        if sid in st.active_agents:
            return text_error("agent already running", 409)
        sa = SessionAgent(sid, storage_messages)
        st.active_agents[sid] = sa
        sa.task = asyncio.create_task(
            _run_agent(st, sa, cfg, sid, model, reasoning, system_prompt, llm_messages)
        )

        return Response(status_code=202)

    @app.delete("/api/sessions/{session_id}/agent")
    async def cancel_agent(session_id: str):
        sa = st.active_agents.get(session_id)
        # La limpieza de active_agents la hace siempre el finally del run;
        # borrar aquí permitiría arrancar un segundo run concurrente.
        if sa is not None and sa.task is not None:
            sa.task.cancel()
        return Response(status_code=204)


async def _run_agent(
    st,
    sa: SessionAgent,
    cfg: Config,
    sid: str,
    model: str,
    reasoning: str,
    system_prompt: str,
    llm_messages: list[Message],
) -> None:
    acc = {"content": "", "reasoning": ""}
    llm_client = DeepSeekClient(cfg.llm_api_key)
    tf_client = TinyfishClient(cfg.tinyfish_api_key)

    try:
        # El servidor es la fuente de verdad: guarda historial + mensaje nuevo
        # ya al empezar. Aquí y no en el handler: el POST responde al instante
        # aunque SQLite esté ocupado, y los suscriptores inmediatos leen el
        # snapshot de sa.messages en memoria, no de la DB.
        if st.report_store is not None:
            try:
                await asyncio.to_thread(st.report_store.save_messages, sid, sa.messages)
            except Exception as e:
                log.error("chat: save messages (session %s): %s", sid, e)

        # Actualización de estado y fan-out van juntos en sa.publish para que
        # los snapshots de suscripción no dupliquen ni pierdan eventos. Los
        # closures update corren dentro de publish (sección síncrona).
        def process_event(ev: dict) -> None:
            update = None
            t = ev["type"]
            data = ev.get("data")
            if t == "token" and isinstance(data, str):
                def update():
                    acc["content"] += data
                    sa.live_content = acc["content"]
            elif t == "reasoning" and isinstance(data, str):
                def update():
                    acc["reasoning"] += data
                    sa.live_reasoning = acc["reasoning"]
            elif t == "tool_progress" and isinstance(data, dict):
                msg = data.get("message")
                if isinstance(msg, str):
                    def update():
                        sa.tool_status = msg
            elif t == "subagent_end":
                def update():
                    sa.tool_status = ""
                    if isinstance(data, dict):
                        rid = data.get("reportId")
                        if isinstance(rid, str):
                            sa.live_report_id = rid
                        rt = data.get("title")
                        if isinstance(rt, str):
                            sa.live_report_title = rt
            sa.publish(ev, update)

        subagent_cfgs = cfg.subagent_config or {}
        web_cfg = subagent_cfgs.get("web_researcher")
        web_model = (web_cfg.model if web_cfg else "") or DEFAULT_MODEL
        web_reasoning = web_cfg.reasoning if web_cfg else ""
        web_max_steps = web_cfg.max_steps if web_cfg else 0
        if web_max_steps <= 0:
            web_max_steps = DEFAULT_RESEARCHER_MAX_STEPS

        subagent_map: dict[str, AgentConfig] = {
            "web_researcher": researcher_config(
                web_model, web_reasoning, web_max_steps, tf_client
            )
        }

        if st.rag is not None and st.rag.error is None:
            doc_cfg = subagent_cfgs.get("documentalista")
            doc_model = (doc_cfg.model if doc_cfg else "") or DEFAULT_MODEL
            doc_reasoning = doc_cfg.reasoning if doc_cfg else ""
            doc_max_steps = doc_cfg.max_steps if doc_cfg else 0
            if doc_max_steps <= 0:
                doc_max_steps = DEFAULT_RESEARCHER_MAX_STEPS
            subagent_map["documentalista"] = documentalista_config(
                doc_model,
                doc_reasoning,
                doc_max_steps,
                llm_client,
                st.rag,
                tf_client,
                st.report_store,
                lambda: sid,
                process_event,
            )

        registry = Registry()
        registry.register(
            DeploySubagent(
                llm_client=llm_client,
                report_store=st.report_store,
                subagents=subagent_map,
                session_id=lambda: sid,
                emit=process_event,
            )
        )

        ag = Agent(
            AgentConfig(
                name="orchestrator",
                model=model,
                reasoning=reasoning,
                max_steps=ORCHESTRATOR_MAX_STEPS,
                system_prompt=system_prompt,
                tools=registry,
                subagents=subagent_map,
            ),
            llm_client,
        )

        try:
            await ag.run(llm_messages, process_event)
        except asyncio.CancelledError:
            # La cancelación del usuario no es un error de cara al chat.
            log.info("chat: agent run cancelled (session %s)", sid)
        except Exception as e:
            log.error("chat: agent run (session %s): %s", sid, e)
            sa.publish({"type": "error", "data": str(e)})
    finally:
        # Bloque 100% síncrono: persistir el parcial, desregistrar y cerrar.
        content = acc["content"]
        reasoning_text = acc["reasoning"]
        assistant_row = None
        if content or reasoning_text or sa.live_report_id:
            assistant_row = MessageRow(
                role="assistant",
                content=content,
                reasoning=reasoning_text,
                report_id=sa.live_report_id,
                report_title=sa.live_report_title,
            )
            sa.messages.append(assistant_row)
        sa.live_content = ""
        sa.live_reasoning = ""
        sa.live_report_id = ""
        sa.live_report_title = ""
        sa.tool_status = ""

        # El historial ya se persistió al arrancar el run; solo falta añadir la
        # respuesta (también el parcial, si el run se canceló a mitad). Llamada
        # sqlite directa (ms) en vez de to_thread: un await aquí podría ser
        # interrumpido por una segunda cancelación y saltarse el resto.
        if assistant_row is not None and st.report_store is not None:
            try:
                st.report_store.append_message(sid, assistant_row)
            except Exception as e:
                log.error("chat: append message (session %s): %s", sid, e)

        st.active_agents.pop(sid, None)
        sa.close()

        # Cierre de clientes HTTP sin await (fire-and-forget en el loop).
        for client in (llm_client, tf_client):
            with contextlib.suppress(Exception):
                asyncio.get_running_loop().create_task(client.aclose())
