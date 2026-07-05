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

from cognits.agent.prompts import DEFAULT_AGENT_ID, TEACHER_SYSTEM_PROMPT, default_agent_prompt
from cognits.constants import DEFAULT_MODEL
from cognits.llm.deepseek import DeepSeekClient
from cognits.llm.types import ROLE_SYSTEM, ROLE_USER, Message
from cognits.server.exceptions import AgentBusy, ConfigError
from cognits.server.session_agent import SessionAgent
from cognits.server.util import MONTHS, WEEKDAYS
from cognits.storage.models import MessageRow
from cognits.storage.files import Config, StudentProfile

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

    all_states = store.get_all()

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

    # Accept both: a single ReportStore/LegacyStore (tests) or individual
    # repos (production). Use long-name methods on the legacy object, short
    # names on the real repos.
    _skills = store  # skills repo (or ReportStore in tests)
    _ls = learner_state if learner_state is not None else store
    _ped = pedagogy if pedagogy is not None else store

    if skill_id:
        skill = (
            _skills.get(skill_id)
            if _skills is not None else None
        )
        if skill:
            prompt += "\n\n## Skill\n\n"
            prompt += f"- Name: {skill.name}\n"
            prompt += f"- ID: {skill.id}\n"
            prompt += f"- Domain: {skill.domain}\n"
            prompt += f"- Description: {skill.description}\n"
            if skill.bloom_level:
                prompt += f"- Bloom level: {skill.bloom_level}\n"

        state = (
            _ls.get(skill_id)
            if _ls is not None else None
        )
        if state:
            prompt += "\n## Learner State\n\n"
            prompt += f"- Status: {state.status_enum}\n"
            prompt += f"- p_mastery (BKT): {state.p_mastery:.2f}\n"
            prompt += f"- Sessions completed: {state.reps}\n"
            if state.next_review:
                prompt += f"- FSRS next review: {state.next_review}\n"
        else:
            prompt += "\n## Learner State\n\n(No learner state yet)\n"

        plan = (
            _ped.get(skill_id)
            if _ped is not None else None
        )
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
            raise ConfigError("config not available")
        if not cfg.llm_api_key:
            raise ConfigError("API key not configured")

        try:
            body = await request.json()
            if not isinstance(body, dict):
                raise ValueError("body")
            incoming = body.get("messages") or []
            if not isinstance(incoming, list):
                raise ValueError("messages")
        except (json.JSONDecodeError, ValueError, UnicodeDecodeError):
            raise ConfigError("invalid body")

        sid = request.query_params.get("sessionId") or ""
        if not sid:
            raise ConfigError("sessionId required")

        # Config resolution: session → global → default.
        model = cfg.llm_model
        reasoning = cfg.llm_reasoning
        agent_id = cfg.llm_agent_id
        sess_cfg = None
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
            raise AgentBusy(sid)
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
    from cognits.server.chat_service import ChatService

    svc = ChatService(
        st, sa, cfg, sid, model, reasoning, system_prompt,
        llm_messages, incoming, agent_id,
    )
    await svc.run_agent()
