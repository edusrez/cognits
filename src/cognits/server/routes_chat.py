"""Port of internal/server/chat.go: POST /api/chat and DELETE .../agent.

The agent run is an asyncio.Task; its finally block is 100% synchronous
(partial-response persistence included) so a second cancellation cannot
skip the cleanup at an await point.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, Request, Response

from cognits.agent.agent import Agent, AgentConfig
from cognits.agent.prompts import DEFAULT_AGENT_ID, default_agent_prompt
from cognits.agent.subagents import (
    directory_reader_config,
    documentalist_config,
    evaluator_config,
    researcher_config,
    session_namer_config,
    skill_planner_config,
    study_planner_config,
    teacher_config,
)
from cognits.agent.prompts import (
    TEACHER_SYSTEM_PROMPT,
    default_agent_prompt,
)
from cognits.agent.tool_deploy import DeploySubagent
from cognits.constants import (
    AGENT_LABELS,
    DEFAULT_FLASH_MODEL,
    DEFAULT_MODEL,
    ORCHESTRATOR_MAX_STEPS,
    RESEARCHER_MAX_STEPS,
)
from cognits.llm.deepseek import DeepSeekClient
from cognits.llm.types import ROLE_SYSTEM, ROLE_USER, Message
from cognits.server.session_agent import SessionAgent
from cognits.server.util import text_error
from cognits.storage.models import MessageRow
from cognits.storage.files import Config, StudentProfile
from cognits.tinyfish import TinyfishClient
from cognits.tools import Registry

log = logging.getLogger("cognits.chat")


def _build_profile_context(profile: StudentProfile) -> str:
    d = profile.declared
    parts = ["\n\n## Learner Profile"]
    if d.get("background"):
        parts.append(f"Background: {d['background']}")
    if d.get("goals"):
        goals = d["goals"]
        if isinstance(goals, list):
            parts.append("Goals: " + ", ".join(goals))
        else:
            parts.append(f"Goals: {goals}")
    if d.get("self_assessed"):
        sa = d["self_assessed"]
        if isinstance(sa, dict):
            items = [f"{k}: {v}" for k, v in sa.items()]
            parts.append("Self-assessed skills: " + "; ".join(items))
    prefs = d.get("preferences", {})
    if isinstance(prefs, dict):
        pref_items = []
        if prefs.get("style"):
            pref_items.append(f"style={prefs['style']}")
        if prefs.get("pace"):
            pref_items.append(f"pace={prefs['pace']}")
        if prefs.get("language"):
            pref_items.append(f"language={prefs['language']}")
        if pref_items:
            parts.append("Preferences: " + ", ".join(pref_items))

    inf = profile.inferred
    if inf and isinstance(inf, dict):
        inf_parts = []
        for key, value in inf.items():
            if isinstance(value, dict):
                v = value.get("value") or value
                if v and not isinstance(v, dict):
                    inf_parts.append(f"{key}: {v}")
            elif value and not isinstance(value, dict):
                inf_parts.append(f"{key}: {value}")
        if inf_parts:
            parts.append("\n## Inferred Profile")
            parts.extend(inf_parts)

    return "\n".join(parts)


def _build_skills_summary(store, tree: dict) -> str:
    """Build a compact skill tree summary for the planning mode prompt.

    Format per skill::

        • SkillName (domain) [status, p=0.78] — prereqs: A, B

    Uses ``get_all_learner_states()`` for a single SELECT rather than N
    per-skill calls.
    """
    skills = tree.get("skills", [])
    if not skills:
        return ""

    edges = tree.get("edges", [])
    # Build prereq lookup: skill_id -> list of prereq skill names.
    prereq_names: dict[str, list[str]] = {}
    id_to_name: dict[str, str] = {s["id"]: s["name"] for s in skills}
    for e in edges:
        etype = e.get("edgeType", "")
        if etype not in ("prereq", "soft_prereq"):
            continue
        pid = e["prereqId"]
        pname = id_to_name.get(pid, pid)
        prereq_names.setdefault(e["skillId"], []).append(pname)

    all_states = (store.get_all_learner_states if hasattr(store, "get_all_learner_states") else store.get_all)()

    lines: list[str] = []
    for s in skills:
        sid = s["id"]
        name = s.get("name", "")
        domain = s.get("domain", "")
        st = all_states.get(sid)
        if st:
            p = st.p_mastery
            status = st.status_enum
        else:
            p = 0.0
            status = "not_seen"

        prereqs = prereq_names.get(sid, [])
        prereqs_str = ", ".join(prereqs) if prereqs else "(none)"

        lines.append(
            f"• {name} ({domain}) [{status}, p={p:.2f}] — prereqs: {prereqs_str}"
        )

    return "\n".join(lines)


def _build_teacher_system_prompt(
    skill_id: str, store=None, learner_state=None, pedagogy=None, profile_ctx: str = ""
) -> str:
    """Assemble the 5-layer Teacher system prompt by fetching the skill,
    learner state, and pedagogical plan from the DB and concatenating them
    with the static TEACHER_SYSTEM_PROMPT."""
    prompt = TEACHER_SYSTEM_PROMPT

    # Legacy: store is a ReportStore or compat object with all methods.
    # New: skills, learner_state, pedagogy are individual repos.
    _skills = store if store is not None else None  # will determine later
    _ls = learner_state if learner_state is not None else store
    _ped = pedagogy if pedagogy is not None else store

    if skill_id:
        skill = _skills.get_skill(skill_id) if _skills else None
        if skill:
            prompt += "\n\n## Skill\n\n"
            prompt += f"- Name: {skill.name}\n"
            prompt += f"- ID: {skill.id}\n"
            prompt += f"- Domain: {skill.domain}\n"
            prompt += f"- Description: {skill.description}\n"
            if skill.bloom_level:
                prompt += f"- Bloom level: {skill.bloom_level}\n"

            state = _ls.get_learner_state(skill_id) if _ls else None
            if state:
                prompt += "\n## Learner State\n\n"
                prompt += f"- Status: {state.status_enum}\n"
                prompt += f"- p_mastery (BKT): {state.p_mastery:.2f}\n"
                prompt += f"- Sessions completed: {state.reps}\n"
                if state.next_review:
                    prompt += f"- FSRS next review: {state.next_review}\n"
            else:
                prompt += "\n## Learner State\n\n(No learner state yet)\n"

            plan = _ped.get_pedagogical_plan(skill_id) if _ped else None
            if plan:
                prompt += "\n## Pedagogical Plan\n\n" + plan
            else:
                prompt += (
                    "\n## Pedagogical Plan\n\n"
                    "(No pedagogical plan available yet. Teach from your own "
                    "knowledge but follow a stage-based progression: activate "
                    "prior knowledge → introduce concept → guided practice → "
                    "assessment → wrap-up.)\n"
                )

    if profile_ctx:
        prompt += "\n## Learner Profile\n\n" + profile_ctx

    return prompt




# Explicit lists instead of strftime %A/%B: those are locale-dependent.
MONTHS = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]
WEEKDAYS = [
    "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday",
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
    """Separates what the LLM sees from what gets persisted: the history is
    stored as it arrived and only the last user message carries a date stamp,
    so DeepSeek's prefix cache is not invalidated on every turn."""
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
        if m.get("role") in ("user", "hidden_user"):
            last_user_idx = i

    now = datetime.now().astimezone()
    tz = now.strftime("%Z") or now.strftime("%z")
    date_str = (
        f"{WEEKDAYS[now.weekday()]}, {now.day} {MONTHS[now.month - 1]} "
        f"{now.year}, {now.strftime('%H:%M')} {tz}"
    )

    storage_messages: list[MessageRow] = []
    for i, m in enumerate(incoming):
        role = m.get("role", "")
        if role == "hidden_user":
            content = m.get("content") or ""
            if i == last_user_idx:
                content = f"[{date_str}]\n{content.strip()}"
            llm_messages.append(Message(role="user", content=content))
            continue
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
                reports=json.dumps(m.get("reports") or [], ensure_ascii=False),
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

        # Config resolution: session → global → default.
        model = cfg.llm_model
        reasoning = cfg.llm_reasoning
        agent_id = cfg.llm_agent_id
        if st.db is not None:
            try:
                sess_cfg = await asyncio.to_thread(
                    st.session_config.load, sid
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

        # Inject learner profile into system prompt if available.
        if st.store is not None:
            try:
                profile = await asyncio.to_thread(st.store.load_profile)
                if profile.declared:
                    system_prompt += _build_profile_context(profile)
                else:
                    # Use the System Support agent for first-time setup / onboarding.
                    agent_id = "system_support"
                    system_prompt = default_agent_prompt("system_support")
            except Exception:
                pass

        # Inject compact skill tree context when in planning mode.
        if st.db is not None:
            is_planning = any(
                m.get("role") == "hidden_user"
                and "planning" in (m.get("content") or "").lower()
                for m in incoming
            )
            if is_planning:
                try:
                    tree = await asyncio.to_thread(st.skills.get_tree)
                    if tree.get("skills"):
                        summary = await asyncio.to_thread(
                            _build_skills_summary, st.learner_state, tree
                        )
                        if summary:
                            system_prompt += "\n\n## Skill Tree Context\n\n" + summary
                except Exception:
                    pass

        # Build dynamic Teacher system prompt when in a learning session.
        if agent_id == "maestro" and sess_cfg is not None and sess_cfg.skill_id:
            try:
                profile = (await asyncio.to_thread(st.store.load_profile)) if st.store else None
                profile_ctx = _build_profile_context(profile) if profile and profile.declared else ""
                teacher_prompt = await asyncio.to_thread(
                    _build_teacher_system_prompt, sess_cfg.skill_id,
                    st.skills, st.learner_state, st.pedagogy, profile_ctx,
                )
                if teacher_prompt:
                    system_prompt = teacher_prompt
            except Exception:
                pass

        llm_messages, storage_messages = build_chat_messages(cfg, incoming)

        # 409 check + registration with no await in between: atomic on the loop.
        if sid in st.active_agents:
            return text_error("agent already running", 409)
        sa = SessionAgent(sid, storage_messages)
        st.active_agents[sid] = sa
        sa.task = asyncio.create_task(
            _run_agent(st, sa, cfg, sid, model, reasoning, system_prompt, llm_messages, incoming, agent_id)
        )

        return Response(status_code=202)

    @app.delete("/api/sessions/{session_id}/agent")
    async def cancel_agent(session_id: str):
        sa = st.active_agents.get(session_id)
        # Cleanup of active_agents is always done by the run's finally;
        # removing here would allow a second concurrent run to start.
        if sa is not None and sa.task is not None:
            sa.task.cancel()
        return Response(status_code=204)


async def _run_session_namer(
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
            max_tokens=20,
            temperature=0.3,
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
        if len(name) > 80:
            name = name[:77] + "..."

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


async def _run_agent(
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
) -> None:
    acc = {"content": "", "reasoning": ""}
    llm_client = DeepSeekClient(cfg.llm_api_key)
    tf_client = TinyfishClient(cfg.tinyfish_api_key)

    try:
        # Session Analyzer: fire-and-forget on the first user message.
        if sum(1 for m in incoming if m.get("role") == "user") == 1:
            asyncio.create_task(
                _run_session_namer(st, sa, cfg, sid, incoming)
            )

        # The server is the source of truth: it stores history + new message
        # right at the start. Here and not in the handler: the POST responds
        # immediately even if SQLite is busy, and immediate subscribers read
        # the in-memory sa.messages snapshot, not the DB.
        if st.db is not None:
            try:
                await asyncio.to_thread(st.messages.save, sid, sa.messages)
            except Exception as e:
                log.error("chat: save messages (session %s): %s", sid, e)

        # State update and fan-out go together in sa.publish so subscription
        # snapshots neither duplicate nor lose events. The update closures
        # run inside publish (synchronous section).
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
                        # "Thinking..." and "Writing..." clear favicons but
                        # only update the visible status when no icons are
                        # still animating on the frontend.
                        if msg.endswith("Thinking...") or msg.endswith("Writing..."):
                            is_clearing = True
                            data["favicons"] = []
                            if len(sa.tool_favicons) == 0:
                                data["message"] = status
                                is_action = True
                            else:
                                data["message"] = sa.tool_status
                        # else: keep the previous status visible
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
                doc_model,
                doc_reasoning,
                doc_max_steps,
                llm_client,
                st.rag,
                tf_client,
                st.reports,
                lambda: sid,
                process_event,
                max_tokens=doc_max_tokens or None,
                temperature=doc_temperature or None,
                top_p=doc_top_p or None,
                system_prompt_override=doc_prompt,
            )

        # Skill Planner: builds the learner's skill tree by iterating with
        # web_researcher. Requires TinyFish (the planner descends recursively
        # into prerequisites via web research); if no key is configured we
        # simply don't expose the subagent — the user can build the tree
        # later from the Settings panel after configuring one.
        if cfg.tinyfish_api_key:
            planner_cfg = subagent_cfgs.get("skill_planner")
            planner_model = (planner_cfg.model if planner_cfg else "") or DEFAULT_MODEL
            planner_reasoning = planner_cfg.reasoning if planner_cfg else "max"
            planner_max_steps = planner_cfg.max_steps if planner_cfg else 0
            if planner_max_steps <= 0:
                planner_max_steps = ORCHESTRATOR_MAX_STEPS  # 999
            planner_max_tokens = planner_cfg.max_tokens if planner_cfg else 0
            planner_temperature = planner_cfg.temperature if planner_cfg else 0.0
            planner_top_p = planner_cfg.top_p if planner_cfg else 0.0
            planner_prompt = cfg.agent_overrides.get("skill_planner") or None
            subagent_map["skill_planner"] = skill_planner_config(
                planner_model,
                planner_reasoning,
                planner_max_steps,
                llm_client,
                st.rag if st.rag is not None and st.rag.error is None else None,
                tf_client,
                st.reports,
                st.skills,
                lambda: sid,
                process_event,
                max_tokens=planner_max_tokens or None,
                temperature=planner_temperature or None,
                top_p=planner_top_p or None,
                system_prompt_override=planner_prompt,
                tinyfish_api_key=cfg.tinyfish_api_key,
            )

        # Study Planner: deterministic algorithm (no TinyFish, no RAG).
        # Always available — the planner calls plan_study which uses the
        # skill tree + learner states already in the DB. Because requests
        # are rare and cheap, use the orchestrator's model/reasoning with
        # a low max_steps (the planner calls one tool then summarises).
        sp_cfg = subagent_cfgs.get("study_planner")
        sp_model = (sp_cfg.model if sp_cfg else "") or DEFAULT_MODEL
        sp_reasoning = sp_cfg.reasoning if sp_cfg else reasoning
        sp_max_steps = sp_cfg.max_steps if sp_cfg else 10
        sp_prompt = cfg.agent_overrides.get("study_planner") or None
        subagent_map["study_planner"] = study_planner_config(
            sp_model, sp_reasoning, sp_max_steps,
            st.reports, st.study_plans, st.skills, st.learner_state, st.pedagogy, lambda: sid, process_event,
            system_prompt_override=sp_prompt,
            rag_engine=st.rag if st.rag is not None and st.rag.error is None else None,
            tf_client=tf_client,
            llm_client=llm_client,
            tinyfish_api_key=cfg.tinyfish_api_key,
            suspended_subagents=st.suspended_subagents,
        )

        # Evaluator: available ONLY when the Teacher agent is active (dormant
        # until Phase 12). Builds evaluator_config with its own DeploySubagent
        # (web_researcher fallback for source grounding) and UpdateMastery tool.
        # Requires RAG (the evaluator's Phase 1 searches the knowledge base
        # before falling back to web search).
        if agent_id == "maestro" and tf_client is not None:
            ev_cfg = subagent_cfgs.get("evaluator")
            ev_model = (ev_cfg.model if ev_cfg else "") or DEFAULT_MODEL
            ev_reasoning = ev_cfg.reasoning if ev_cfg else reasoning
            ev_max_steps = ev_cfg.max_steps if ev_cfg else 100
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

        # Teacher (Maestro): available as the main agent of learning sessions.
        # Its DeploySubagent includes documentalist (for authoritative sources)
        # and evaluator (for 2-phase assessment with resume_token support).
        if agent_id == "maestro" and tf_client is not None:
            te_cfg = subagent_cfgs.get("maestro")
            te_model = (te_cfg.model if te_cfg else "") or DEFAULT_MODEL
            te_reasoning = te_cfg.reasoning if te_cfg else reasoning
            te_max_steps = te_cfg.max_steps if te_cfg else 100
            te_prompt = cfg.agent_overrides.get("maestro") or None
            doc_cfg = subagent_cfgs.get("documentalist")
            doc_model = (doc_cfg.model if doc_cfg else "") or DEFAULT_MODEL
            doc_reasoning = doc_cfg.reasoning if doc_cfg else reasoning
            doc_prompt = cfg.agent_overrides.get("documentalist") or None
            subagent_map["maestro"] = teacher_config(
                te_model, te_reasoning, te_max_steps,
                llm_client,
                st.rag if st.rag is not None and st.rag.error is None else None,
                tf_client,
                st.reports, st.skills, st.learner_state, st.pedagogy, lambda: sid, process_event,
                system_prompt_override=te_prompt,
                tinyfish_api_key=cfg.tinyfish_api_key,
                suspended_subagents=st.suspended_subagents,
            )
            # The documentalist and evaluator have already been registered
            # earlier; the teacher's DeploySubagent references them by key.

        # session_analyzer: only available to the orchestrator (who can deploy
        # it to analyze session transcripts and produce profile patches).
        if agent_id != "system_support":
            s_analyzer_cfg = subagent_cfgs.get("session_analyzer")
            s_analyzer_model = (s_analyzer_cfg.model if s_analyzer_cfg else "") or DEFAULT_MODEL
            s_analyzer_reasoning = s_analyzer_cfg.reasoning if s_analyzer_cfg else "disabled"
            from cognits.agent.subagents import session_analyzer_config
            sa_cfg = session_analyzer_config(
                model=s_analyzer_model,
                reasoning=s_analyzer_reasoning,
            )
            subagent_map["session_analyzer"] = sa_cfg

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

        # CreateLearningSession: available for the orchestrator in
        # planning mode. Emits an SSE event the frontend will handle
        # (Fase 10) to create a new learning session.
        from cognits.agent.tool_ui import CreateLearningSession
        registry.register(
            CreateLearningSession(emit=process_event, skills=st.skills)
        )

        if agent_id == "system_support":
            from cognits.agent.tool_ui import FinishSetup

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

        if agent_id == "maestro":
            from cognits.agent.tool_ui import ApplyProfile
            registry.register(ApplyProfile(store=st.store, session_id=sid, emit=process_event))

        max_steps = cfg.max_steps or ORCHESTRATOR_MAX_STEPS
        ag = Agent(
            AgentConfig(
                name=agent_id,
                model=model,
                reasoning=reasoning,
                max_steps=max_steps,
                max_tokens=cfg.max_tokens or None,
                temperature=cfg.temperature or None,
                top_p=cfg.top_p or None,
                system_prompt=system_prompt,
                tools=registry,
                subagents=subagent_map,
            ),
            llm_client,
        )

        try:
            # Tag usage events so the frontend can distinguish main-agent
            # context usage from subagent usage.
            def _orchestrator_emit(ev: dict) -> None:
                if ev.get("type") == "usage" and isinstance(ev.get("data"), dict):
                    ev["data"]["source"] = "orchestrator"
                process_event(ev)

            await ag.run(llm_messages, _orchestrator_emit)
        except asyncio.CancelledError:
            # User cancellation is not an error as far as the chat goes.
            log.info("chat: agent run cancelled (session %s)", sid)
        except Exception as e:
            log.error("chat: agent run (session %s): %s", sid, e)
            sa.publish({"type": "error", "data": str(e)})
    finally:
        # 100% synchronous block: persist the partial, deregister, close.
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

        # The history was already persisted when the run started; only the
        # response remains (the partial too, if the run was cancelled). Direct
        # sqlite call (ms) instead of to_thread: an await here could be
        # interrupted by a second cancellation and skip the rest.
        if assistant_row is not None and st.db is not None:
            try:
                st.messages.append(sid, assistant_row)
            except Exception as e:
                log.error("chat: append message (session %s): %s", sid, e)

        st.active_agents.pop(sid, None)
        sa.close()

        # Close HTTP clients without awaiting (fire-and-forget on the loop).
        for client in (llm_client, tf_client):
            with contextlib.suppress(Exception):
                asyncio.get_running_loop().create_task(client.aclose())
