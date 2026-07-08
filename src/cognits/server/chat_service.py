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
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from cognits.agent.agent import Agent, AgentConfig
from cognits.agent.subagents import (
    directory_reader_config,
    documentalist_config,
    evaluator_config,
    researcher_config,
    session_analyzer_config,
    session_namer_config,
    skill_planner_config,
    study_planner_config,
    teacher_config,
)
from cognits.agent.tool_deploy import DeploySubagent
from cognits.agent.tool_ui import ApplyProfile, CreateLearningSession, FinishSetup, ListSkills, SearchSkills
from cognits.llm.types import ROLE_SYSTEM, ROLE_USER
from cognits.constants import (
    COMPACTION_PRESERVE_TURNS,
    COMPACTION_TRIGGER,
    DEFAULT_FLASH_MODEL,
    DEFAULT_MODEL,
    EVALUATOR_MAX_STEPS,
    MAX_SESSION_NAME_LENGTH,
    get_context_window,
    ORCHESTRATOR_MAX_STEPS,
    RESEARCHER_MAX_STEPS,
    SKILL_PLANNER_MAX_STEPS,
    SESSION_NAMER_MAX_TOKENS,
    SESSION_NAMER_TEMPERATURE,
    STUDY_PLANNER_DEFAULT_STEPS,
)
from cognits.llm.deepseek import DeepSeekClient
from cognits.llm.types import Message
from cognits.server.util import MONTHS, WEEKDAYS
from cognits.server.session_agent import SessionAgent
from cognits.storage.files import Config
from cognits.storage.models import MessageRow
from cognits.tinyfish import TinyfishClient
from cognits.tools import Registry

async def _run_session_namer(
    st,
    sa: SessionAgent,
    cfg: Config,
    sid: str,
    incoming: list[dict],
    tracer=None,
) -> None:
    """Fire-and-forget: generates a session name from the first user message."""
    logger = logging.getLogger("cognits.session_namer")
    try:
        user_msgs = [m for m in incoming if m.get("role") in ("user", "hidden_user")]
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
        ag = Agent(ag_cfg, llm_client, tracer=tracer)

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




# ---------------------------------------------------------------------------
# Helpers for orchestrator study plan push and maestro floor enforcement
# ---------------------------------------------------------------------------

from cognits.agent.tool_study_plan import classify_item as _classify_item


async def _fetch_plan_summary(st) -> tuple:
    """Fetch the active study plan with classified items for orchestrator injection.

    All DB I/O is inside asyncio.to_thread per AGENTS.md invariant.
    Returns (plan, classified_items, summary_string).
    """
    from datetime import datetime, timezone

    def _fetch():
        plans = st.study_plans
        if plans is None:
            return None, [], ""

        plan = plans.get_active()
        if plan is None:
            return None, [], ""

        items = plans.get_items(plan.id)
        if not items:
            return plan, [], "empty plan"

        states = st.learner_state.get_all()

        # Pre-fetch skill names inside the to_thread closure
        classified = []
        total_new = 0
        total_review = 0
        total_estimated_min = 0
        now = datetime.now(timezone.utc)

        for item in items:
            sk = st.skills.get(item.skill_id)
            name = sk.name if sk else item.skill_id
            item_type = _classify_item(item.skill_id, states, now)
            if item_type == "skip":
                continue
            duration = item.estimated_duration_min or 0

            classified.append({
                "skill_id": item.skill_id,
                "name": name,
                "type": item_type,
                "order_index": item.order_index,
                "estimated_duration_min": duration,
                "mode": item.mode,
            })

            if item_type == "review":
                total_review += 1
            else:
                total_new += 1
            total_estimated_min += duration

        # Build summary string
        parts = []
        if total_new:
            parts.append(f"{total_new} new skill{'s' if total_new != 1 else ''}")
        if total_review:
            parts.append(f"{total_review} review skill{'s' if total_review != 1 else ''}")
        if total_estimated_min:
            parts.append(f"~{total_estimated_min} min total")
        summary = " + ".join(parts) if parts else "empty plan"

        return plan, classified, summary

    return await asyncio.to_thread(_fetch)


