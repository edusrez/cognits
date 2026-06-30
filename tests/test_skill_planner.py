"""Tests for the skill_planner subagent + skill_tree_save tool.

Uses the ScriptedLLM pattern from test_agent.py (plain asyncio.run, no
pytest-asyncio marker — matches the codebase convention).

The SkillTreeSave tool exercises the real ReportStore on a tmp_path DB.
"""

import asyncio
import json

import pytest

from cognits.agent.agent import Agent, AgentConfig
from cognits.agent.tool_skill import SkillTreeSave
from cognits.storage.db import ReportStore
from cognits.tools import Registry


# --- helpers ---------------------------------------------------------

class ScriptedLLM:
    """Replays scripted streams; each element is one chat_completion_stream call."""

    def __init__(self, streams):
        self.streams = list(streams)
        self.calls = []

    async def chat_completion_stream(self, messages, tools, model, reasoning, on_chunk, **kwargs):
        self.calls.append([m.to_payload() for m in messages])
        for chunk in self.streams.pop(0):
            on_chunk(chunk)


def _tc(index, name, args):
    return {
        "index": index,
        "id": f"call_{index}",
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(args, ensure_ascii=False)},
    }


def _delta(content=None, tool_calls=None, finish=None):
    delta = {}
    if content is not None:
        delta["content"] = content
    if tool_calls is not None:
        delta["tool_calls"] = tool_calls
    return {"choices": [{"delta": delta, "finish_reason": finish}]}


@pytest.fixture
def store(tmp_path):
    rs = ReportStore(tmp_path / "test.db")
    yield rs
    rs.close()


# --- tool-level tests ------------------------------------------------

def test_skill_tree_save_start_build(store):
    tool = SkillTreeSave(report_store=store, session_id=lambda: "s1")
    result = asyncio.run(tool.execute(json.dumps({"action": "start_build", "trigger": "onboarding"})))
    data = json.loads(result)
    assert data["build_id"].startswith("b_")


def test_skill_tree_save_upsert_and_get(store):
    tool = SkillTreeSave(report_store=store, session_id=lambda: "s1")
    result = asyncio.run(tool.execute(json.dumps({
        "action": "upsert_skill",
        "domain": "python",
        "name": "Variables",
        "description": "Assignment, mutability, scope",
    })))
    skill_id = json.loads(result)["skill_id"]
    assert skill_id.startswith("k_")
    fetched = store.get_skill(skill_id)
    assert fetched.name == "Variables"
    assert fetched.domain == "python"
    ls = store.get_learner_state(skill_id)
    assert ls is not None and ls.p_mastery == 0.5


def test_skill_tree_save_add_edge_cycle_returns_tool_error(store):
    tool = SkillTreeSave(report_store=store, session_id=lambda: "s1")
    a = json.loads(asyncio.run(tool.execute(json.dumps({"action": "upsert_skill", "domain": "d", "name": "A"}))))["skill_id"]
    b = json.loads(asyncio.run(tool.execute(json.dumps({"action": "upsert_skill", "domain": "d", "name": "B"}))))["skill_id"]
    ok = asyncio.run(tool.execute(json.dumps({"action": "add_edge", "skill_id": b, "prereq_id": a, "edge_type": "prereq"})))
    assert json.loads(ok) == {"ok": True}
    err = asyncio.run(tool.execute(json.dumps({"action": "add_edge", "skill_id": a, "prereq_id": b, "edge_type": "prereq"})))
    err_data = json.loads(err)
    assert "error" in err_data
    assert "cycle" in err_data["error"].lower()


def test_skill_tree_save_finish_build(store):
    tool = SkillTreeSave(report_store=store, session_id=lambda: "s1")
    bid = json.loads(asyncio.run(tool.execute(json.dumps({"action": "start_build", "trigger": "test"}))))["build_id"]
    result = asyncio.run(tool.execute(json.dumps({
        "action": "finish_build",
        "build_id": bid,
        "summary": "built 3 skills",
        "status": "done",
    })))
    assert json.loads(result) == {"ok": True}
    with store._lock:
        row = store._conn.execute(
            "SELECT status, summary, finished_at FROM skill_builds WHERE id = ?", (bid,)
        ).fetchone()
    assert row[0] == "done"
    assert row[1] == "built 3 skills"
    assert row[2]  # finished_at set


def test_skill_tree_save_missing_args_returns_tool_error(store):
    tool = SkillTreeSave(report_store=store)
    result = asyncio.run(tool.execute(json.dumps({"action": "upsert_skill", "domain": "d"})))
    assert "error" in json.loads(result)


# --- agent-level end-to-end (no nested web_researcher) ---------------

