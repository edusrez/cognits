"""Chat service: agent lifecycle, subagent map, tool registry, event bridge.

Extracted from routes_chat.py:_run_agent (410 lines, 7 responsibilities).
routes_chat.py now delegates to ChatService.run_agent() and is ~250 lines
of pure HTTP dispatch.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from typing import Any, Callable

from cognits.agent.agent import Agent, AgentConfig
from cognits.agent.subagents import (
    directory_reader_config,
    documentalist_config,
    evaluator_config,
    researcher_config,
    session_analyzer_config,
    skill_planner_config,
    study_planner_config,
    teacher_config,
)
from cognits.agent.tool_deploy import DeploySubagent
from cognits.agent.tool_ui import ApplyProfile, CreateLearningSession, FinishSetup
from cognits.agent.agent import Agent, AgentConfig
from cognits.agent.subagents import session_namer_config
from cognits.constants import DEFAULT_FLASH_MODEL, MAX_SESSION_NAME_LENGTH, SESSION_NAMER_MAX_TOKENS, SESSION_NAMER_TEMPERATURE
from cognits.llm.types import ROLE_SYSTEM, ROLE_USER
from cognits.constants import DEFAULT_MODEL, EVALUATOR_MAX_STEPS, ORCHESTRATOR_MAX_STEPS, RESEARCHER_MAX_STEPS, STUDY_PLANNER_DEFAULT_STEPS
from cognits.llm.deepseek import DeepSeekClient
from cognits.llm.types import Message
from cognits.server.util import MONTHS, WEEKDAYS
from cognits.server.session_agent import SessionAgent
from cognits.storage.files import Config
from cognits.storage.models import MessageRow
from cognits.tinyfish import TinyfishClient
from cognits.tools import Regasync def _run_session_namer(
    st,
    sa: SessionAgent,
    cfg: Config,
    sid: str,
    incoming: list[dict],
) -> None:
    """Fire-and-forget: generates a session name from the first user message."""
    logger = logging.getLogger("cognits.session_namer")
    try:
        user_msgs = [m for m in incoming if m.get("role") == "user"]
        if not user_msgs:
            return
        first_msg = user_msgs[0].get("content", "").strip()
        if not first_msg:
            return

        now = datetime.now().astimezone()
        tz = now.strftime("%Z") or now.strftime("%z")
        date_stamp = (
            f"{WEEKDAYS[now.weekday()]}, {now.day} {MONTHS[now.month - 1]} "
            f"{now.year}, {now.strftime('%H:%M')} {tz}"
        )
        context = f"Today is {date_stamp}. "
        if cfg.user_name:
            context += f"The user's name is {cfg.user_name}. "
        if cfg.user_location:
            context += f"Their location is set to {cfg.user_location}. "
        context += f"The project directory is '{Path.cwd().name}'."

        model = DEFAULT_FLASH_MODEL
        ag_cfg = session_namer_config(
            model=model,
            max_tokens=SESSION_NAMER_MAX_TOKENS,
            temperature=SESSION_NAMER_TEMPERATURE,
        )
        llm_client = DeepSeekClient(cfg.llm_api_key)
        ag = Agent(ag_cfg, llm_client)

        messages = [
            Message(role=ROLE_SYSTEM, content=context),
            Message(role=ROLE_USER, content=first_msg),
        ]
        try:
            content = await ag.run(messages, emit=lambda _ev: None)
        except Exception as e:
            logger.error("session_namer: agent run: %s", e)
            return

        name = content.strip().strip('"\'').strip()
        if not name:
            return
        if len(name) > MAX_SESSION_NAME_LENGTH:
            name = name[:MAX_SESSION_NAME_LENGTH - 3] + "..."

        logger.info("session_namer: renaming %s -> %s", sid, name)
        await asyncio.to_thread(st.store.rename_session, sid, name)
        sa.publish({"type": "session_renamed", "data": {"name": name}})
    except asyncio.CancelledError:
        pass
    except Exception:
        logger.exception("session_namer: failed")
    finally:
        with contextlib.suppress(Exception):
            asyncio.get_running_loop().create_task(llm_client.aclose())




istry

log = logging.getLogger("cognits.chat")


class ChatService:
    """Orchestrator agent lifecycle: config cascade, subagent map, tool
    registry, agent construction, run, persistence."""

    def __init__(
        self,
        st,
        sa: SessionAgent,
        cfg: Config,
        sid: str,
        model: str,
        reasoning: str,
        system_prompt: str,
        llm_messages: list[Message],
        incoming: list[dict],
        agent_id: str,
    ):
        self.st = st
        self.sa = sa
        self.cfg = cfg
        self.sid = sid
        self.model = model
        self.reasoning = reasoning
        self.system_prompt = system_prompt
        self.llm_messages = llm_messages
        self.incoming = incoming
        self.agent_id = agent_id

    async def run_agent(self) -> None:
        st = self.st
        sa = self.sa
        sid = self.sid
        cfg = self.cfg
        acc: dict[str, str] = {"content": "", "reasoning": ""}

        llm_client = DeepSeekClient(cfg.llm_api_key)
        tf_client = TinyfishClient(cfg.tinyfish_api_key)

        try:
            if sum(1 for m in self.incoming if m.get("role") == "user") == 1:
                asyncio.create_task(
                    _run_session_namer(st, sa, cfg, sid, self.incoming)
                )

            if st.db is not None:
                try:
                    await asyncio.to_thread(st.messages.save, sid, sa.messages)
                except Exception as e:
                    log.error("chat: save messages (session %s): %s", sid, e)

            process_event = self._make_process_event(acc, sa, st, sid)

            subagent_map = self._build_subagent_map(
                process_event, cfg, sid, llm_client, tf_client
            )

            registry = self._build_tool_registry(
                process_event, subagent_map, cfg, sid, llm_client, tf_client
            )

            max_steps = cfg.max_steps or ORCHESTRATOR_MAX_STEPS
            ag = Agent(
                AgentConfig(
                    name=self.agent_id,
                    model=self.model,
                    reasoning=self.reasoning,
                    max_steps=max_steps,
                    max_tokens=cfg.max_tokens or None,
                    temperature=cfg.temperature or None,
                    top_p=cfg.top_p or None,
                    system_prompt=self.system_prompt,
                    tools=registry,
                    subagents=subagent_map,
                ),
                llm_client,
            )

            try:
                def _orchestrator_emit(ev: dict) -> None:
                    if ev.get("type") == "usage" and isinstance(ev.get("data"), dict):
                        ev["data"]["source"] = "orchestrator"
                    process_event(ev)

                await ag.run(self.llm_messages, _orchestrator_emit)
            except asyncio.CancelledError:
                log.info("chat: agent run cancelled (session %s)", sid)
            except Exception as e:
                log.error("chat: agent run (session %s): %s", sid, e)
                sa.publish({"type": "error", "data": str(e)})
        finally:
            self._persist_partial(acc, sa, st, sid, llm_client, tf_client)

    # -----------------------------------------------------------------
    # internal
    # -----------------------------------------------------------------

    def _make_process_event(
        self, acc: dict[str, str], sa: SessionAgent, st, sid: str
    ) -> Callable[[dict], None]:
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
                favicons = data.get("favicons", [])
                is_clearing = False
                is_action = False
                if isinstance(msg, str):
                    if msg:
                        agent = data.get("agent", "") if isinstance(data, dict) else ""
                        data["agent"] = agent
                        status = msg
                        if msg.endswith("Thinking...") or msg.endswith("Writing..."):
                            is_clearing = True
                            data["favicons"] = []
                            if len(sa.tool_favicons) == 0:
                                data["message"] = status
                                is_action = True
                            else:
                                data["message"] = sa.tool_status
                        else:
                            data["message"] = status
                            is_clearing = False
                            is_action = True
                    else:
                        status = ""
                        is_clearing = True
                        data["favicons"] = []
                        is_action = True
                    has_favicons = favicons and isinstance(favicons, list)
                    def update():
                        if is_action:
                            sa.tool_status = status
                        if is_clearing:
                            sa.tool_favicons = []
                        if has_favicons:
                            sa.tool_favicons = list(favicons)
                elif favicons and isinstance(favicons, list):
                    def update():
                        sa.tool_favicons = list(favicons)
                    data["message"] = sa.tool_status
            elif t == "tool_start":
                if acc["content"] or acc["reasoning"]:
                    partial = MessageRow(
                        role="assistant",
                        content=acc["content"],
                        reasoning=acc["reasoning"],
                    )
                    last = sa.messages[-1] if sa.messages else None
                    if last is None or last.role != "assistant" or last.content != acc["content"]:
                        def update():
                            sa.messages.append(partial)
                            acc["content"] = ""
                            acc["reasoning"] = ""
                            sa.live_content = ""
                            sa.live_reasoning = ""
                            if st.db is not None:
                                try:
                                    st.messages.append(sid, partial)
                                except Exception:
                                    pass
            elif t == "subagent_end":
                def update():
                    sa.tool_status = ""
                    sa.tool_favicons = []
                    if isinstance(data, dict):
                        rid = data.get("reportId")
                        rt = data.get("title")
                        if isinstance(rid, str) and isinstance(rt, str):
                            sa.live_reports.append({"reportId": rid, "reportTitle": rt})
            sa.publish(ev, update)
        return process_event

    def _build_subagent_map(
        self, process_event, cfg, sid, llm_client, tf_client
    ) -> dict[str, AgentConfig]:
        st = self.st
        subagent_cfgs = cfg.subagent_config or {}
        web_cfg = subagent_cfgs.get("web_researcher")
        web_model = (web_cfg.model if web_cfg else "") or DEFAULT_MODEL
        web_reasoning = web_cfg.reasoning if web_cfg else ""
        web_max_steps = web_cfg.max_steps if web_cfg else 0
        if web_max_steps <= 0:
            web_max_steps = RESEARCHER_MAX_STEPS
        web_max_tokens = web_cfg.max_tokens if web_cfg else 0
        web_temperature = web_cfg.temperature if web_cfg else 0.0
        web_top_p = web_cfg.top_p if web_cfg else 0.0
        web_prompt = cfg.agent_overrides.get("web_researcher") or None

        subagent_map: dict[str, AgentConfig] = {
            "web_researcher": researcher_config(
                web_model, web_reasoning, web_max_steps, tf_client,
                rag_engine=st.rag if st.rag is not None and st.rag.error is None else None,
                max_tokens=web_max_tokens or None,
                temperature=web_temperature or None,
                top_p=web_top_p or None,
                system_prompt_override=web_prompt,
            ),
            "directory_reader": directory_reader_config(
                web_model, web_reasoning, web_max_steps,
                docling_engine=st.docling_engine if st.docling_engine is not None and st.docling_engine.error is None else None,
                docling_config=cfg.docling_config,
                max_tokens=web_max_tokens or None,
                temperature=web_temperature or None,
                top_p=web_top_p or None,
            ),
        }

        if st.rag is not None and st.rag.error is None:
            doc_cfg = subagent_cfgs.get("documentalist")
            doc_model = (doc_cfg.model if doc_cfg else "") or DEFAULT_MODEL
            doc_reasoning = doc_cfg.reasoning if doc_cfg else ""
            doc_max_steps = doc_cfg.max_steps if doc_cfg else 0
            if doc_max_steps <= 0:
                doc_max_steps = RESEARCHER_MAX_STEPS
            doc_max_tokens = doc_cfg.max_tokens if doc_cfg else 0
            doc_temperature = doc_cfg.temperature if doc_cfg else 0.0
            doc_top_p = doc_cfg.top_p if doc_cfg else 0.0
            doc_prompt = cfg.agent_overrides.get("documentalist") or None
            subagent_map["documentalist"] = documentalist_config(
                doc_model, doc_reasoning, doc_max_steps,
                llm_client, st.rag, tf_client,
                st.reports, lambda: sid, process_event,
                max_tokens=doc_max_tokens or None,
                temperature=doc_temperature or None,
                top_p=doc_top_p or None,
                system_prompt_override=doc_prompt,
            )

        if cfg.tinyfish_api_key:
            planner_cfg = subagent_cfgs.get("skill_planner")
            planner_model = (planner_cfg.model if planner_cfg else "") or DEFAULT_MODEL
            planner_reasoning = planner_cfg.reasoning if planner_cfg else "max"
            planner_max_steps = planner_cfg.max_steps if planner_cfg else 0
            if planner_max_steps <= 0:
                planner_max_steps = ORCHESTRATOR_MAX_STEPS
            planner_max_tokens = planner_cfg.max_tokens if planner_cfg else 0
            planner_temperature = planner_cfg.temperature if planner_cfg else 0.0
            planner_top_p = planner_cfg.top_p if planner_cfg else 0.0
            planner_prompt = cfg.agent_overrides.get("skill_planner") or None
            subagent_map["skill_planner"] = skill_planner_config(
                planner_model, planner_reasoning, planner_max_steps,
                llm_client,
                st.rag if st.rag is not None and st.rag.error is None else None,
                tf_client,
                st.reports, st.skills,
                lambda: sid, process_event,
                max_tokens=planner_max_tokens or None,
                temperature=planner_temperature or None,
                top_p=planner_top_p or None,
                system_prompt_override=planner_prompt,
                tinyfish_api_key=cfg.tinyfish_api_key,
            )

        sp_cfg = subagent_cfgs.get("study_planner")
        sp_model = (sp_cfg.model if sp_cfg else "") or DEFAULT_MODEL
        sp_reasoning = sp_cfg.reasoning if sp_cfg else self.reasoning
        sp_max_steps = sp_cfg.max_steps if sp_cfg else STUDY_PLANNER_DEFAULT_STEPS
        sp_prompt = cfg.agent_overrides.get("study_planner") or None
        subagent_map["study_planner"] = study_planner_config(
            sp_model, sp_reasoning, sp_max_steps,
            st.reports, st.study_plans, st.skills, st.learner_state, st.pedagogy,
            lambda: sid, process_event,
            system_prompt_override=sp_prompt,
            rag_engine=st.rag if st.rag is not None and st.rag.error is None else None,
            tf_client=tf_client,
            llm_client=llm_client,
            tinyfish_api_key=cfg.tinyfish_api_key,
            suspended_subagents=st.suspended_subagents,
        )

        if self.agent_id == "maestro" and tf_client is not None:
            ev_cfg = subagent_cfgs.get("evaluator")
            ev_model = (ev_cfg.model if ev_cfg else "") or DEFAULT_MODEL
            ev_reasoning = ev_cfg.reasoning if ev_cfg else self.reasoning
            ev_max_steps = ev_cfg.max_steps if ev_cfg else EVALUATOR_MAX_STEPS
            ev_prompt = cfg.agent_overrides.get("evaluator") or None
            subagent_map["evaluator"] = evaluator_config(
                ev_model, ev_reasoning, ev_max_steps,
                llm_client,
                st.rag if st.rag is not None and st.rag.error is None else None,
                tf_client,
                st.reports, st.learner_state, lambda: sid, process_event,
                system_prompt_override=ev_prompt,
                tinyfish_api_key=cfg.tinyfish_api_key,
                suspended_subagents=st.suspended_subagents,
            )

        if self.agent_id == "maestro" and tf_client is not None:
            te_cfg = subagent_cfgs.get("maestro")
            te_model = (te_cfg.model if te_cfg else "") or DEFAULT_MODEL
            te_reasoning = te_cfg.reasoning if te_cfg else self.reasoning
            te_max_steps = te_cfg.max_steps if te_cfg else EVALUATOR_MAX_STEPS
            te_prompt = cfg.agent_overrides.get("maestro") or None
            doc_cfg = subagent_cfgs.get("documentalist")
            doc_model = (doc_cfg.model if doc_cfg else "") or DEFAULT_MODEL
            doc_reasoning = doc_cfg.reasoning if doc_cfg else self.reasoning
            doc_prompt = cfg.agent_overrides.get("documentalist") or None
            subagent_map["maestro"] = teacher_config(
                te_model, te_reasoning, te_max_steps,
                llm_client,
                st.rag if st.rag is not None and st.rag.error is None else None,
                tf_client,
                st.reports, st.skills, st.learner_state, st.pedagogy,
                lambda: sid, process_event,
                system_prompt_override=te_prompt,
                tinyfish_api_key=cfg.tinyfish_api_key,
                suspended_subagents=st.suspended_subagents,
            )

        if self.agent_id != "system_support":
            s_analyzer_cfg = subagent_cfgs.get("session_analyzer")
            s_analyzer_model = (s_analyzer_cfg.model if s_analyzer_cfg else "") or DEFAULT_MODEL
            s_analyzer_reasoning = s_analyzer_cfg.reasoning if s_analyzer_cfg else "disabled"
            subagent_map["session_analyzer"] = session_analyzer_config(
                model=s_analyzer_model,
                reasoning=s_analyzer_reasoning,
            )

        return subagent_map

    def _build_tool_registry(
        self, process_event, subagent_map, cfg, sid, llm_client, tf_client
    ) -> Registry:
        st = self.st
        registry = Registry()
        deploy_subagent_tool = DeploySubagent(
            llm_client=llm_client,
            reports=st.reports,
            subagents=subagent_map,
            session_id=lambda: sid,
            emit=process_event,
            rag_engine=st.rag if st.rag is not None and st.rag.error is None else None,
            tinyfish_api_key=cfg.tinyfish_api_key,
            suspended_subagents=st.suspended_subagents,
        )
        registry.register(deploy_subagent_tool)
        registry.register(CreateLearningSession(emit=process_event, skills=st.skills))

        if self.agent_id == "system_support":
            skill_planner_deployer = None
            if cfg.tinyfish_api_key and "skill_planner" in subagent_map:
                async def _skill_planner_deployer(query: str) -> str:
                    return await deploy_subagent_tool.execute(
                        json.dumps({"type": "skill_planner", "query": query})
                    )
                skill_planner_deployer = _skill_planner_deployer
            registry.register(
                FinishSetup(
                    emit=process_event,
                    store=st.store,
                    skill_planner_deployer=skill_planner_deployer,
                )
            )

        if self.agent_id == "maestro":
            registry.register(
                ApplyProfile(store=st.store, session_id=sid, emit=process_event)
            )

        return registry

    @staticmethod
    def _persist_partial(
        acc: dict[str, str],
        sa: SessionAgent,
        st,
        sid: str,
        llm_client,
        tf_client,
    ) -> None:
        content = acc["content"]
        reasoning_text = acc["reasoning"]
        assistant_row = None
        if content or reasoning_text or sa.live_reports:
            assistant_row = MessageRow(
                role="assistant",
                content=content,
                reasoning=reasoning_text,
                reports=json.dumps(sa.live_reports, ensure_ascii=False),
            )
            sa.messages.append(assistant_row)
        sa.live_content = ""
        sa.live_reasoning = ""
        sa.live_reports.clear()
        sa.tool_status = ""

        if len(st.suspended_subagents) > 20:
            st.suspended_subagents.clear()

        if assistant_row is not None and st.db is not None:
            try:
                st.messages.append(sid, assistant_row)
            except Exception as e:
                log.error("chat: append message (session %s): %s", sid, e)

        st.active_agents.pop(sid, None)
        sa.close()

        for client in (llm_client, tf_client):
            with contextlib.suppress(Exception):
                asyncio.get_running_loop().create_task(client.aclose())