def _format_plan_for_prompt(items, plan, st) -> str:
    """Format the study plan as a Markdown section for the orchestrator's system prompt."""
    if not items:
        return ""

    lines = [
        "## Current Study Plan (deterministic \u2014 follow this priority)",
        "",
        f"**Goal:** {plan.goal or '(no goal set)'}",
    ]

    new_count = sum(1 for i in items if i.get("type") == "new")
    review_count = sum(1 for i in items if i.get("type") == "review")
    total_min = sum(i.get("estimated_duration_min", 0) for i in items)

    summary_parts = []
    if new_count:
        summary_parts.append(f"{new_count} new skill{'s' if new_count != 1 else ''}")
    if review_count:
        summary_parts.append(f"{review_count} review skill{'s' if review_count != 1 else ''}")
    if total_min:
        summary_parts.append(f"~{total_min} min total")

    lines.append(
        f"**Summary:** {', '.join(summary_parts)}"
        if summary_parts
        else "**Summary:** empty plan"
    )
    lines.append("")
    lines.append("**Next items (by priority):**")

    for i, item in enumerate(items, 1):
        type_label = "[Nuevo]" if item.get("type") == "new" else "[Repaso]"
        name = item.get("name", item.get("skill_id", "?"))
        sid = item.get("skill_id", "?")
        mode = item.get("mode", "?")
        duration = item.get("estimated_duration_min", 0)
        dur_str = f" \u2014 ~{duration} min" if duration else ""

        lines.append(f"{i}. {type_label} {name} ({sid}) \u2014 stage: {mode}{dur_str}")

    lines.append("")
    lines.append(
        "Follow this priority order. Do not re-derive the frontier from the "
        "skill tree summary."
    )

    return "\n".join(lines)