def test_skill_planner_run_end_to_end_scripted(store):
    """Drive skill_planner's loop with a ScriptedLLM that issues start_build,
    upsert_skill x2, add_edge, finish_build, then emits Markdown content.

    The scripted tool_call args contain placeholders (__A__, __B__, __BID__)
    that we rewrite on the fly from earlier tool results seen in messages,
    so the agent loop sees consistent IDs without us hard-coding them.
    """
    tool = SkillTreeSave(report_store=store, session_id=lambda: "s_test")
    registry = Registry()
    registry.register(tool)

    captured = {"build_id": None, "skills": []}

    def _mangle_args(args_str):
        skills = captured["skills"]
        skill_a = skills[0] if len(skills) >= 1 else ""
        skill_b = skills[1] if len(skills) >= 2 else ""
        return (args_str
                .replace("__A__", skill_a)
                .replace("__B__", skill_b)
                .replace("__BID__", captured["build_id"] or ""))

    class RewritingScriptedLLM(ScriptedLLM):
        async def chat_completion_stream(self, messages, tools, model, reasoning, on_chunk, **kwargs):
            # Capture ALL distinct skill_id / build_id results we've seen so
            # far. We re-scan every call (messages accumulate) so we use lists
            # and dedupe by id string.
            for m in messages:
                if m.role == "tool":
                    try:
                        payload = json.loads(m.content)
                        if "build_id" in payload and not captured["build_id"]:
                            captured["build_id"] = payload["build_id"]
                        if "skill_id" in payload:
                            sid = payload["skill_id"]
                            if sid not in captured["skills"]:
                                captured["skills"].append(sid)
                    except json.JSONDecodeError:
                        pass
            if self.streams:
                for chunk in self.streams[0]:
                    tcs = chunk.get("choices", [{}])[0].get("delta", {}).get("tool_calls")
                    if tcs:
                        for tc in tcs:
                            tc["function"]["arguments"] = _mangle_args(tc["function"]["arguments"])
            return await super().chat_completion_stream(messages, tools, model, reasoning, on_chunk, **kwargs)

    streams = [
        [_delta(tool_calls=[_tc(0, "skill_tree_save", {"action": "start_build", "trigger": "onboarding"})], finish="tool_calls")],
        [_delta(tool_calls=[_tc(0, "skill_tree_save", {"action": "upsert_skill", "domain": "python", "name": "Variables", "description": "var basics"})], finish="tool_calls")],
        [_delta(tool_calls=[_tc(0, "skill_tree_save", {"action": "upsert_skill", "domain": "python", "name": "Loops", "description": "for/while"})], finish="tool_calls")],
        [_delta(tool_calls=[_tc(0, "skill_tree_save", {"action": "add_edge", "skill_id": "__B__", "prereq_id": "__A__", "edge_type": "prereq", "proof_query": "loops need variables"})], finish="tool_calls")],
        [_delta(tool_calls=[_tc(0, "skill_tree_save", {"action": "finish_build", "build_id": "__BID__", "summary": "2 skills, 1 edge"})], finish="tool_calls")],
        [_delta(content="# Skill tree for Python\n\n2 skills built.", finish="stop")],
    ]
    llm = RewritingScriptedLLM(streams)
    ag = Agent(AgentConfig(name="skill_planner", model="m", system_prompt="sp", tools=registry), llm)
    events = []
    result = asyncio.run(ag.run([], events.append))
    assert "Skill tree for Python" in result

    skills = store.list_skills()
    assert len(skills) == 2
    names = {s.name for s in skills}
    assert names == {"Variables", "Loops"}
    loops = next(s for s in skills if s.name == "Loops")
    variables = next(s for s in skills if s.name == "Variables")
    prereqs = store.get_prerequisites(loops.id)
    assert len(prereqs) == 1
    assert prereqs[0].prereq_id == variables.id
    assert prereqs[0].proof_query == "loops need variables"


# --- static schema checks --------------------------------------------

def test_deploy_subagent_enum_includes_skill_planner():
    from cognits.agent.tool_deploy import DeploySubagent
    assert "skill_planner" in DeploySubagent.schema["properties"]["type"]["enum"]


def test_subagent_labels_includes_skill_planner_and_web_researcher():
    from cognits.agent.tool_deploy import SUBAGENT_LABELS
    assert SUBAGENT_LABELS.get("skill_planner") == "Skill Planner"
    assert SUBAGENT_LABELS.get("web_researcher") == "Web Researcher"
    assert SUBAGENT_LABELS.get("directory_reader") == "Directory Reader"


def test_skill_planner_prompt_prohibits_timing():
    from cognits.agent.subagents import SKILL_PLANNER_SYSTEM_PROMPT
    assert "Do NOT include timing" in SKILL_PLANNER_SYSTEM_PROMPT
    assert "dependency order" in SKILL_PLANNER_SYSTEM_PROMPT
    assert "Scheduling is the Study" in SKILL_PLANNER_SYSTEM_PROMPT
    assert "Planner's job" in SKILL_PLANNER_SYSTEM_PROMPT


def test_skill_planner_appears_in_default_agents():
    from cognits.agent.prompts import DEFAULT_AGENTS
    ids = [a["id"] for a in DEFAULT_AGENTS]
    assert "skill_planner" in ids


def test_skill_planner_config_builds_registry(store):
    """skill_planner_config(...) returns a proper AgentConfig without touching
    the network. LLM and TinyFish clients are fakes that satisfy the type."""
    from cognits.agent.subagents import skill_planner_config

    class FakeLLM:
        async def aclose(self): pass
        async def chat_completion_stream(self, *a, **kw): pass

    class FakeTF:
        async def aclose(self): pass

    cfg = skill_planner_config(
        model="deepseek-v4-pro",
        reasoning="max",
        max_steps=999,
        llm_client=FakeLLM(),
        rag_engine=None,
        tf_client=FakeTF(),
        report_store=store,
        session_id=lambda: "s_test",
        emit=lambda ev: None,
        tinyfish_api_key="fake_key",
    )
    assert cfg.name == "skill_planner"
    assert cfg.model == "deepseek-v4-pro"
    assert cfg.reasoning == "max"
    assert cfg.max_steps == 999
    tool_names = set(cfg.tools._tools.keys())
    assert "skill_tree_save" in tool_names
    assert "deploy_subagent" in tool_names
    assert "web_researcher" in cfg.subagents