def _format_floor_report(floor_data: dict) -> str:
    """Format the floor check result as a Markdown section for the maestro's system prompt."""
    branch_root = floor_data.get("branch_root", "?")
    floor_confirmed = floor_data.get("floor_confirmed", True)
    prereqs_checked = floor_data.get("prereqs_checked", [])
    expanded = floor_data.get("expanded_skills", [])
    pruned = floor_data.get("pruned_skills", [])

    lines = [
        "## Floor Verification (system-enforced)",
        "",
        "The learner's floor has been re-verified before starting this branch.",
        "",
        f"**Branch root:** {branch_root}",
        f"**Floor confirmed:** {str(floor_confirmed).lower()}",
        "",
    ]

    if prereqs_checked:
        lines.append("**Prerequisites checked:**")
        for pc in prereqs_checked:
            name = pc.get("name", "") or pc.get("skill_id", "?")
            sid = pc.get("skill_id", "?")
            mastery = pc.get("mastery", "?")
            confidence = pc.get("confidence", 0)
            lines.append(f"- {name} ({sid}): {mastery} (confidence {confidence}%)")
        lines.append("")

    if expanded:
        lines.append(
            "**Expanded skills (prerequisites not mastered \u2014 teach these first):**"
        )
        for es in expanded:
            name = es.get("name", es.get("skill_id", "?"))
            sid = es.get("skill_id", "?")
            lines.append(f"- {name} ({sid})")
        lines.append("")

    if pruned:
        lines.append("**Pruned skills (mastered \u2014 removed over-decomposition):**")
        for ps in pruned:
            sid = ps.get("skill_id", "?")
            lines.append(f"- {sid}")
        lines.append("")

    if expanded:
        lines.append(
            "If expanded skills exist, teach those prerequisites first before "
            "the branch root."
        )

    return "\n".join(lines)



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
        skill_id: str = "",
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
        self.skill_id = skill_id

    async def run_agent(self) -> None:
        st = self.st
        sa = self.sa
        sid = self.sid
        cfg = self.cfg
        acc: dict[str, str] = {"content": "", "reasoning": ""}

        from cognits.agent.tracer import Tracer
        tracer = Tracer(sid)

        llm_client = DeepSeekClient(cfg.llm_api_key)
        tf_client = TinyfishClient(cfg.tinyfish_api_key)

        try:
            # Reset tool_log each run (SessionAgent may be reused across turns)
            sa.tool_log = []

            if sum(1 for m in self.incoming if m.get("role") in ("user", "hidden_user")) == 1:
                asyncio.create_task(
                    _run_session_namer(st, sa, cfg, sid, self.incoming, tracer=tracer)
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
                process_event, subagent_map, cfg, sid, llm_client, tf_client, tracer=tracer
            )

            # --- pedagogy engine (maestro only, external stage management) ---
            pedagogy_engine = None
            previous_p_mastery = None
            if self.agent_id == "maestro" and self.skill_id:
                from cognits.learner.pedagogy_engine import PedagogyEngine
                try:
                    ls = await asyncio.to_thread(st.learner_state.get, self.skill_id)
                except Exception:
                    ls = None
                engine = PedagogyEngine()
                if ls is not None and ls.scaffolding_level > 0:
                    engine.load_from_scaffolding_level(ls.scaffolding_level)
                previous_p_mastery = ls.p_mastery if ls is not None else None
                self.system_prompt += "\n\n" + engine.prompt_context()
                pedagogy_engine = engine

            # --- study plan injection (orchestrator only, push not pull) ---
            if self.agent_id == "orchestrator":
                try:
                    plan, items, plan_summary = await _fetch_plan_summary(st)
                    if plan is not None and items:
                        plan_text = _format_plan_for_prompt(items, plan, st)
                        if plan_text:
                            self.system_prompt += "\n\n" + plan_text
                except Exception as e:
                    log.warning("orchestrator: plan injection failed: %s", e)

            # --- system-enforced floor verification (maestro only) ---
            if self.agent_id == "maestro" and self.skill_id:
                try:
                    from cognits.agent.tool_floor import CheckBranchFloor
                    floor_tool = CheckBranchFloor(
                        skills=st.skills,
                        learner_state=st.learner_state,
                        messages=st.messages,
                        llm_client=llm_client,
                        rag_engine=st.rag_or_none,
                        tf_client=tf_client,
                        reports=st.reports,
                        assessment=st.assessment,
                        session_id=lambda: sid,
                        emit=process_event,
                        tinyfish_api_key=cfg.tinyfish_api_key,
                    )
                    floor_result_raw = await floor_tool.execute(
                        json.dumps({"skill_id": self.skill_id})
                    )
                    floor_data = json.loads(floor_result_raw)
                    if not floor_data.get("error"):
                        floor_confirmed = floor_data.get("floor_confirmed", True)
                        expanded = floor_data.get("expanded_skills", [])
                        pruned = floor_data.get("pruned_skills", [])
                        if expanded or pruned or not floor_confirmed:
                            floor_text = _format_floor_report(floor_data)
                            self.system_prompt += "\n\n" + floor_text
                except Exception as e:
                    log.warning("maestro: floor verification failed: %s", e)

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
                tracer,
            )

            # --- context compaction ---
            if COMPACTION_TRIGGER > 0:
                from cognits.agent.token_counter import TokenCounter
                counter = TokenCounter()
                token_count = counter.count_messages(self.llm_messages)
                if token_count > get_context_window(self.model) * COMPACTION_TRIGGER:
                    self.llm_messages = self._compact(self.llm_messages, counter, llm_client)

            # --- inject pending critique from prior turn (maestro only) ---
            if self.agent_id == "maestro":
                pending = st.pending_critiques.pop(sid, None)
                if pending:
                    self.llm_messages.append(Message(role="system", content=pending))

            try:
                mastery_updated = {"val": False}

                def _orchestrator_emit(ev: dict) -> None:
                    if ev.get("type") == "usage" and isinstance(ev.get("data"), dict):
                        ev["data"]["source"] = "orchestrator"
                    if ev.get("type") == "tool_end" and isinstance(ev.get("data"), dict):
                        if ev["data"].get("tool") == "update_mastery":
                            mastery_updated["val"] = True
                    process_event(ev)

                await ag.run(self.llm_messages, _orchestrator_emit)

                # --- background reflection (maestro only, post-send) ---
                if self.agent_id == "maestro" and acc["content"] and getattr(cfg, "reflection_enabled", True):
                    _draft = acc["content"]
                    _subagent_map = subagent_map
                    _llm_client = llm_client
                    _sid = sid
                    _tracer = tracer
                    asyncio.create_task(self._reflect_async(
                        _draft, _subagent_map, _llm_client, _sid, tracer=_tracer
                    ))

            except asyncio.CancelledError:
                log.info("chat: agent run cancelled (session %s)", sid)
            except Exception as e:
                log.error("chat: agent run (session %s): %s", sid, e)
                sa.publish({"type": "error", "data": str(e)})

            # --- post-run pedagogy transition ---
            if pedagogy_engine is not None:
                pedagogy_engine.record_interaction()
                try:
                    ls = await asyncio.to_thread(st.learner_state.get, self.skill_id)
                except Exception:
                    ls = None
                p_mastery = ls.p_mastery if ls is not None else 0.0
                did_advance = False
                if pedagogy_engine.should_advance(p_mastery):
                    new_stage = pedagogy_engine.advance()
                    if new_stage is not None:
                        did_advance = True
                        if ls is not None:
                            ls.scaffolding_level = pedagogy_engine.to_scaffolding_level()
                            try:
                                await asyncio.to_thread(st.learner_state.upsert, ls)
                            except Exception as e2:
                                log.error("chat: pedagogy upsert (session %s): %s", sid, e2)
                        sa.publish({
                            "type": "ui_action",
                            "data": {
                                "action": "stage_advanced",
                                "stage": new_stage.value,
                            },
                        })

                # --- retreat on mastery drop (regress one stage) ---
                if not did_advance and previous_p_mastery is not None:
                    from cognits.learner.pedagogy_engine import RETREAT_MASTERY_DROP
                    drop = previous_p_mastery - p_mastery
                    if drop >= RETREAT_MASTERY_DROP:
                        new_stage = pedagogy_engine.retreat()
                        if new_stage is not None:
                            if ls is not None:
                                ls.scaffolding_level = pedagogy_engine.to_scaffolding_level()
                                try:
                                    await asyncio.to_thread(st.learner_state.upsert, ls)
                                except Exception as e3:
                                    log.error("chat: pedagogy retreat upsert (session %s): %s", sid, e3)
                            sa.publish({
                                "type": "ui_action",
                                "data": {
                                    "action": "pedagogy_retreat",
                                    "stage": new_stage,
                                },
                            })

            # --- auto-regen study plan after mastery update (maestro only) ---
            if (self.agent_id == "maestro" and mastery_updated["val"]
                    and getattr(cfg, "study_plan_auto_regen", True)):
                _sid = sid
                _sa = sa
                asyncio.create_task(self._regen_study_plan_async(_sid, _sa))

        finally:
            asyncio.get_running_loop().create_task(tracer.flush())
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
                eid = data.get("id")
                agent = data.get("agent", "")
                parent_id = data.get("parentId")
                parent_agent = data.get("parentAgent")
                message = data.get("message", "")
                favicons = data.get("favicons")
                if eid is not None:
                    has_favicons_key = "favicons" in data
                    def update():
                        for entry in sa.tool_log:
                            if entry["id"] == eid:
                                if message:
                                    entry["message"] = message
                                if agent:
                                    entry["agent"] = agent
                                if parent_id is not None:
                                    entry["parentId"] = parent_id
                                if parent_agent is not None:
                                    entry["parentAgent"] = parent_agent
                                if has_favicons_key:
                                    entry["favicons"] = list(favicons) if isinstance(favicons, list) else []
                                break
                        else:
                            sa.tool_log.append({
                                "id": eid,
                                "agent": agent,
                                "parentId": parent_id,
                                "parentAgent": parent_agent,
                                "message": message,
                                "favicons": list(favicons) if isinstance(favicons, list) else [],
                                "done": False,
                            })
                        if message:
                            sa.tool_status = message
                        if has_favicons_key:
                            sa.tool_favicons = list(favicons) if isinstance(favicons, list) else []
                else:
                    has_favicons_key = "favicons" in data
                    def update():
                        if message and isinstance(message, str):
                            sa.tool_status = message
                        if has_favicons_key:
                            sa.tool_favicons = list(favicons) if isinstance(favicons, list) else []
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
                    if isinstance(data, dict):
                        eid = data.get("id")
                        internal = bool(data.get("internal"))
                        rid = data.get("reportId")
                        rt = data.get("title")
                        if eid is not None:
                            for entry in sa.tool_log:
                                if entry["id"] == eid:
                                    entry["done"] = True
                                    break
                            else:
                                sa.tool_log.append({
                                    "id": eid,
                                    "agent": data.get("agent", ""),
                                    "parentId": data.get("parentId"),
                                    "parentAgent": data.get("parentAgent"),
                                    "message": "",
                                    "favicons": [],
                                    "done": True,
                                })
                        if not internal and isinstance(rid, str) and isinstance(rt, str):
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
                rag_engine=st.rag_or_none,
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
                planner_max_steps = SKILL_PLANNER_MAX_STEPS
            planner_max_tokens = planner_cfg.max_tokens if planner_cfg else 0
            planner_temperature = planner_cfg.temperature if planner_cfg else 0.0
            planner_top_p = planner_cfg.top_p if planner_cfg else 0.0
            planner_prompt = cfg.agent_overrides.get("skill_planner") or None
            subagent_map["skill_planner"] = skill_planner_config(
                planner_model, planner_reasoning, planner_max_steps,
                llm_client,
                st.rag_or_none,
                tf_client,
                st.reports, st.skills, st.assessment, st.learner_state,
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
            rag_engine=st.rag_or_none,
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
                st.rag_or_none,
                tf_client,
                st.reports, st.skills, st.assessment, st.learner_state, lambda: sid, process_event,
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
                st.rag_or_none,
                tf_client,
                st.reports, st.skills, st.assessment, st.learner_state, st.messages,
                session_id=lambda: sid, emit=process_event,
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
        self, process_event, subagent_map, cfg, sid, llm_client, tf_client, tracer=None
    ) -> Registry:
        st = self.st
        registry = Registry()
        deploy_subagent_tool = DeploySubagent(
            llm_client=llm_client,
            reports=st.reports,
            subagents=subagent_map,
            session_id=lambda: sid,
            emit=process_event,
            rag_engine=st.rag_or_none,
            tinyfish_api_key=cfg.tinyfish_api_key,
            suspended_subagents=st.suspended_subagents,
            tracer=tracer,
        )
        registry.register(deploy_subagent_tool)
        registry.register(CreateLearningSession(emit=process_event, skills=st.skills, session_id=lambda: sid, store=st.store))
        registry.register(ListSkills(skills=st.skills))
        registry.register(SearchSkills(skills=st.skills))

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
            from cognits.agent.tool_floor import CheckBranchFloor
            from cognits.agent.tool_refocus import RefocusTree
            registry.register(
                CheckBranchFloor(
                    skills=st.skills,
                    learner_state=st.learner_state,
                    messages=st.messages,
                    llm_client=llm_client,
                    rag_engine=st.rag_or_none,
                    tf_client=tf_client,
                    reports=st.reports,
                    assessment=st.assessment,
                    session_id=lambda: sid,
                    emit=process_event,
                    tinyfish_api_key=cfg.tinyfish_api_key,
                )
            )
            registry.register(
                RefocusTree(
                    skills=st.skills,
                    learner_state=st.learner_state,
                    assessment=st.assessment,
                    llm_client=llm_client,
                    rag_engine=st.rag_or_none,
                    tf_client=tf_client,
                    reports=st.reports,
                    session_id=lambda: sid,
                    emit=process_event,
                    tinyfish_api_key=cfg.tinyfish_api_key,
                )
            )

        if self.agent_id in ("orchestrator", "maestro"):
            from cognits.agent.tool_study_plan import GetCurrentStudyPlan
            registry.register(
                GetCurrentStudyPlan(
                    study_plans=st.study_plans,
                    skills=st.skills,
                    learner_state=st.learner_state,
                    session_id=lambda: sid,
                    emit=process_event,
                )
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

    def _compact(self, messages: list[Message], counter, llm_client) -> list[Message]:
        """Compress older turns into an anchored summary using observation masking.

        Preserves: system prompt, last N user/assistant turns, and tool-call
        result pairs (the factual record). Compresses older turns into a
        structured summary: learning objective, knowledge gaps, Socratic
        approach, next step."""
        preserve_count = COMPACTION_PRESERVE_TURNS
        system_msg = messages[0] if messages and messages[0].role == "system" else None
        rest = messages[1:] if system_msg else messages

        # Walk backward to find the last N user/assistant turns
        compact_start = 0
        turns_found = 0
        for i in range(len(rest) - 1, -1, -1):
            if rest[i].role in ("user", "assistant"):
                turns_found += 1
                if turns_found >= preserve_count:
                    compact_start = i
                    break
            elif rest[i].role == "tool":
                # preserve tool results near their parent assistant
                pass
            else:
                compact_start = max(0, i)

        to_compress = rest[:compact_start]
        to_keep = rest[compact_start:]

        if not to_compress:
            return messages

        # Build a compact summary of the compressed turns
        # (Observation masking — keep reasoning, collapse old tool outputs)
        summary_parts = []
        current_objective = ""
        for m in to_compress:
            if m.role == "user":
                summary_parts.append(f"[User asked: {m.content[:200]}]")
            elif m.role == "assistant" and m.content:
                summary_parts.append(f"[Tutor: {m.content[:200]}]")
            elif m.role == "tool":
                # mask the output, preserve the fact it was called
                name = getattr(m, 'name', '') or ''
                summary_parts.append(f"[Tool '{name}': result saved]")

        summary = " ".join(summary_parts)
        if not summary:
            return messages

        compact_msg = Message(
            role="system",
            content=f"[COMPACTED TURNS {compact_start+1}-{len(messages)}]\n\n"
                     f"The following is a compressed summary of the conversation "
                     f"before turn {compact_start+1}. Preserve this context:\n\n"
                     f"{summary}\n\n"
                     f"Continue the Socratic dialogue as if you remember all past details.",
        )
        result = [compact_msg] + to_keep
        if system_msg:
            result.insert(0, system_msg)
        return result

    async def _reflect_async(self, draft, subagent_map, llm_client, sid, tracer=None):
        """Background post-send review: deploy evaluator once in critique mode.

        Non-blocking — runs after the turn is delivered. If violations are
        found, store the critique for the next maestro turn. No in-place
        revision."""
        from cognits.agent.tool_deploy import DeploySubagent

        try:
            evaluator_cfg = subagent_map.get("evaluator")
            if evaluator_cfg is None:
                return

            def _noop_emit(ev: dict) -> None:
                return  # turn is over; evaluator is invisible to the user

            deploy = DeploySubagent(
                llm_client=llm_client,
                reports=self.st.reports,
                subagents={"evaluator": evaluator_cfg},
                session_id=lambda: sid,
                emit=_noop_emit,
                rag_engine=None,
                tinyfish_api_key=None,
                suspended_subagents=self.st.suspended_subagents,
                tracer=tracer,
            )
            result = await deploy.execute(json.dumps({
                "type": "evaluator",
                "query": json.dumps({
                    "mode": "critique",
                    "teacher_draft": draft,
                }),
            }))
            critique = json.loads(result)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.warning("reflect_async (session %s): evaluator failed: %s", sid, e)
            return

        if not isinstance(critique, dict):
            return

        violations = critique.get("socratic_violations", []) or []
        verdict = critique.get("verdict", "pass")
        if verdict == "pass" and not violations:
            return  # clean — nothing to flag

        critique_text = json.dumps(critique, ensure_ascii=False, indent=2)
        feedback = (
            "FEEDBACK FROM AN INDEPENDENT REVIEWER OF YOUR PRIOR RESPONSE:\n\n"
            f"{critique_text}\n\n"
            "The reviewer flagged the issues above in your LAST response. "
            "In your NEXT response, address them while maintaining your "
            "Socratic approach. Do NOT mention this feedback to the learner."
        )
        self.st.pending_critiques[sid] = feedback
        log.info("reflect_async (session %s): flagged %d violation(s) for next turn",
                 sid, len(violations) if isinstance(violations, list) else 0)

    async def _regen_study_plan_async(self, session_id, sa):
        """Fire-and-forget: regenerate study plan after mastery updates.

        Non-blocking — runs after the turn is delivered. If any skill
        in the active plan has crossed MASTERY_THRESHOLD, regenerate
        the plan and emit a study_plan_updated SSE event.

        Mirrors _reflect_async pattern — catches all exceptions,
        never touches SessionAgent in finally.
        """
        try:
            st = self.st
            plans = st.study_plans
            if plans is None:
                return

            active = await asyncio.to_thread(plans.get_active)
            if active is None:
                return

            items = await asyncio.to_thread(plans.get_items, active.id)
            if not items:
                return

            skills = await asyncio.to_thread(st.skills.list_active)
            tree_data = await asyncio.to_thread(st.skills.get_tree)
            edges_data = tree_data.get("edges", [])
            from cognits.storage.models import SkillPrereq
            edges = [SkillPrereq(**e) for e in edges_data]

            states: dict = {}
            for s in skills:  # all skills (not just plan items), so compute_frontier sees all mastered prereqs
                state = await asyncio.to_thread(st.learner_state.get, s.id)
                if state is not None:
                    states[s.id] = state

            if not states:
                return

            from cognits.learner.planner import generate_plan
            from cognits.constants import MASTERY_THRESHOLD

            # Check if any skill crossed the mastery threshold
            any_mastered = any(
                s.p_mastery >= MASTERY_THRESHOLD for s in states.values()
            )
            if not any_mastered:
                return

            # Generate new plan
            new_items = await asyncio.to_thread(
                generate_plan,
                skills, edges, states,
                active.goal or "",
                priorities=None,
                max_items=len(items),
            )
            if not new_items:
                return

            # Supersede old plan + create new
            await asyncio.to_thread(plans.supersede, active.id)

            new_plan_id = await asyncio.to_thread(
                plans.create,
                active.tree_version,
                active.goal or "",
                session_id,
            )
            await asyncio.to_thread(plans.replace_items, new_plan_id, new_items)

            # Emit SSE if sa is alive (mirrors _reflect_async defensiveness)
            try:
                plan_summary = {
                    "plan_id": new_plan_id,
                    "goal": active.goal,
                    "skill_ids": [item.skill_id for item in new_items],
                    "item_count": len(new_items),
                }
                sa.publish({
                    "type": "study_plan_updated",
                    "data": plan_summary,
                })
            except Exception:
                pass  # sa may be torn down by now

            log.info("regen_study_plan (session %s): regenerated plan %s with %d items",
                     session_id, new_plan_id, len(new_items))
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.warning("regen_study_plan_async (session %s): %s", session_id, e)


