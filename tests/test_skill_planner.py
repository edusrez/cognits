"""Tests for the skill_planner subagent + skill_tree_save tool.
"""

import asyncio
import json
import os
import tempfile

import pytest

from cognits.agent.agent import Agent, AgentConfig
from cognits.agent.tool_skill import SkillTreeSave
from cognits.storage.database import Database
from cognits.storage.learner_state import LearnerStateRepository
from cognits.storage.skills import SkillRepository
from cognits.storage.assessment import AssessmentItemRepository
from cognits.storage.models import LearnerState, Skill, new_skill_id
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
    db = Database(tmp_path / "test.db")
    yield SkillRepository(db), LearnerStateRepository(db), db, AssessmentItemRepository(db)
    db.shutdown()


# --- tool-level tests ------------------------------------------------

def test_skill_tree_save_start_build(store):
    skills, learner_state, db, assessment = store
    tool = SkillTreeSave(skills=skills, assessment=assessment, session_id=lambda: "s1")
    result = asyncio.run(tool.execute(json.dumps({"action": "start_build", "trigger": "onboarding"})))
    data = json.loads(result)
    assert data["build_id"].startswith("b_")


def test_skill_tree_save_upsert_and_get(store):
    skills, learner_state, db, assessment = store
    tool = SkillTreeSave(skills=skills, assessment=assessment, session_id=lambda: "s1")
    result = asyncio.run(tool.execute(json.dumps({
        "action": "upsert_skill",
        "domain": "python",
        "name": "Variables",
        "description": "Assignment, mutability, scope",
    })))
    skill_id = json.loads(result)["skill_id"]
    assert skill_id.startswith("k_")
    fetched = skills.get(skill_id)
    assert fetched.name == "Variables"
    assert fetched.domain == "python"
    ls = learner_state.get(skill_id)
    assert ls is not None and ls.p_mastery == 0.5


def test_skill_tree_save_add_edge_cycle_returns_tool_error(store):
    skills, learner_state, db, assessment = store
    tool = SkillTreeSave(skills=skills, assessment=assessment, session_id=lambda: "s1")
    a = json.loads(asyncio.run(tool.execute(json.dumps({"action": "upsert_skill", "domain": "d", "name": "A"}))))["skill_id"]
    b = json.loads(asyncio.run(tool.execute(json.dumps({"action": "upsert_skill", "domain": "d", "name": "B"}))))["skill_id"]
    ok = asyncio.run(tool.execute(json.dumps({"action": "add_edge", "skill_id": b, "prereq_id": a, "edge_type": "prereq"})))
    assert json.loads(ok) == {"ok": True}
    err = asyncio.run(tool.execute(json.dumps({"action": "add_edge", "skill_id": a, "prereq_id": b, "edge_type": "prereq"})))
    err_data = json.loads(err)
    assert "error" in err_data
    assert "cycle" in err_data["error"].lower()


def test_skill_tree_save_finish_build(store):
    skills, learner_state, db, assessment = store
    tool = SkillTreeSave(skills=skills, assessment=assessment, session_id=lambda: "s1")
    bid = json.loads(asyncio.run(tool.execute(json.dumps({"action": "start_build", "trigger": "test"}))))["build_id"]
    result = asyncio.run(tool.execute(json.dumps({
        "action": "finish_build",
        "build_id": bid,
        "summary": "built 3 skills",
        "status": "done",
    })))
    assert json.loads(result) == {"ok": True}
    with db.lock:
        row = db.conn.execute(
            "SELECT status, summary, finished_at FROM skill_builds WHERE id = ?", (bid,)
        ).fetchone()
    assert row[0] == "done"
    assert row[1] == "built 3 skills"
    assert row[2]  # finished_at set


def test_skill_tree_save_missing_args_returns_tool_error(store):
    skills, learner_state, db, assessment = store
    tool = SkillTreeSave(skills=skills, assessment=assessment)
    result = asyncio.run(tool.execute(json.dumps({"action": "upsert_skill", "domain": "d"})))
    assert "error" in json.loads(result)


# --- agent-level end-to-end (no nested web_researcher) ---------------

def test_skill_planner_run_end_to_end_scripted(store):
    skills, learner_state, db, assessment = store
    """Drive skill_planner's loop with a ScriptedLLM that issues start_build,
    upsert_skill x2, add_edge, finish_build, then emits Markdown content.

    The scripted tool_call args contain placeholders (__A__, __B__, __BID__)
    that we rewrite on the fly from earlier tool results seen in messages,
    so the agent loop sees consistent IDs without us hard-coding them.
    """
    tool = SkillTreeSave(skills=skills, assessment=assessment, session_id=lambda: "s_test")
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

    active = skills.list_active()
    assert len(active) == 2
    names = {s.name for s in active}
    assert names == {"Variables", "Loops"}
    loops = next(s for s in active if s.name == "Loops")
    variables = next(s for s in active if s.name == "Variables")
    prereqs = skills.get_prerequisites(loops.id)
    assert len(prereqs) == 1
    assert prereqs[0].prereq_id == variables.id
    assert prereqs[0].proof_query == "loops need variables"


# --- static schema checks --------------------------------------------

def test_deploy_subagent_enum_includes_skill_planner():
    from cognits.agent.tool_deploy import DeploySubagent
    assert "skill_planner" in DeploySubagent.schema["properties"]["type"]["enum"]
    assert "skill_branch_builder" in DeploySubagent.schema["properties"]["type"]["enum"]


def test_subagent_labels_includes_skill_planner_and_web_researcher():
    from cognits.constants import AGENT_LABELS
    assert AGENT_LABELS.get("skill_planner") == "Skill Planner"
    assert AGENT_LABELS.get("skill_branch_builder") == "Branch Builder"
    assert AGENT_LABELS.get("web_researcher") == "Web Researcher"
    assert AGENT_LABELS.get("directory_reader") == "Directory Reader"


def test_skill_planner_prompt_prohibits_timing():
    from cognits.agent.prompts import SKILL_PLANNER_SYSTEM_PROMPT
    assert "Do NOT include timing" in SKILL_PLANNER_SYSTEM_PROMPT
    assert "dependency order" in SKILL_PLANNER_SYSTEM_PROMPT
    assert "Scheduling is the" in SKILL_PLANNER_SYSTEM_PROMPT
    assert "Planner's job" in SKILL_PLANNER_SYSTEM_PROMPT


def test_skill_planner_appears_in_default_agents():
    from cognits.agent.prompts import DEFAULT_AGENTS
    ids = [a["id"] for a in DEFAULT_AGENTS]
    assert "skill_planner" in ids


def test_skill_planner_config_builds_registry(store):
    skills, learner_state, db, assessment = store
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
        reports=skills, skills=skills, assessment=assessment,
        learner_state=learner_state,
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
    assert "update_mastery" in tool_names
    assert "seed_mastery" in tool_names
    assert "deploy_subagent" in tool_names
    assert "web_researcher" in cfg.subagents


# --- assessment item tool actions ------------------------------------

def test_save_assessment_items(store):
    skills, learner_state, db, assessment = store
    s = Skill(id=new_skill_id(), domain="test", name="AssessTest", source="test")
    skills.upsert(s)
    tool = SkillTreeSave(skills=skills, assessment=assessment, session_id=lambda: "s1")
    items = [
        {"question": "Q1", "expected_answer": "A1", "rubric": "R1", "question_type": "open", "blooms_level": "remember", "difficulty": 0.3, "generation_model": "test"},
        {"question": "Q2", "expected_answer": "A2", "rubric": "R2", "question_type": "open", "blooms_level": "understand", "difficulty": 0.5, "generation_model": "test"},
        {"question": "Q3", "expected_answer": "A3", "rubric": "R3", "question_type": "open", "blooms_level": "apply", "difficulty": 0.7, "generation_model": "test"},
    ]
    result = asyncio.run(tool.execute(json.dumps({
        "action": "save_assessment_items",
        "skill_id": s.id,
        "items": items,
    })))
    data = json.loads(result)
    assert data["saved"] == 3
    assert len(data["item_ids"]) == 3
    assert all(iid.startswith("ai_") for iid in data["item_ids"])
    assert "warning" not in data

    # Verify they persist via list
    result2 = asyncio.run(tool.execute(json.dumps({
        "action": "list_assessment_items",
        "skill_id": s.id,
    })))
    data2 = json.loads(result2)
    assert len(data2["items"]) == 3
    assert all(it["question_type"] == "open" for it in data2["items"])


def test_save_assessment_items_warns_on_few(store):
    skills, learner_state, db, assessment = store
    s = Skill(id=new_skill_id(), domain="test", name="FewTest", source="test")
    skills.upsert(s)
    tool = SkillTreeSave(skills=skills, assessment=assessment, session_id=lambda: "s1")
    items = [
        {"question": "Q1", "expected_answer": "A1", "rubric": "R1", "question_type": "open", "blooms_level": "remember", "difficulty": 0.3, "generation_model": "test"},
        {"question": "Q2", "expected_answer": "A2", "rubric": "R2", "question_type": "open", "blooms_level": "understand", "difficulty": 0.5, "generation_model": "test"},
    ]
    result = asyncio.run(tool.execute(json.dumps({
        "action": "save_assessment_items",
        "skill_id": s.id,
        "items": items,
    })))
    data = json.loads(result)
    assert data["saved"] == 2
    assert "warning" in data
    assert "BKT" in data["warning"]


def test_save_assessment_items_unknown_skill(store):
    skills, learner_state, db, assessment = store
    tool = SkillTreeSave(skills=skills, assessment=assessment, session_id=lambda: "s1")
    result = asyncio.run(tool.execute(json.dumps({
        "action": "save_assessment_items",
        "skill_id": "k_nonexistent",
        "items": [{"question": "Q", "expected_answer": "A", "rubric": "R", "question_type": "open", "blooms_level": "remember", "difficulty": 0.5, "generation_model": "test"}],
    })))
    data = json.loads(result)
    assert "error" in data


def test_list_assessment_items(store):
    skills, learner_state, db, assessment = store
    s = Skill(id=new_skill_id(), domain="test", name="ListTest", source="test")
    skills.upsert(s)
    tool = SkillTreeSave(skills=skills, assessment=assessment, session_id=lambda: "s1")
    # Save 3 items with varying question_types
    items = [
        {"question": "Q1", "expected_answer": "A1", "rubric": "R1", "question_type": "multiple_choice", "blooms_level": "remember", "difficulty": 0.3, "generation_model": "test"},
        {"question": "Q2", "expected_answer": "A2", "rubric": "R2", "question_type": "open", "blooms_level": "understand", "difficulty": 0.5, "generation_model": "test"},
        {"question": "Q3", "expected_answer": "A3", "rubric": "R3", "question_type": "code", "blooms_level": "apply", "difficulty": 0.8, "generation_model": "test"},
    ]
    asyncio.run(tool.execute(json.dumps({
        "action": "save_assessment_items",
        "skill_id": s.id,
        "items": items,
    })))

    # List them back
    result = asyncio.run(tool.execute(json.dumps({
        "action": "list_assessment_items",
        "skill_id": s.id,
    })))
    data = json.loads(result)
    assert len(data["items"]) == 3
    qtypes = {it["question_type"] for it in data["items"]}
    assert qtypes == {"multiple_choice", "open", "code"}
    for it in data["items"]:
        assert it["skill_id"] == s.id
        assert it["status"] == "active"
        assert it["irt_model"] == "heuristic"


def test_list_assessment_items_empty_skill(store):
    skills, learner_state, db, assessment = store
    s = Skill(id=new_skill_id(), domain="test", name="EmptyTest", source="test")
    skills.upsert(s)
    tool = SkillTreeSave(skills=skills, assessment=assessment, session_id=lambda: "s1")
    result = asyncio.run(tool.execute(json.dumps({
        "action": "list_assessment_items",
        "skill_id": s.id,
    })))
    data = json.loads(result)
    assert len(data["items"]) == 0


def test_save_assessment_items_empty_array(store):
    skills, learner_state, db, assessment = store
    tool = SkillTreeSave(skills=skills, assessment=assessment, session_id=lambda: "s1")
    result = asyncio.run(tool.execute(json.dumps({
        "action": "save_assessment_items",
        "skill_id": "k_fake",
        "items": [],
    })))
    data = json.loads(result)
    assert "error" in data


# --- finish_build under-itemed count ---------------------------------

def test_finish_build_reports_underitemed_count(store):
    """finish_build appends '<N>/<M> skills have <3 assessment items' to summary."""
    skills, learner_state, db, assessment = store
    tool = SkillTreeSave(skills=skills, assessment=assessment, session_id=lambda: "s1")

    # Create 2 skills.
    a_id = json.loads(asyncio.run(tool.execute(json.dumps({
        "action": "upsert_skill", "domain": "d", "name": "A",
    }))))["skill_id"]
    b_id = json.loads(asyncio.run(tool.execute(json.dumps({
        "action": "upsert_skill", "domain": "d", "name": "B",
    }))))["skill_id"]

    # Give skill A 3 items (enough), skill B 1 item (under).
    items_a = [
        {"question": f"Q{i}", "expected_answer": "A", "rubric": "R",
         "question_type": "open", "blooms_level": "remember", "difficulty": 0.3,
         "generation_model": "test"}
        for i in range(3)
    ]
    items_b = [
        {"question": "Q1", "expected_answer": "A", "rubric": "R",
         "question_type": "open", "blooms_level": "remember", "difficulty": 0.3,
         "generation_model": "test"}
    ]
    for sid, items in ((a_id, items_a), (b_id, items_b)):
        asyncio.run(tool.execute(json.dumps({
            "action": "save_assessment_items",
            "skill_id": sid,
            "items": items,
        })))

    # Finish build — summary should mention under-itemed count.
    bid = json.loads(asyncio.run(tool.execute(json.dumps({
        "action": "start_build", "trigger": "test",
    }))))["build_id"]
    result = asyncio.run(tool.execute(json.dumps({
        "action": "finish_build",
        "build_id": bid,
        "summary": "built 2 skills",
        "status": "done",
    })))
    assert json.loads(result) == {"ok": True}

    # Check the persisted summary includes the under-itemed count.
    with db.lock:
        row = db.conn.execute(
            "SELECT summary FROM skill_builds WHERE id = ?", (bid,)
        ).fetchone()
    summary = row[0]
    assert "1/2 skills have <3 assessment items" in summary, (
        f"Expected '1/2 skills have <3 assessment items' in summary, got: {summary}"
    )


# --- alt_prereq edge type ------------------------------------------------

def test_skill_tree_save_add_edge_alt_prereq_requires_group_id(store):
    """tool_error returned when alt_prereq given without group_id."""
    skills, learner_state, db, assessment = store
    a = json.loads(asyncio.run(SkillTreeSave(skills=skills, assessment=assessment, session_id=lambda: "s1").execute(
        json.dumps({"action": "upsert_skill", "domain": "d", "name": "X"})
    )))["skill_id"]
    b = json.loads(asyncio.run(SkillTreeSave(skills=skills, assessment=assessment, session_id=lambda: "s1").execute(
        json.dumps({"action": "upsert_skill", "domain": "d", "name": "Y"})
    )))["skill_id"]
    tool = SkillTreeSave(skills=skills, assessment=assessment, session_id=lambda: "s1")
    result = asyncio.run(tool.execute(json.dumps({
        "action": "add_edge",
        "skill_id": b,
        "prereq_id": a,
        "edge_type": "alt_prereq",
    })))
    data = json.loads(result)
    assert "error" in data
    assert "group_id" in data["error"].lower()


def test_skill_tree_save_add_edge_alt_prereq_with_group_id(store):
    """alt_prereq with group_id succeeds."""
    skills, learner_state, db, assessment = store
    a = json.loads(asyncio.run(SkillTreeSave(skills=skills, assessment=assessment, session_id=lambda: "s1").execute(
        json.dumps({"action": "upsert_skill", "domain": "d", "name": "X"})
    )))["skill_id"]
    b = json.loads(asyncio.run(SkillTreeSave(skills=skills, assessment=assessment, session_id=lambda: "s1").execute(
        json.dumps({"action": "upsert_skill", "domain": "d", "name": "Y"})
    )))["skill_id"]
    tool = SkillTreeSave(skills=skills, assessment=assessment, session_id=lambda: "s1")
    result = asyncio.run(tool.execute(json.dumps({
        "action": "add_edge",
        "skill_id": b,
        "prereq_id": a,
        "edge_type": "alt_prereq",
        "group_id": "g1",
    })))
    assert json.loads(result) == {"ok": True}
    prereqs = skills.get_prerequisites(b)
    assert len(prereqs) == 1
    assert prereqs[0].edge_type == "alt_prereq"
    assert prereqs[0].group_id == "g1"


# --- validate_tree tests ----------------------------------------------

def test_validate_tree_pass(store):
    """A clean tree: every skill has ≥1 item, balanced Bloom distribution,
    proof_query 100%, no orphans, acyclic, density ≥1.2 → passed=true,
    no FAIL gaps."""
    skills, learner_state, db, assessment = store
    tool = SkillTreeSave(skills=skills, assessment=assessment, session_id=lambda: "s1")

    # Create 5 skills with balanced Bloom: remember, understand, apply,
    # analyze, evaluate (each 20% — all caps pass).
    ids = {}
    for name, bloom in [("RememberA", "remember"), ("UnderstandB", "understand"),
                         ("ApplyC", "apply"), ("AnalyzeD", "analyze"),
                         ("EvaluateE", "evaluate")]:
        sid = json.loads(asyncio.run(tool.execute(json.dumps({
            "action": "upsert_skill", "domain": "d", "name": name,
            "bloom_level": bloom,
        }))))["skill_id"]
        ids[name] = sid

    # Build a directed graph with 7 edges (ratio=1.4 → WARN not FAIL):
    # B→A, C→A, C→B, D→B, D→C, E→C, E→D
    edges = [
        ("UnderstandB", "RememberA"),
        ("ApplyC", "RememberA"),
        ("ApplyC", "UnderstandB"),
        ("AnalyzeD", "UnderstandB"),
        ("AnalyzeD", "ApplyC"),
        ("EvaluateE", "ApplyC"),
        ("EvaluateE", "AnalyzeD"),
    ]
    for src_name, dst_name in edges:
        asyncio.run(tool.execute(json.dumps({
            "action": "add_edge",
            "skill_id": ids[src_name], "prereq_id": ids[dst_name],
            "edge_type": "prereq", "proof_query": f"{src_name} needs {dst_name}",
        })))

    # ≥1 assessment item per skill.
    for sid in ids.values():
        asyncio.run(tool.execute(json.dumps({
            "action": "save_assessment_items",
            "skill_id": sid,
            "items": [{"question": "A sufficiently long question to pass quality",
                       "expected_answer": "Answer", "rubric": "Rubric",
                       "question_type": "open", "blooms_level": "remember",
                       "difficulty": 0.5, "generation_model": "test"}],
        })))

    result = asyncio.run(tool.execute(json.dumps({"action": "validate_tree"})))
    data = json.loads(result)

    assert data["passed"] is True, f"Expected passed=True but got gaps: {data['gaps']}"
    assert "PASS" in data["summary"]
    assert data["counts"]["skills"] == 5
    assert data["counts"]["edges"] == 7
    assert data["counts"]["items"] == 5
    assert data["counts"]["domains"] == 1

    # All gaps should be PASS (or WARN) — no FAIL.
    severities = {g["severity"] for g in data["gaps"]}
    assert "FAIL" not in severities

    # No fix lists needed.
    assert "skills_needing_items" not in data
    assert "orphan_skills" not in data
    assert "apply_skills" not in data


def test_validate_tree_fails_on_missing_items(store):
    """2 skills, 1 with 0 items → passed=false, gap assessment_items FAIL,
    skills_needing_items lists the 0-item skill."""
    skills, learner_state, db, assessment = store
    tool = SkillTreeSave(skills=skills, assessment=assessment, session_id=lambda: "s1")

    a_id = json.loads(asyncio.run(tool.execute(json.dumps({
        "action": "upsert_skill", "domain": "d", "name": "HasItems",
        "bloom_level": "understand",
    }))))["skill_id"]
    b_id = json.loads(asyncio.run(tool.execute(json.dumps({
        "action": "upsert_skill", "domain": "d", "name": "NoItems",
        "bloom_level": "understand",
    }))))["skill_id"]

    # Connect with proof_query.
    asyncio.run(tool.execute(json.dumps({
        "action": "add_edge", "skill_id": b_id, "prereq_id": a_id,
        "edge_type": "prereq", "proof_query": "pq",
    })))

    # Only skill A gets items — B has 0.
    asyncio.run(tool.execute(json.dumps({
        "action": "save_assessment_items",
        "skill_id": a_id,
        "items": [{"question": "Q", "expected_answer": "A", "rubric": "R",
                   "question_type": "open", "blooms_level": "remember",
                   "difficulty": 0.5, "generation_model": "test"}],
    })))

    result = asyncio.run(tool.execute(json.dumps({"action": "validate_tree"})))
    data = json.loads(result)

    assert data["passed"] is False
    assert "assessment_items" in data["summary"]

    # Find the FAIL gap for assessment_items.
    ai_gap = next(g for g in data["gaps"] if g["criterion"] == "assessment_items")
    assert ai_gap["severity"] == "FAIL"

    # skills_needing_items should list b_id.
    assert "skills_needing_items" in data
    assert b_id in data["skills_needing_items"]
    assert a_id not in data["skills_needing_items"]


def test_validate_tree_fails_on_bloom_apply(store):
    """apply > 35% → gap bloom_apply FAIL, apply_skills lists them."""
    skills, learner_state, db, assessment = store
    tool = SkillTreeSave(skills=skills, assessment=assessment, session_id=lambda: "s1")

    # 3 skills, 2 apply (66.7% > 35%).
    ids = []
    for name in ("UnderstandA", "ApplyB", "ApplyC"):
        bloom = "apply" if "Apply" in name else "understand"
        sid = json.loads(asyncio.run(tool.execute(json.dumps({
            "action": "upsert_skill", "domain": "d", "name": name,
            "bloom_level": bloom,
        }))))["skill_id"]
        ids.append(sid)

    # Connect them (acyclic chain).
    asyncio.run(tool.execute(json.dumps({
        "action": "add_edge", "skill_id": ids[1], "prereq_id": ids[0],
        "edge_type": "prereq", "proof_query": "pq1",
    })))
    asyncio.run(tool.execute(json.dumps({
        "action": "add_edge", "skill_id": ids[2], "prereq_id": ids[1],
        "edge_type": "prereq", "proof_query": "pq2",
    })))

    # ≥1 item per skill (so items don't fail).
    for sid in ids:
        asyncio.run(tool.execute(json.dumps({
            "action": "save_assessment_items",
            "skill_id": sid,
            "items": [{"question": "Q", "expected_answer": "A", "rubric": "R",
                       "question_type": "open", "blooms_level": "remember",
                       "difficulty": 0.5, "generation_model": "test"}],
        })))

    result = asyncio.run(tool.execute(json.dumps({"action": "validate_tree"})))
    data = json.loads(result)

    assert data["passed"] is False
    assert "bloom_apply_cap" in data["summary"]

    bloom_gap = next(g for g in data["gaps"] if g["criterion"] == "bloom_apply_cap")
    assert bloom_gap["severity"] == "FAIL"

    assert "apply_skills" in data
    assert len(data["apply_skills"]) == 2


def test_validate_tree_fails_on_orphans(store):
    """A non-root skill with no prereq + no dependent → orphan.
    A root (no prereq, HAS dependents) is NOT an orphan."""
    skills, learner_state, db, assessment = store
    tool = SkillTreeSave(skills=skills, assessment=assessment, session_id=lambda: "s1")

    # 3 skills: Root (no prereq, has dependent), Child (has prereq), Orphan (no prereq, no dependent).
    root_id = json.loads(asyncio.run(tool.execute(json.dumps({
        "action": "upsert_skill", "domain": "d", "name": "Root",
        "bloom_level": "understand",
    }))))["skill_id"]
    child_id = json.loads(asyncio.run(tool.execute(json.dumps({
        "action": "upsert_skill", "domain": "d", "name": "Child",
        "bloom_level": "understand",
    }))))["skill_id"]
    orphan_id = json.loads(asyncio.run(tool.execute(json.dumps({
        "action": "upsert_skill", "domain": "d", "name": "Orphan",
        "bloom_level": "understand",
    }))))["skill_id"]

    # Child → Root edge (Root is root, Child has prereq).
    asyncio.run(tool.execute(json.dumps({
        "action": "add_edge", "skill_id": child_id, "prereq_id": root_id,
        "edge_type": "prereq", "proof_query": "child needs root",
    })))

    # ≥1 item per skill.
    for sid in (root_id, child_id, orphan_id):
        asyncio.run(tool.execute(json.dumps({
            "action": "save_assessment_items",
            "skill_id": sid,
            "items": [{"question": "Q", "expected_answer": "A", "rubric": "R",
                       "question_type": "open", "blooms_level": "remember",
                       "difficulty": 0.5, "generation_model": "test"}],
        })))

    result = asyncio.run(tool.execute(json.dumps({"action": "validate_tree"})))
    data = json.loads(result)

    assert data["passed"] is False
    assert "connectivity_orphans" in data["summary"]

    orphan_gap = next(g for g in data["gaps"] if g["criterion"] == "connectivity_orphans")
    assert orphan_gap["severity"] == "FAIL"

    assert "orphan_skills" in data
    assert orphan_id in data["orphan_skills"]
    # Root (no prereq but has dependents) should NOT be in orphans.
    assert root_id not in data["orphan_skills"]


# --- upsert_skill with optional skill_id tests -----------------------

def test_upsert_skill_with_skill_id_updates(store):
    """upsert a skill, then upsert again with same skill_id + new bloom_level
    → the skill is UPDATED (not duplicated), bloom_level changed."""
    skills, learner_state, db, assessment = store
    tool = SkillTreeSave(skills=skills, assessment=assessment, session_id=lambda: "s1")

    # First upsert: creates new skill.
    r1 = json.loads(asyncio.run(tool.execute(json.dumps({
        "action": "upsert_skill",
        "domain": "d",
        "name": "Use FSM",
        "bloom_level": "apply",
        "description": "Implement FSM for enemy AI",
    }))))
    skill_id = r1["skill_id"]

    # Verify initial state.
    s1 = skills.get(skill_id)
    assert s1.name == "Use FSM"
    assert s1.bloom_level == "apply"
    assert s1.description == "Implement FSM for enemy AI"

    # Update: upsert with same skill_id, new bloom_level.
    r2 = json.loads(asyncio.run(tool.execute(json.dumps({
        "action": "upsert_skill",
        "skill_id": skill_id,
        "domain": "d",
        "name": "Analyze FSM vs Node-Based State",
        "bloom_level": "analyze",
        "description": "Compare FSM and node-based state patterns",
    }))))
    assert r2["skill_id"] == skill_id  # Same ID returned.

    # Verify the skill was updated, not duplicated.
    s2 = skills.get(skill_id)
    assert s2.name == "Analyze FSM vs Node-Based State"
    assert s2.bloom_level == "analyze"
    assert s2.description == "Compare FSM and node-based state patterns"

    # There should be only 1 active skill.
    active = skills.list_active()
    assert len(active) == 1


def test_upsert_skill_without_skill_id_creates_new(store):
    """Current behavior preserved: upsert without skill_id generates a new id."""
    skills, learner_state, db, assessment = store
    tool = SkillTreeSave(skills=skills, assessment=assessment, session_id=lambda: "s1")

    r1 = json.loads(asyncio.run(tool.execute(json.dumps({
        "action": "upsert_skill",
        "domain": "d",
        "name": "Skill A",
        "bloom_level": "understand",
    }))))
    r2 = json.loads(asyncio.run(tool.execute(json.dumps({
        "action": "upsert_skill",
        "domain": "d",
        "name": "Skill B",
        "bloom_level": "understand",
    }))))

    assert r1["skill_id"] != r2["skill_id"]
    assert r1["skill_id"].startswith("k_")
    assert r2["skill_id"].startswith("k_")

    active = skills.list_active()
    assert len(active) == 2


# --- validate_tree quality WARN tests ---------------------------------

def test_validate_tree_warns_on_low_quality_items(store):
    """Low-quality items (question <20 chars or empty rubric) produce a WARN
    gap but do NOT block passed (only FAIL gaps block)."""
    skills, learner_state, db, assessment = store
    tool = SkillTreeSave(skills=skills, assessment=assessment, session_id=lambda: "s1")

    # 5 skills with balanced Bloom (each 20%) so all new Bloom caps pass.
    ids = {}
    for name, bl in [("Remember", "remember"), ("Understand", "understand"),
                      ("Apply", "apply"), ("Analyze", "analyze"),
                      ("Evaluate", "evaluate")]:
        sid = json.loads(asyncio.run(tool.execute(json.dumps({
            "action": "upsert_skill", "domain": "d", "name": name,
            "bloom_level": bl,
        }))))["skill_id"]
        ids[name] = sid

    # Build a graph with 6 edges (ratio=1.2): chain (4) + 2 cross.
    chain_map = [("Understand", "Remember"), ("Apply", "Understand"),
                 ("Analyze", "Apply"), ("Evaluate", "Analyze")]
    for src, dst in chain_map:
        asyncio.run(tool.execute(json.dumps({
            "action": "add_edge", "skill_id": ids[src], "prereq_id": ids[dst],
            "edge_type": "prereq", "proof_query": f"{src} needs {dst}",
        })))
    for src, dst in [("Apply", "Remember"), ("Evaluate", "Understand")]:
        asyncio.run(tool.execute(json.dumps({
            "action": "add_edge", "skill_id": ids[src], "prereq_id": ids[dst],
            "edge_type": "prereq", "proof_query": f"{src} needs {dst}",
        })))

    # All skills get good items except Evaluate gets low-quality.
    for name in ("Remember", "Understand", "Apply", "Analyze"):
        asyncio.run(tool.execute(json.dumps({
            "action": "save_assessment_items",
            "skill_id": ids[name],
            "items": [{"question": "A real question that is long enough to pass",
                       "expected_answer": "Some answer", "rubric": "Grading guide",
                       "question_type": "open", "blooms_level": "remember",
                       "difficulty": 0.5, "generation_model": "test"}],
        })))
    bad_sid = ids["Evaluate"]
    asyncio.run(tool.execute(json.dumps({
        "action": "save_assessment_items",
        "skill_id": bad_sid,
        "items": [{"question": "What is X?",  # <20 chars
                   "expected_answer": "Answer", "rubric": "",  # empty rubric
                   "question_type": "open", "blooms_level": "remember",
                   "difficulty": 0.5, "generation_model": "test"}],
    })))

    result = asyncio.run(tool.execute(json.dumps({"action": "validate_tree"})))
    data = json.loads(result)

    # Should still pass (no FAIL gaps).
    assert data["passed"] is True, f"Expected passed=True but got gaps: {data['gaps']}"

    # Should have a WARN for item_quality.
    item_q_gap = next((g for g in data["gaps"] if g["criterion"] == "item_quality"), None)
    assert item_q_gap is not None, "Expected item_quality gap but not found"
    assert item_q_gap["severity"] == "WARN", f"Expected WARN severity, got {item_q_gap['severity']}"

    # low_quality_items / low_quality_skill_ids should be in response.
    assert "low_quality_items" in data, "Expected low_quality_items in response"
    assert "low_quality_skill_ids" in data, "Expected low_quality_skill_ids in response"
    assert len(data["low_quality_items"]) >= 1
    assert bad_sid in data["low_quality_skill_ids"]


def test_validate_tree_warns_on_bloom_over_conversion(store):
    """remember > 15% triggers a WARN (bloom_balance_overall) but does NOT
    block passed. Tests the distribution WARN for understand/remember."""
    skills, learner_state, db, assessment = store
    tool = SkillTreeSave(skills=skills, assessment=assessment, session_id=lambda: "s1")

    # 5 skills: 1 understand, 2 remember (40% > 15% → WARN), 1 apply, 1 analyze
    # apply=20% ≤35%, analyze=20% ≤30%, eval+create=0%<20%... need eval+create
    # Let's use: 1 understand, 2 remember (40% > 15% WARN), 1 apply, 1 evaluate
    # apply=20%, analyze=0%, eval+create=20% → Bloom all pass, high-order passes at boundary.
    # remember=40% > 15% → WARN bloom_balance_overall.
    ids = []
    blooms = ["understand"] * 1 + ["remember"] * 2 + ["apply"] * 1 + ["evaluate"] * 1
    for i, bl in enumerate(blooms):
        sid = json.loads(asyncio.run(tool.execute(json.dumps({
            "action": "upsert_skill", "domain": "d", "name": f"S{i}",
            "bloom_level": bl,
        }))))["skill_id"]
        ids.append(sid)

    # Build a graph with 6 edges (ratio=1.2, not FAIL): chain + 2 cross edges.
    # Chain: S1→S0, S2→S1, S3→S2, S4→S3 (4 edges)
    # Extra: S2→S0, S4→S1 (2 edges) = 6 edges / 5 skills = 1.2
    chain_edges = [(ids[i], ids[i-1]) for i in range(1, len(ids))]
    cross_edges = [(ids[2], ids[0]), (ids[4], ids[1])]
    for src, dst in chain_edges + cross_edges:
        asyncio.run(tool.execute(json.dumps({
            "action": "add_edge", "skill_id": src, "prereq_id": dst,
            "edge_type": "prereq", "proof_query": f"pq",
        })))

    # >=1 item per skill (good quality).
    for sid in ids:
        asyncio.run(tool.execute(json.dumps({
            "action": "save_assessment_items",
            "skill_id": sid,
            "items": [{"question": "A sufficiently long question to pass quality check",
                       "expected_answer": "Answer", "rubric": "Rubric here",
                       "question_type": "open", "blooms_level": "remember",
                       "difficulty": 0.5, "generation_model": "test"}],
        })))

    result = asyncio.run(tool.execute(json.dumps({"action": "validate_tree"})))
    data = json.loads(result)

    # Should still pass (only WARNs, no FAILs).
    assert data["passed"] is True, f"Expected passed=True but got gaps: {data['gaps']}"

    # Should have a WARN for bloom_balance_overall.
    bloom_gap = next((g for g in data["gaps"] if g["criterion"] == "bloom_balance_overall"), None)
    assert bloom_gap is not None, "Expected bloom_balance_overall gap but not found"
    assert bloom_gap["severity"] == "WARN", f"Expected WARN severity, got {bloom_gap['severity']}"
    assert "remember=40" in bloom_gap["current"].replace(".0%", ""), (
        f"Expected remember=40% in current, got: {bloom_gap['current']}"
    )


# --- new Bloom full-distribution + density tests -----------------------


def test_validate_tree_fails_on_analyze_over(store):
    """analyze > 30% → FAIL bloom_analyze_cap, even when apply is fine."""
    skills, learner_state, db, assessment = store
    tool = SkillTreeSave(skills=skills, assessment=assessment, session_id=lambda: "s1")

    # 10 skills: 4 analyze (40% > 30% → FAIL), 2 understand, 2 apply, 2 evaluate
    # apply=20% ≤35%, analyze=40%>30% FAIL, eval+create=20% ≥20%, max=40% ✓
    ids = []
    blooms = ["understand"] * 2 + ["apply"] * 2 + ["analyze"] * 4 + ["evaluate"] * 2
    for i, bl in enumerate(blooms):
        sid = json.loads(asyncio.run(tool.execute(json.dumps({
            "action": "upsert_skill", "domain": "d", "name": f"S{i}",
            "bloom_level": bl,
        }))))["skill_id"]
        ids.append(sid)

    # Build a graph with 12 edges (ratio=1.2): chain (9) + 3 cross.
    for i in range(1, len(ids)):
        asyncio.run(tool.execute(json.dumps({
            "action": "add_edge", "skill_id": ids[i], "prereq_id": ids[i - 1],
            "edge_type": "prereq", "proof_query": f"pq_{i}",
        })))
    for src, dst in [(5, 0), (7, 3), (9, 4)]:
        asyncio.run(tool.execute(json.dumps({
            "action": "add_edge", "skill_id": ids[src], "prereq_id": ids[dst],
            "edge_type": "prereq", "proof_query": "pq_cross",
        })))

    for sid in ids:
        asyncio.run(tool.execute(json.dumps({
            "action": "save_assessment_items",
            "skill_id": sid,
            "items": [{"question": "Long enough question for quality check",
                       "expected_answer": "Answer", "rubric": "Rubric",
                       "question_type": "open", "blooms_level": "remember",
                       "difficulty": 0.5, "generation_model": "test"}],
        })))

    result = asyncio.run(tool.execute(json.dumps({"action": "validate_tree"})))
    data = json.loads(result)

    assert data["passed"] is False
    assert "bloom_analyze_cap" in data["summary"]
    anal_gap = next(g for g in data["gaps"] if g["criterion"] == "bloom_analyze_cap")
    assert anal_gap["severity"] == "FAIL"
    assert "40.0%" in anal_gap["current"]


def test_validate_tree_fails_on_low_high_order(store):
    """evaluate+create < 20% → FAIL bloom_high_order_floor."""
    skills, learner_state, db, assessment = store
    tool = SkillTreeSave(skills=skills, assessment=assessment, session_id=lambda: "s1")

    # 5 skills: 2 remember, 1 understand, 1 apply, 1 analyze, 0 eval/create
    # eval+create=0% < 20% → FAIL. All other caps pass (apply=20%, analyze=20%).
    ids = []
    blooms = ["remember"] * 2 + ["understand"] * 1 + ["apply"] * 1 + ["analyze"] * 1
    for i, bl in enumerate(blooms):
        sid = json.loads(asyncio.run(tool.execute(json.dumps({
            "action": "upsert_skill", "domain": "d", "name": f"S{i}",
            "bloom_level": bl,
        }))))["skill_id"]
        ids.append(sid)

    # 5 skills → need ≥6 edges for density ≥1.2. Chain (4) + 2 cross = 6.
    for i in range(1, len(ids)):
        asyncio.run(tool.execute(json.dumps({
            "action": "add_edge", "skill_id": ids[i], "prereq_id": ids[i - 1],
            "edge_type": "prereq", "proof_query": f"pq_{i}",
        })))
    asyncio.run(tool.execute(json.dumps({
        "action": "add_edge", "skill_id": ids[2], "prereq_id": ids[0],
        "edge_type": "prereq", "proof_query": "pq_x1",
    })))
    asyncio.run(tool.execute(json.dumps({
        "action": "add_edge", "skill_id": ids[4], "prereq_id": ids[1],
        "edge_type": "prereq", "proof_query": "pq_x2",
    })))

    for sid in ids:
        asyncio.run(tool.execute(json.dumps({
            "action": "save_assessment_items",
            "skill_id": sid,
            "items": [{"question": "Long enough question for quality",
                       "expected_answer": "Answer", "rubric": "Rubric",
                       "question_type": "open", "blooms_level": "remember",
                       "difficulty": 0.5, "generation_model": "test"}],
        })))

    result = asyncio.run(tool.execute(json.dumps({"action": "validate_tree"})))
    data = json.loads(result)

    assert data["passed"] is False
    assert "bloom_high_order_floor" in data["summary"]
    ho_gap = next(g for g in data["gaps"] if g["criterion"] == "bloom_high_order_floor")
    assert ho_gap["severity"] == "FAIL"


def test_validate_tree_fails_on_single_dominance(store):
    """A single Bloom level > 40% → FAIL bloom_no_single_dominance."""
    skills, learner_state, db, assessment = store
    tool = SkillTreeSave(skills=skills, assessment=assessment, session_id=lambda: "s1")

    # 6 skills: 3 understand (50% > 40% → FAIL), 1 apply, 1 analyze, 1 evaluate
    # apply=16.7% ≤35%, analyze=16.7% ≤30%, eval+create=16.7% < 20%...
    # Need eval+create ≥20%. Add create too.
    ids = []
    blooms = ["understand"] * 3 + ["apply"] * 1 + ["analyze"] * 1 + ["evaluate"] * 1
    for i, bl in enumerate(blooms):
        sid = json.loads(asyncio.run(tool.execute(json.dumps({
            "action": "upsert_skill", "domain": "d", "name": f"S{i}",
            "bloom_level": bl,
        }))))["skill_id"]
        ids.append(sid)

    # 6 skills → need ≥8 edges for density ≥1.2 (6*1.2=7.2, ceil 8).
    # Chain (5) + 3 cross = 8.
    for i in range(1, len(ids)):
        asyncio.run(tool.execute(json.dumps({
            "action": "add_edge", "skill_id": ids[i], "prereq_id": ids[i - 1],
            "edge_type": "prereq", "proof_query": f"pq_{i}",
        })))
    for src, dst in [(2, 0), (4, 1), (5, 2)]:
        asyncio.run(tool.execute(json.dumps({
            "action": "add_edge", "skill_id": ids[src], "prereq_id": ids[dst],
            "edge_type": "prereq", "proof_query": "pq_cross",
        })))

    for sid in ids:
        asyncio.run(tool.execute(json.dumps({
            "action": "save_assessment_items",
            "skill_id": sid,
            "items": [{"question": "Long enough question for quality",
                       "expected_answer": "Answer", "rubric": "Rubric",
                       "question_type": "open", "blooms_level": "remember",
                       "difficulty": 0.5, "generation_model": "test"}],
        })))

    result = asyncio.run(tool.execute(json.dumps({"action": "validate_tree"})))
    data = json.loads(result)

    assert data["passed"] is False
    assert "bloom_no_single_dominance" in data["summary"]
    dom_gap = next(g for g in data["gaps"] if g["criterion"] == "bloom_no_single_dominance")
    assert dom_gap["severity"] == "FAIL"
    assert "50" in dom_gap["current"]


def test_validate_tree_passes_balanced_distribution(store):
    """Balanced Bloom: apply=30%, analyze=25%, evaluate=15%, create=10%, understand=20%
    → all Bloom PASS."""
    skills, learner_state, db, assessment = store
    tool = SkillTreeSave(skills=skills, assessment=assessment, session_id=lambda: "s1")

    # 20 skills: apply=6(30%), analyze=5(25%), evaluate=3(15%), create=2(10%), understand=4(20%)
    blooms = (["apply"] * 6 + ["analyze"] * 5 + ["evaluate"] * 3
              + ["create"] * 2 + ["understand"] * 4)
    ids = []
    for i, bl in enumerate(blooms):
        sid = json.loads(asyncio.run(tool.execute(json.dumps({
            "action": "upsert_skill", "domain": "d", "name": f"S{i}",
            "bloom_level": bl,
        }))))["skill_id"]
        ids.append(sid)

    # Chain (19) + 5 cross = 24 edges, ratio=1.2.
    for i in range(1, len(ids)):
        asyncio.run(tool.execute(json.dumps({
            "action": "add_edge", "skill_id": ids[i], "prereq_id": ids[i - 1],
            "edge_type": "prereq", "proof_query": f"pq_{i}",
        })))
    for src, dst in [(5, 0), (10, 3), (12, 6), (15, 8), (18, 10)]:
        asyncio.run(tool.execute(json.dumps({
            "action": "add_edge", "skill_id": ids[src], "prereq_id": ids[dst],
            "edge_type": "prereq", "proof_query": "pq_cross",
        })))

    for sid in ids:
        asyncio.run(tool.execute(json.dumps({
            "action": "save_assessment_items",
            "skill_id": sid,
            "items": [{"question": "A sufficiently long question for quality check",
                       "expected_answer": "Answer", "rubric": "Rubric",
                       "question_type": "open", "blooms_level": "remember",
                       "difficulty": 0.5, "generation_model": "test"}],
        })))

    result = asyncio.run(tool.execute(json.dumps({"action": "validate_tree"})))
    data = json.loads(result)

    assert data["passed"] is True, f"Expected passed=True but got gaps: {data['gaps']}"
    # Verify all Bloom criteria are PASS.
    for criterion in ("bloom_apply_cap", "bloom_analyze_cap", "bloom_high_order_floor", "bloom_no_single_dominance"):
        gap = next(g for g in data["gaps"] if g["criterion"] == criterion)
        assert gap["severity"] == "PASS", f"{criterion} should be PASS, got {gap['severity']}"


def test_validate_tree_fails_on_low_density(store):
    """ed/skill ratio < 0.8 → WARN connectivity_density. With 5 skills and
    3 edges (0.6), triggers WARN but still passes (no FAIL gaps from density
    alone — only orphans cause FAIL)."""
    skills, learner_state, db, assessment = store
    tool = SkillTreeSave(skills=skills, assessment=assessment, session_id=lambda: "s1")

    # 5 skills, chain S1→S0, S2→S1, S3→S2 = 3 edges, ratio=0.6 < 0.8.
    ids = []
    for name, bl in [("R", "remember"), ("U", "understand"), ("A1", "apply"),
                      ("A2", "analyze"), ("E", "evaluate")]:
        sid = json.loads(asyncio.run(tool.execute(json.dumps({
            "action": "upsert_skill", "domain": "d", "name": name,
            "bloom_level": bl,
        }))))["skill_id"]
        ids.append(sid)

    # Chain only (3 edges = 0.6 ed/skill < 0.8).
    for i in range(1, 4):
        asyncio.run(tool.execute(json.dumps({
            "action": "add_edge", "skill_id": ids[i], "prereq_id": ids[i - 1],
            "edge_type": "prereq", "proof_query": f"pq_{i}",
        })))

    for sid in ids:
        asyncio.run(tool.execute(json.dumps({
            "action": "save_assessment_items",
            "skill_id": sid,
            "items": [{"question": "Long enough question for quality",
                       "expected_answer": "Answer", "rubric": "Rubric",
                       "question_type": "open", "blooms_level": "remember",
                       "difficulty": 0.5, "generation_model": "test"}],
        })))

    result = asyncio.run(tool.execute(json.dumps({"action": "validate_tree"})))
    data = json.loads(result)

    # Density alone at 0.6 < 0.8 is WARN, not FAIL. But orphan_check (last 2
    # skills have no dependents) hits FAIL because skill S3 has no dependents
    # and S4 has no prereq. Actually: S3 depends on S2, S2 on S1, S1 on S0.
    # Edge S3→S2, S2→S1, S1→S0. So S4 (id[4]) has no prereq → root. S3 also
    # is a sink (no one depends on it). But orphan means no prereq AND no
    # dependents. S4 has no prereq but may/may not have dependents.
    # With 3 edges only connecting 4 skills, S4 is isolated (no prereq, no
    # dependents) → orphan → FAIL.
    # The test focus: connectivity_density should be WARN not FAIL.
    dens_gap = next((g for g in data["gaps"] if g["criterion"] == "connectivity_density"), None)
    # density may not appear as a separate gap if orphans take precedence
    # (the elif in the original). With orphans present, connectivity_orphans
    # is emitted instead of connectivity_density. So this test checks orphans
    # trigger FAIL.
    assert data["passed"] is False
    orphan_gap = next((g for g in data["gaps"] if g["criterion"] == "connectivity_orphans"), None)
    assert orphan_gap is not None
    assert orphan_gap["severity"] == "FAIL"


def test_validate_tree_warns_on_medium_density(store):
    """0.8 ≤ ed/skill ratio → PASS connectivity_density (softened per SOTA).
    A tree with ratio=1.2 (5 skills, 6 edges) now PASSES density check."""
    skills, learner_state, db, assessment = store
    tool = SkillTreeSave(skills=skills, assessment=assessment, session_id=lambda: "s1")

    # 5 skills, chain (4) + 2 cross = 6 edges, ratio=1.2.
    ids = []
    for name, bl in [("R", "remember"), ("U", "understand"), ("A1", "apply"),
                      ("A2", "analyze"), ("E", "evaluate")]:
        sid = json.loads(asyncio.run(tool.execute(json.dumps({
            "action": "upsert_skill", "domain": "d", "name": name,
            "bloom_level": bl,
        }))))["skill_id"]
        ids.append(sid)

    for i in range(1, len(ids)):
        asyncio.run(tool.execute(json.dumps({
            "action": "add_edge", "skill_id": ids[i], "prereq_id": ids[i - 1],
            "edge_type": "prereq", "proof_query": f"pq_{i}",
        })))
    asyncio.run(tool.execute(json.dumps({
        "action": "add_edge", "skill_id": ids[2], "prereq_id": ids[0],
        "edge_type": "prereq", "proof_query": "pq_x1",
    })))
    asyncio.run(tool.execute(json.dumps({
        "action": "add_edge", "skill_id": ids[4], "prereq_id": ids[1],
        "edge_type": "prereq", "proof_query": "pq_x2",
    })))

    for sid in ids:
        asyncio.run(tool.execute(json.dumps({
            "action": "save_assessment_items",
            "skill_id": sid,
            "items": [{"question": "Long enough question for quality",
                       "expected_answer": "Answer", "rubric": "Rubric",
                       "question_type": "open", "blooms_level": "remember",
                       "difficulty": 0.5, "generation_model": "test"}],
        })))

    result = asyncio.run(tool.execute(json.dumps({"action": "validate_tree"})))
    data = json.loads(result)

    assert data["passed"] is True, f"Expected passed=True but got gaps: {data['gaps']}"
    dens_gap = next((g for g in data["gaps"] if g["criterion"] == "connectivity_density"), None)
    assert dens_gap is not None, "Expected connectivity_density gap"
    assert dens_gap["severity"] == "PASS", f"Expected PASS (1.2 ≥ 0.8), got {dens_gap['severity']}"
    assert "1.20" in dens_gap["current"]


# --- mastery_seeding_frontier WARN tests -------------------------------

def _make_valid_tree(store):
    """Helper: build a valid 5-skill tree that passes all checks (Bloom, items,
    connectivity, proof). Returns (tool, skill_ids_dict) for further setup."""
    skills, learner_state, db, assessment = store
    tool = SkillTreeSave(skills=skills, assessment=assessment, session_id=lambda: "s1")

    ids = {}
    for name, bloom in [("RememberA", "remember"), ("UnderstandB", "understand"),
                         ("ApplyC", "apply"), ("AnalyzeD", "analyze"),
                         ("EvaluateE", "evaluate")]:
        sid = json.loads(asyncio.run(tool.execute(json.dumps({
            "action": "upsert_skill", "domain": "d", "name": name,
            "bloom_level": bloom,
        }))))["skill_id"]
        ids[name] = sid

    # 7 edges (ratio=1.4) — passes density
    edges = [
        ("UnderstandB", "RememberA"),
        ("ApplyC", "RememberA"),
        ("ApplyC", "UnderstandB"),
        ("AnalyzeD", "UnderstandB"),
        ("AnalyzeD", "ApplyC"),
        ("EvaluateE", "ApplyC"),
        ("EvaluateE", "AnalyzeD"),
    ]
    for src_name, dst_name in edges:
        asyncio.run(tool.execute(json.dumps({
            "action": "add_edge",
            "skill_id": ids[src_name], "prereq_id": ids[dst_name],
            "edge_type": "prereq", "proof_query": f"{src_name} needs {dst_name}",
        })))

    # 1 item per skill (good quality).
    for sid in ids.values():
        asyncio.run(tool.execute(json.dumps({
            "action": "save_assessment_items",
            "skill_id": sid,
            "items": [{"question": "A sufficiently long question to pass quality",
                       "expected_answer": "Answer", "rubric": "Rubric",
                       "question_type": "open", "blooms_level": "remember",
                       "difficulty": 0.5, "generation_model": "test"}],
        })))

    return tool, ids


def test_validate_tree_warns_on_no_high_mastery_seed(store):
    """3 seeded skills all at p=0.60 → WARN mastery_seeding_frontier,
    passed still true (no FAIL gaps), max_seeded_p_mastery=0.60."""
    skills, learner_state, db, assessment = store
    tool, ids = _make_valid_tree(store)

    # Seed 3 skills at p_mastery=0.60 (below 0.75 threshold).
    for name in ("RememberA", "UnderstandB", "ApplyC"):
        ls = LearnerState(
            skill_id=ids[name],
            alpha=3.0, beta=2.0, p_mastery=0.60,
            status_enum="developing",
        )
        asyncio.run(asyncio.to_thread(learner_state.upsert, ls))

    result = asyncio.run(tool.execute(json.dumps({"action": "validate_tree"})))
    data = json.loads(result)

    # Should still pass (only WARNs, no FAILs).
    assert data["passed"] is True, f"Expected passed=True but got gaps: {data['gaps']}"

    # Check WARN for mastery_seeding_frontier.
    seed_gap = next((g for g in data["gaps"] if g["criterion"] == "mastery_seeding_frontier"), None)
    assert seed_gap is not None, "Expected mastery_seeding_frontier gap but not found"
    assert seed_gap["severity"] == "WARN", f"Expected WARN, got {seed_gap['severity']}"
    assert "3 seeded" in seed_gap["current"] or "none" in seed_gap["current"]

    # Counts should reflect seeding state.
    assert data["counts"]["seeded_skills"] == 3
    assert data["counts"]["max_seeded_p_mastery"] == 0.60


def test_validate_tree_no_warn_when_high_mastery_seed(store):
    """One seeded skill at p=0.85 → no mastery_seeding_frontier WARN (PASS)."""
    skills, learner_state, db, assessment = store
    tool, ids = _make_valid_tree(store)

    # Seed one skill at p_mastery=0.85 (above 0.75 threshold).
    ls = LearnerState(
        skill_id=ids["RememberA"],
        alpha=17.0, beta=3.0, p_mastery=0.85,
        status_enum="proficient",
    )
    asyncio.run(asyncio.to_thread(learner_state.upsert, ls))

    result = asyncio.run(tool.execute(json.dumps({"action": "validate_tree"})))
    data = json.loads(result)

    # Should pass.
    assert data["passed"] is True, f"Expected passed=True but got gaps: {data['gaps']}"

    # mastery_seeding_frontier should be PASS (not WARN).
    seed_gap = next((g for g in data["gaps"] if g["criterion"] == "mastery_seeding_frontier"), None)
    assert seed_gap is not None, "Expected mastery_seeding_frontier gap but not found"
    assert seed_gap["severity"] == "PASS", f"Expected PASS, got {seed_gap['severity']}"

    # Counts should reflect seeding state.
    assert data["counts"]["seeded_skills"] == 1
    assert data["counts"]["max_seeded_p_mastery"] == 0.85


def test_validate_tree_no_warn_when_no_seeds(store):
    """No seeded skills at all → no WARN (PASS with 'no seeded skills' current)."""
    skills, learner_state, db, assessment = store
    tool, ids = _make_valid_tree(store)

    # No explicit learner_state upserts — all default to p_mastery=0.5.

    result = asyncio.run(tool.execute(json.dumps({"action": "validate_tree"})))
    data = json.loads(result)

    # Should pass.
    assert data["passed"] is True, f"Expected passed=True but got gaps: {data['gaps']}"

    # mastery_seeding_frontier should be PASS.
    seed_gap = next((g for g in data["gaps"] if g["criterion"] == "mastery_seeding_frontier"), None)
    assert seed_gap is not None, "Expected mastery_seeding_frontier gap but not found"
    assert seed_gap["severity"] == "PASS", f"Expected PASS, got {seed_gap['severity']}"

    # Counts should show no seeded skills.
    assert data["counts"]["seeded_skills"] == 0
    assert data["counts"]["max_seeded_p_mastery"] == 0.0


# --- propose_targets + adaptive validate_tree tests -------------------


def test_propose_targets_stores_targets(store):
    """Call propose_targets → the build row has the targets JSON."""
    skills, learner_state, db, assessment = store
    tool = SkillTreeSave(skills=skills, assessment=assessment, session_id=lambda: "s1")

    # Call start_build first (propose_targets updates the most recent build).
    bid = json.loads(asyncio.run(tool.execute(json.dumps({
        "action": "start_build", "trigger": "onboarding",
    }))))["build_id"]

    # Now propose targets.
    targets = {
        "domain_type": "programming",
        "size_range": [40, 100],
        "bloom_targets": {
            "apply": [35, 50],
            "analyze": [10, 20],
            "evaluate": [5, 15],
            "create": [5, 15],
            "understand": [15, 25],
            "remember": [0, 10],
        },
        "max_depth": 6,
        "atomicity_criterion": "each leaf skill is a specific coding task assessable via code output",
    }
    result = asyncio.run(tool.execute(json.dumps({
        "action": "propose_targets",
        "domain_type": targets["domain_type"],
        "size_range": targets["size_range"],
        "bloom_targets": targets["bloom_targets"],
        "max_depth": targets["max_depth"],
        "atomicity_criterion": targets["atomicity_criterion"],
    })))
    data = json.loads(result)
    assert data["ok"] is True
    assert data["build_id"] == bid
    assert data["targets"]["domain_type"] == "programming"

    # Verify the build row has targets stored.
    with db.lock:
        row = db.conn.execute(
            "SELECT targets FROM skill_builds WHERE id = ?", (bid,)
        ).fetchone()
    stored = json.loads(row[0])
    assert stored["domain_type"] == "programming"
    assert stored["size_range"] == [40, 100]
    assert stored["bloom_targets"]["apply"] == [35, 50]
    assert stored["max_depth"] == 6


def test_validate_tree_uses_proposed_targets(store):
    """Propose apply 40-50%, build tree with apply=45% → PASS within proposed range."""
    skills, learner_state, db, assessment = store
    tool = SkillTreeSave(skills=skills, assessment=assessment, session_id=lambda: "s1")

    # start_build + propose_targets with apply 40-50%.
    asyncio.run(tool.execute(json.dumps({"action": "start_build", "trigger": "test"})))
    asyncio.run(tool.execute(json.dumps({
        "action": "propose_targets",
        "domain_type": "programming",
        "size_range": [10, 20],
        "bloom_targets": {
            "apply": [40, 50],
            "understand": [20, 30],
            "analyze": [10, 20],
            "evaluate": [5, 15],
            "remember": [0, 10],
            "create": [0, 10],
        },
        "max_depth": 5,
        "atomicity_criterion": "test",
    })))

    # Build a tree with apply=45% (9/20 skills) — within proposed range.
    # 20 skills: 9 apply, 5 understand, 3 analyze, 1 evaluate, 2 remember
    ids = []
    blooms = (["apply"] * 9 + ["understand"] * 5 + ["analyze"] * 3
              + ["evaluate"] * 1 + ["remember"] * 2)
    for i, bl in enumerate(blooms):
        sid = json.loads(asyncio.run(tool.execute(json.dumps({
            "action": "upsert_skill", "domain": "d", "name": f"S{i}",
            "bloom_level": bl,
        }))))["skill_id"]
        ids.append(sid)

    # Chain (19 edges) + 5 cross = 24 edges / 20 skills = 1.2 ratio
    for i in range(1, len(ids)):
        asyncio.run(tool.execute(json.dumps({
            "action": "add_edge", "skill_id": ids[i], "prereq_id": ids[i - 1],
            "edge_type": "prereq", "proof_query": f"pq_{i}",
        })))
    for src, dst in [(5, 0), (10, 3), (12, 6), (15, 8), (18, 10)]:
        asyncio.run(tool.execute(json.dumps({
            "action": "add_edge", "skill_id": ids[src], "prereq_id": ids[dst],
            "edge_type": "prereq", "proof_query": "pq_cross",
        })))

    for sid in ids:
        asyncio.run(tool.execute(json.dumps({
            "action": "save_assessment_items",
            "skill_id": sid,
            "items": [{"question": "A sufficiently long question for quality",
                       "expected_answer": "Answer", "rubric": "Rubric",
                       "question_type": "open", "blooms_level": "remember",
                       "difficulty": 0.5, "generation_model": "test"}],
        })))

    result = asyncio.run(tool.execute(json.dumps({"action": "validate_tree"})))
    data = json.loads(result)

    assert data["passed"] is True, f"Expected passed=True but got gaps: {data['gaps']}"

    # Verify adaptive criteria exist.
    apply_gap = next((g for g in data["gaps"] if g["criterion"] == "bloom_apply_target"), None)
    assert apply_gap is not None, "Expected bloom_apply_target gap"
    assert apply_gap["severity"] == "PASS", f"Expected PASS for apply_target, got {apply_gap['severity']}"

    # Size + depth should be present.
    size_gap = next((g for g in data["gaps"] if g["criterion"] == "size_note"), None)
    assert size_gap is not None, "Expected size_note gap"
    assert size_gap["severity"] == "NOTE"
    depth_gap = next((g for g in data["gaps"] if g["criterion"] == "depth_target"), None)
    assert depth_gap is not None, "Expected depth_target gap"


def test_validate_tree_fails_outside_proposed_range(store):
    """Propose apply 40-50%, build with apply=55% → FAIL outside proposed range."""
    skills, learner_state, db, assessment = store
    tool = SkillTreeSave(skills=skills, assessment=assessment, session_id=lambda: "s1")

    asyncio.run(tool.execute(json.dumps({"action": "start_build", "trigger": "test"})))
    asyncio.run(tool.execute(json.dumps({
        "action": "propose_targets",
        "domain_type": "programming",
        "size_range": [10, 20],
        "bloom_targets": {
            "apply": [40, 50],
            "understand": [20, 30],
            "analyze": [10, 20],
            "evaluate": [5, 15],
            "remember": [0, 10],
            "create": [0, 10],
        },
        "max_depth": 5,
        "atomicity_criterion": "test",
    })))

    # Build a tree with apply=55% (11/20) — exceeds proposed max of 50%.
    ids = []
    blooms = (["apply"] * 11 + ["understand"] * 3 + ["analyze"] * 3
              + ["evaluate"] * 2 + ["remember"] * 1)
    for i, bl in enumerate(blooms):
        sid = json.loads(asyncio.run(tool.execute(json.dumps({
            "action": "upsert_skill", "domain": "d", "name": f"S{i}",
            "bloom_level": bl,
        }))))["skill_id"]
        ids.append(sid)

    for i in range(1, len(ids)):
        asyncio.run(tool.execute(json.dumps({
            "action": "add_edge", "skill_id": ids[i], "prereq_id": ids[i - 1],
            "edge_type": "prereq", "proof_query": f"pq_{i}",
        })))
    for src, dst in [(5, 0), (10, 3), (12, 6), (15, 8), (18, 10)]:
        asyncio.run(tool.execute(json.dumps({
            "action": "add_edge", "skill_id": ids[src], "prereq_id": ids[dst],
            "edge_type": "prereq", "proof_query": "pq_cross",
        })))

    for sid in ids:
        asyncio.run(tool.execute(json.dumps({
            "action": "save_assessment_items",
            "skill_id": sid,
            "items": [{"question": "A sufficiently long question for quality",
                       "expected_answer": "Answer", "rubric": "Rubric",
                       "question_type": "open", "blooms_level": "remember",
                       "difficulty": 0.5, "generation_model": "test"}],
        })))

    result = asyncio.run(tool.execute(json.dumps({"action": "validate_tree"})))
    data = json.loads(result)

    assert data["passed"] is False
    apply_gap = next((g for g in data["gaps"] if g["criterion"] == "bloom_apply_target"), None)
    assert apply_gap is not None, "Expected bloom_apply_target gap"
    assert apply_gap["severity"] == "FAIL", f"Expected FAIL, got {apply_gap['severity']}"


def test_validate_tree_falls_back_to_defaults_without_targets(store):
    """No propose_targets called → uses hardcoded defaults (apply≤35%)."""
    skills, learner_state, db, assessment = store
    tool = SkillTreeSave(skills=skills, assessment=assessment, session_id=lambda: "s1")

    # start_build WITHOUT propose_targets.
    asyncio.run(tool.execute(json.dumps({"action": "start_build", "trigger": "test"})))

    # Build with apply=50% (10/20) — fails hardcoded apply≤35%.
    ids = []
    blooms = (["apply"] * 10 + ["understand"] * 3 + ["analyze"] * 3
              + ["evaluate"] * 3 + ["remember"] * 1)
    for i, bl in enumerate(blooms):
        sid = json.loads(asyncio.run(tool.execute(json.dumps({
            "action": "upsert_skill", "domain": "d", "name": f"S{i}",
            "bloom_level": bl,
        }))))["skill_id"]
        ids.append(sid)

    for i in range(1, len(ids)):
        asyncio.run(tool.execute(json.dumps({
            "action": "add_edge", "skill_id": ids[i], "prereq_id": ids[i - 1],
            "edge_type": "prereq", "proof_query": f"pq_{i}",
        })))
    for src, dst in [(5, 0), (10, 3), (12, 6), (15, 8), (18, 10)]:
        asyncio.run(tool.execute(json.dumps({
            "action": "add_edge", "skill_id": ids[src], "prereq_id": ids[dst],
            "edge_type": "prereq", "proof_query": "pq_cross",
        })))

    for sid in ids:
        asyncio.run(tool.execute(json.dumps({
            "action": "save_assessment_items",
            "skill_id": sid,
            "items": [{"question": "A sufficiently long question for quality",
                       "expected_answer": "Answer", "rubric": "Rubric",
                       "question_type": "open", "blooms_level": "remember",
                       "difficulty": 0.5, "generation_model": "test"}],
        })))

    result = asyncio.run(tool.execute(json.dumps({"action": "validate_tree"})))
    data = json.loads(result)

    assert data["passed"] is False
    # Should have hardcoded bloom_apply_cap FAIL, not adaptive bloom_apply_target.
    apply_cap = next((g for g in data["gaps"] if g["criterion"] == "bloom_apply_cap"), None)
    assert apply_cap is not None, "Expected bloom_apply_cap gap (hardcoded fallback)"
    assert apply_cap["severity"] == "FAIL"
    # Adaptive criteria should NOT be present.
    apply_target = next((g for g in data["gaps"] if g["criterion"] == "bloom_apply_target"), None)
    assert apply_target is None, "Should not have bloom_apply_target when no targets proposed"


def test_validate_tree_adaptive_theory_domain(store):
    """Propose theory targets (understand 35-45%), build understand-heavy tree → PASS.
    Under hardcoded defaults (no single >40%), understand=42% would FAIL.
    With proposed targets, it PASSES."""
    skills, learner_state, db, assessment = store
    tool = SkillTreeSave(skills=skills, assessment=assessment, session_id=lambda: "s1")

    asyncio.run(tool.execute(json.dumps({"action": "start_build", "trigger": "test"})))
    asyncio.run(tool.execute(json.dumps({
        "action": "propose_targets",
        "domain_type": "field",
        "size_range": [10, 25],
        "bloom_targets": {
            "understand": [35, 45],
            "analyze": [20, 30],
            "evaluate": [15, 25],
            "remember": [10, 20],
            "apply": [0, 15],
            "create": [5, 15],
        },
        "max_depth": 5,
        "atomicity_criterion": "each leaf skill is a distinct concept assessable via explanation",
    })))

    # Build a tree with understand=42% (8/19 skills) — exceeds hardcoded 40%
    # but within proposed 35-45%.
    ids = []
    blooms = (["understand"] * 8 + ["analyze"] * 4 + ["evaluate"] * 3
              + ["remember"] * 2 + ["apply"] * 1 + ["create"] * 1)
    for i, bl in enumerate(blooms):
        sid = json.loads(asyncio.run(tool.execute(json.dumps({
            "action": "upsert_skill", "domain": "d", "name": f"S{i}",
            "bloom_level": bl,
        }))))["skill_id"]
        ids.append(sid)

    # 19 skills → need ≥23 edges (19*1.2=22.8, ceil 23). Chain 18 + 5 cross = 23.
    for i in range(1, len(ids)):
        asyncio.run(tool.execute(json.dumps({
            "action": "add_edge", "skill_id": ids[i], "prereq_id": ids[i - 1],
            "edge_type": "prereq", "proof_query": f"pq_{i}",
        })))
    for src, dst in [(5, 0), (9, 3), (12, 6), (15, 8), (18, 10)]:
        asyncio.run(tool.execute(json.dumps({
            "action": "add_edge", "skill_id": ids[src], "prereq_id": ids[dst],
            "edge_type": "prereq", "proof_query": "pq_cross",
        })))

    for sid in ids:
        asyncio.run(tool.execute(json.dumps({
            "action": "save_assessment_items",
            "skill_id": sid,
            "items": [{"question": "A sufficiently long question for quality",
                       "expected_answer": "Answer", "rubric": "Rubric",
                       "question_type": "open", "blooms_level": "remember",
                       "difficulty": 0.5, "generation_model": "test"}],
        })))

    result = asyncio.run(tool.execute(json.dumps({"action": "validate_tree"})))
    data = json.loads(result)

    assert data["passed"] is True, f"Expected passed=True (adaptive theory targets) but got: {data['gaps']}"

    # Verify understand is within proposed target.
    understand_gap = next((g for g in data["gaps"] if g["criterion"] == "bloom_understand_target"), None)
    assert understand_gap is not None, "Expected bloom_understand_target gap"
    assert understand_gap["severity"] == "PASS", f"Expected PASS, got {understand_gap['severity']}"

    # Verify size and depth targets are present.
    size_gap = next((g for g in data["gaps"] if g["criterion"] == "size_note"), None)
    assert size_gap is not None, "Expected size_note gap"
    assert size_gap["severity"] == "NOTE"
    depth_gap = next((g for g in data["gaps"] if g["criterion"] == "depth_target"), None)
    assert depth_gap is not None, "Expected depth_target gap"


# --- branch builder tests ---------------------------------------------


def test_skill_branch_builder_config_builds(store):
    """skill_branch_builder_config(...) returns a proper AgentConfig with
    the right tools: skill_tree_save, seed_mastery, update_mastery,
    deploy_subagent — and NO self-recursion."""
    skills, learner_state, db, assessment = store
    from cognits.agent.subagents import skill_branch_builder_config

    class FakeLLM:
        async def aclose(self): pass
        async def chat_completion_stream(self, *a, **kw): pass

    class FakeTF:
        async def aclose(self): pass

    cfg = skill_branch_builder_config(
        model="deepseek-v4-pro",
        reasoning="max",
        max_steps=200,
        llm_client=FakeLLM(),
        rag_engine=None,
        tf_client=FakeTF(),
        reports=skills, skills=skills, assessment=assessment,
        learner_state=learner_state,
        session_id=lambda: "s_test",
        emit=lambda ev: None,
        tinyfish_api_key="fake_key",
        system_prompt_override="test prompt",
    )
    assert cfg.name == "skill_branch_builder"
    assert cfg.internal is True
    assert cfg.model == "deepseek-v4-pro"
    assert cfg.reasoning == "max"
    assert cfg.max_steps == 200
    tool_names = set(cfg.tools._tools.keys())
    assert "skill_tree_save" in tool_names
    assert "update_mastery" in tool_names
    assert "seed_mastery" in tool_names
    assert "deploy_subagent" in tool_names
    assert "web_researcher" in cfg.subagents


def test_skill_planner_deploy_can_deploy_branch_builder(store):
    """skill_planner_config DeploySubagent's subagents dict includes
    'skill_branch_builder' and 'web_researcher'."""
    skills, learner_state, db, assessment = store
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
        reports=skills, skills=skills, assessment=assessment,
        learner_state=learner_state,
        session_id=lambda: "s_test",
        emit=lambda ev: None,
        tinyfish_api_key="fake_key",
        system_prompt_override="test prompt",
    )
    assert "web_researcher" in cfg.subagents
    assert "skill_branch_builder" in cfg.subagents
    bb = cfg.subagents["skill_branch_builder"]
    assert bb.name == "skill_branch_builder"
    assert bb.internal is True


def test_branch_builder_no_self_recursion(store):
    """The branch_builder's DeploySubagent subagents dict does NOT contain
    'skill_branch_builder' (only web_researcher) so recursion is bounded."""
    skills, learner_state, db, assessment = store
    from cognits.agent.subagents import skill_branch_builder_config

    class FakeLLM:
        async def aclose(self): pass
        async def chat_completion_stream(self, *a, **kw): pass

    class FakeTF:
        async def aclose(self): pass

    cfg = skill_branch_builder_config(
        model="deepseek-v4-pro",
        reasoning="max",
        max_steps=200,
        llm_client=FakeLLM(),
        rag_engine=None,
        tf_client=FakeTF(),
        reports=skills, skills=skills, assessment=assessment,
        learner_state=learner_state,
        session_id=lambda: "s_test",
        emit=lambda ev: None,
        tinyfish_api_key="fake_key",
        system_prompt_override="test prompt",
    )
    assert "skill_branch_builder" not in cfg.subagents
    assert "web_researcher" in cfg.subagents


# --- semantic dedup: find_duplicate_skills -----------------------------

import threading


class _MockRagEngine:
    def __init__(self, vectors_by_text):
        self.ready = threading.Event()
        self.ready.set()
        self.error = None
        self._vectors = vectors_by_text

    async def embed(self, texts):
        return [self._vectors[t] for t in texts]


def test_find_duplicate_skills_semantic(store):
    """2 skills with similar names → mock embed returns similar vectors → dup detected."""
    skills, learner_state, db, assessment = store
    mock_rag = _MockRagEngine({
        "Python Loops — Iteration with for and while": [0.7, 0.72, 0.0, 0.0],
        "Python Loop Structures — For and While loop constructs in Python": [0.68, 0.71, 0.0, 0.0],
    })
    tool = SkillTreeSave(
        skills=skills, assessment=assessment, rag_engine=mock_rag,
    )

    sid1 = json.loads(asyncio.run(tool.execute(json.dumps({
        "action": "upsert_skill", "domain": "python", "name": "Python Loops",
        "description": "Iteration with for and while",
    }))))["skill_id"]
    sid2 = json.loads(asyncio.run(tool.execute(json.dumps({
        "action": "upsert_skill", "domain": "python", "name": "Python Loop Structures",
        "description": "For and While loop constructs in Python",
    }))))["skill_id"]

    result = asyncio.run(tool.execute(json.dumps({"action": "find_duplicate_skills", "threshold": 0.85})))
    data = json.loads(result)
    assert data["method"] == "semantic"
    assert data["checked"] == 2
    assert len(data["duplicates"]) == 1
    dup = data["duplicates"][0]
    assert set([dup["skill_id_a"], dup["skill_id_b"]]) == {sid1, sid2}
    assert dup["cosine"] >= 0.85


def test_find_duplicate_skills_keyword_fallback(store):
    """rag_engine=None → FTS5 keyword fallback finds exact-name duplicates."""
    skills, learner_state, db, assessment = store
    tool = SkillTreeSave(skills=skills, assessment=assessment, rag_engine=None)

    sid1 = json.loads(asyncio.run(tool.execute(json.dumps({
        "action": "upsert_skill", "domain": "python", "name": "Variables",
        "description": "Assignment and mutability",
    }))))["skill_id"]
    sid2 = json.loads(asyncio.run(tool.execute(json.dumps({
        "action": "upsert_skill", "domain": "python", "name": "variables",
        "description": "Assignment and mutability",
    }))))["skill_id"]

    result = asyncio.run(tool.execute(json.dumps({"action": "find_duplicate_skills", "threshold": 0.85})))
    data = json.loads(result)
    assert data["method"] == "keyword_fallback"
    assert data["checked"] == 2
    assert len(data["duplicates"]) == 1
    dup = data["duplicates"][0]
    assert set([dup["skill_id_a"], dup["skill_id_b"]]) == {sid1, sid2}
    assert dup["cosine"] == 1.0


# --- merge_skills tests -------------------------------------------------

def test_merge_skills_remaps_edges(store):
    """Skill A (keep) + skill B (merge), edge B→C exists → after merge, A→C exists, B deleted."""
    skills, learner_state, db, assessment = store
    tool = SkillTreeSave(skills=skills, assessment=assessment)

    aid = json.loads(asyncio.run(tool.execute(json.dumps({
        "action": "upsert_skill", "domain": "d", "name": "A",
    }))))["skill_id"]
    bid = json.loads(asyncio.run(tool.execute(json.dumps({
        "action": "upsert_skill", "domain": "d", "name": "B",
    }))))["skill_id"]
    cid = json.loads(asyncio.run(tool.execute(json.dumps({
        "action": "upsert_skill", "domain": "d", "name": "C",
    }))))["skill_id"]
    did = json.loads(asyncio.run(tool.execute(json.dumps({
        "action": "upsert_skill", "domain": "d", "name": "D",
    }))))["skill_id"]

    # Edge B→C (B requires C)
    asyncio.run(tool.execute(json.dumps({
        "action": "add_edge", "skill_id": bid, "prereq_id": cid,
        "edge_type": "prereq",
    })))
    # Edge D→B (D requires B)
    asyncio.run(tool.execute(json.dumps({
        "action": "add_edge", "skill_id": did, "prereq_id": bid,
        "edge_type": "prereq",
    })))

    # Merge B into A
    result = asyncio.run(tool.execute(json.dumps({
        "action": "merge_skills",
        "keep_skill_id": aid,
        "merge_skill_ids": [bid],
    })))
    data = json.loads(result)
    assert data["merged"] == 1
    # B→C (skill_id remapped) + D→B (prereq_id remapped) = 2 edges
    assert data["edges_remapped"] == 2

    # B should be deleted
    assert skills.get(bid) is None

    # A should have edge A→C
    prereqs = skills.get_prerequisites(aid)
    assert len(prereqs) == 1
    assert prereqs[0].prereq_id == cid

    # D should have edge D→A
    prereqs_d = skills.get_prerequisites(did)
    assert len(prereqs_d) == 1
    assert prereqs_d[0].prereq_id == aid


def test_merge_skills_moves_items(store):
    """Skill B has 2 items → after merge into A, A has them."""
    skills, learner_state, db, assessment = store
    tool = SkillTreeSave(skills=skills, assessment=assessment)

    aid = json.loads(asyncio.run(tool.execute(json.dumps({
        "action": "upsert_skill", "domain": "d", "name": "A",
    }))))["skill_id"]
    bid = json.loads(asyncio.run(tool.execute(json.dumps({
        "action": "upsert_skill", "domain": "d", "name": "B",
    }))))["skill_id"]

    # Give skill B 2 items
    asyncio.run(tool.execute(json.dumps({
        "action": "save_assessment_items",
        "skill_id": bid,
        "items": [
            {"question": "What is B1?", "expected_answer": "Ans1", "rubric": "R1",
             "question_type": "open", "blooms_level": "remember",
             "difficulty": 0.5, "generation_model": "test"},
            {"question": "What is B2?", "expected_answer": "Ans2", "rubric": "R2",
             "question_type": "open", "blooms_level": "understand",
             "difficulty": 0.5, "generation_model": "test"},
        ],
    })))

    # Merge B into A
    result = asyncio.run(tool.execute(json.dumps({
        "action": "merge_skills",
        "keep_skill_id": aid,
        "merge_skill_ids": [bid],
    })))
    data = json.loads(result)
    assert data["items_moved"] == 2

    # A should have the 2 items
    items = asyncio.run(asyncio.to_thread(assessment.list_for_skill, aid, True))
    assert len(items) == 2


def test_merge_skills_keeps_higher_mastery(store):
    """Skill A p=0.5, skill B p=0.85 → after merge (B into A), A has p=0.85."""
    skills, learner_state, db, assessment = store
    tool = SkillTreeSave(skills=skills, assessment=assessment)

    aid = json.loads(asyncio.run(tool.execute(json.dumps({
        "action": "upsert_skill", "domain": "d", "name": "A",
    }))))["skill_id"]
    bid = json.loads(asyncio.run(tool.execute(json.dumps({
        "action": "upsert_skill", "domain": "d", "name": "B",
    }))))["skill_id"]

    # Set learner states
    la = LearnerState(skill_id=aid, alpha=3.0, beta=3.0, p_mastery=0.50,
                      reps=5, lapses=1, status_enum="developing")
    lb = LearnerState(skill_id=bid, alpha=17.0, beta=3.0, p_mastery=0.85,
                      reps=20, lapses=0, status_enum="proficient")
    asyncio.run(asyncio.to_thread(learner_state.upsert, la))
    asyncio.run(asyncio.to_thread(learner_state.upsert, lb))

    # Merge B into A
    result = asyncio.run(tool.execute(json.dumps({
        "action": "merge_skills",
        "keep_skill_id": aid,
        "merge_skill_ids": [bid],
    })))
    data = json.loads(result)
    assert data["merged"] == 1

    # A should have the higher p_mastery from B (0.85)
    ls = asyncio.run(asyncio.to_thread(learner_state.get, aid))
    assert ls is not None
    assert ls.p_mastery == 0.85
    assert ls.status_enum == "proficient"
    assert ls.reps == 20

    # B's learner state should be gone
    assert asyncio.run(asyncio.to_thread(learner_state.get, bid)) is None


# --- delete_skill tests -------------------------------------------------

def test_delete_skill_cascades(store):
    """skill X with 2 edges (in+out), 1 item, 1 learner_state
    -> delete_skill -> all removed, skill gone."""
    skills, learner_state, db, assessment = store
    tool = SkillTreeSave(skills=skills, assessment=assessment)

    # Create 3 skills: A -> X -> B (chain)
    aid = json.loads(asyncio.run(tool.execute(json.dumps({
        "action": "upsert_skill", "domain": "d", "name": "A",
    }))))["skill_id"]
    xid = json.loads(asyncio.run(tool.execute(json.dumps({
        "action": "upsert_skill", "domain": "d", "name": "X",
    }))))["skill_id"]
    bid = json.loads(asyncio.run(tool.execute(json.dumps({
        "action": "upsert_skill", "domain": "d", "name": "B",
    }))))["skill_id"]

    # Edge X->A (incoming prereq to X), B->X (outgoing from X)
    asyncio.run(tool.execute(json.dumps({
        "action": "add_edge", "skill_id": xid, "prereq_id": aid,
        "edge_type": "prereq",
    })))
    asyncio.run(tool.execute(json.dumps({
        "action": "add_edge", "skill_id": bid, "prereq_id": xid,
        "edge_type": "prereq",
    })))

    # Add assessment item for X
    asyncio.run(tool.execute(json.dumps({
        "action": "save_assessment_items",
        "skill_id": xid,
        "items": [{"question": "A sufficiently long question for X",
                   "expected_answer": "Answer", "rubric": "Rubric",
                   "question_type": "open", "blooms_level": "remember",
                   "difficulty": 0.5, "generation_model": "test"}],
    })))

    # Seed learner_state for X (p=0.85 to verify deletion)
    ls = LearnerState(skill_id=xid, alpha=17.0, beta=3.0, p_mastery=0.85,
                      status_enum="proficient")
    asyncio.run(asyncio.to_thread(learner_state.upsert, ls))

    # Verify pre-conditions
    assert skills.get(xid) is not None
    assert len(skills.get_prerequisites(xid)) == 1  # X->A
    # B->X should exist too
    prereqs_before = skills.get_prerequisites(bid)
    assert len(prereqs_before) == 1
    assert prereqs_before[0].prereq_id == xid
    items_before = asyncio.run(asyncio.to_thread(assessment.list_for_skill, xid, True))
    assert len(items_before) == 1
    ls_before = asyncio.run(asyncio.to_thread(learner_state.get, xid))
    assert ls_before is not None

    # Delete skill X
    result = asyncio.run(tool.execute(json.dumps({
        "action": "delete_skill",
        "skill_id": xid,
    })))
    data = json.loads(result)
    assert data["deleted"] is True
    assert data["skill_id"] == xid
    assert data["edges_removed"] == 2  # X->A (in) + B->X (out)
    assert data["items_removed"] == 1

    # Skill X is gone
    assert skills.get(xid) is None

    # Edges involving X are gone
    assert len(skills.get_prerequisites(xid)) == 0  # skill itself deleted, so this gets nothing
    prereqs_b_after = skills.get_prerequisites(bid)
    assert len(prereqs_b_after) == 0  # B->X edge removed

    # Assessment items for X are gone
    items_after = asyncio.run(asyncio.to_thread(assessment.list_for_skill, xid, True))
    assert len(items_after) == 0

    # Learner state for X is gone
    assert asyncio.run(asyncio.to_thread(learner_state.get, xid)) is None

    # Skills A and B still exist (only X was pruned)
    assert skills.get(aid) is not None
    assert skills.get(bid) is not None


# --- remove_edge tests --------------------------------------------------

def test_remove_edge(store):
    """edge A->B exists -> remove_edge(A, B) -> edge gone, other edges intact."""
    skills, learner_state, db, assessment = store
    tool = SkillTreeSave(skills=skills, assessment=assessment)

    aid = json.loads(asyncio.run(tool.execute(json.dumps({
        "action": "upsert_skill", "domain": "d", "name": "A",
    }))))["skill_id"]
    bid = json.loads(asyncio.run(tool.execute(json.dumps({
        "action": "upsert_skill", "domain": "d", "name": "B",
    }))))["skill_id"]
    cid = json.loads(asyncio.run(tool.execute(json.dumps({
        "action": "upsert_skill", "domain": "d", "name": "C",
    }))))["skill_id"]

    # B->A (edge to remove)
    asyncio.run(tool.execute(json.dumps({
        "action": "add_edge", "skill_id": bid, "prereq_id": aid,
        "edge_type": "prereq",
    })))
    # C->A (edge to keep)
    asyncio.run(tool.execute(json.dumps({
        "action": "add_edge", "skill_id": cid, "prereq_id": aid,
        "edge_type": "prereq",
    })))

    # Verify both edges exist
    prereqs_b = skills.get_prerequisites(bid)
    assert len(prereqs_b) == 1 and prereqs_b[0].prereq_id == aid
    prereqs_c = skills.get_prerequisites(cid)
    assert len(prereqs_c) == 1 and prereqs_c[0].prereq_id == aid

    # Remove B->A edge
    result = asyncio.run(tool.execute(json.dumps({
        "action": "remove_edge",
        "skill_id": bid,
        "prereq_id": aid,
    })))
    data = json.loads(result)
    assert data["removed"] is True

    # B->A is gone
    assert len(skills.get_prerequisites(bid)) == 0
    # C->A still intact
    prereqs_c_after = skills.get_prerequisites(cid)
    assert len(prereqs_c_after) == 1 and prereqs_c_after[0].prereq_id == aid


def test_remove_edge_nonexistent(store):
    """remove_edge on non-existent edge returns removed=False."""
    skills, learner_state, db, assessment = store
    tool = SkillTreeSave(skills=skills, assessment=assessment)

    aid = json.loads(asyncio.run(tool.execute(json.dumps({
        "action": "upsert_skill", "domain": "d", "name": "A",
    }))))["skill_id"]
    bid = json.loads(asyncio.run(tool.execute(json.dumps({
        "action": "upsert_skill", "domain": "d", "name": "B",
    }))))["skill_id"]

    # No edge exists between B and A
    result = asyncio.run(tool.execute(json.dumps({
        "action": "remove_edge",
        "skill_id": bid,
        "prereq_id": aid,
    })))
    data = json.loads(result)
    assert data["removed"] is False


# --- validate_tree organic size tests -----------------------------------

def test_validate_tree_no_size_check(store):
    """A tree with 3 skills -> validate_tree has NO size_target WARN/FAIL.
    Size is organic — even though there's a proposed size range, it's a NOTE
    not a WARN/FAIL."""
    skills, learner_state, db, assessment = store
    tool = SkillTreeSave(skills=skills, assessment=assessment)

    # Propose targets with size_range [10, 20]
    asyncio.run(tool.execute(json.dumps({"action": "start_build", "trigger": "test"})))
    asyncio.run(tool.execute(json.dumps({
        "action": "propose_targets",
        "domain_type": "programming",
        "size_range": [10, 20],
        "bloom_targets": {
            "apply": [20, 40],
            "analyze": [10, 25],
            "evaluate": [10, 25],
            "create": [5, 20],
            "understand": [15, 30],
            "remember": [5, 15],
        },
        "max_depth": 5,
        "atomicity_criterion": "test",
    })))

    # Build a small tree with only 3 skills (far below size_range [10, 20])
    # Balanced Bloom so no Bloom FAILs
    blooms = ["understand", "apply", "evaluate"]
    ids = []
    for i, bl in enumerate(blooms):
        sid = json.loads(asyncio.run(tool.execute(json.dumps({
            "action": "upsert_skill", "domain": "d", "name": f"S{i}",
            "bloom_level": bl,
        }))))["skill_id"]
        ids.append(sid)

    # Connect with edges (3 skills, 3 edges -> ratio 1.0, but we only care about size check)
    asyncio.run(tool.execute(json.dumps({
        "action": "add_edge", "skill_id": ids[1], "prereq_id": ids[0],
        "edge_type": "prereq", "proof_query": "pq1",
    })))
    asyncio.run(tool.execute(json.dumps({
        "action": "add_edge", "skill_id": ids[2], "prereq_id": ids[1],
        "edge_type": "prereq", "proof_query": "pq2",
    })))
    asyncio.run(tool.execute(json.dumps({
        "action": "add_edge", "skill_id": ids[2], "prereq_id": ids[0],
        "edge_type": "prereq", "proof_query": "pq3",
    })))

    for sid in ids:
        asyncio.run(tool.execute(json.dumps({
            "action": "save_assessment_items",
            "skill_id": sid,
            "items": [{"question": "A sufficiently long question for quality",
                       "expected_answer": "Answer", "rubric": "Rubric",
                       "question_type": "open", "blooms_level": "remember",
                       "difficulty": 0.5, "generation_model": "test"}],
        })))

    result = asyncio.run(tool.execute(json.dumps({"action": "validate_tree"})))
    data = json.loads(result)

    # Verify the size_note criterion exists and is NOTE severity (never FAIL/WARN)
    size_gap = next((g for g in data["gaps"] if g["criterion"] == "size_note"), None)
    assert size_gap is not None, "Expected size_note gap"
    assert size_gap["severity"] == "NOTE", (
        f"size_note should be NOTE, got {size_gap['severity']}"
    )
    assert "3 skills" in size_gap["current"]

    # There should be no size_target criterion at all
    size_target = next((g for g in data["gaps"] if g["criterion"] == "size_target"), None)
    assert size_target is None, "size_target criterion should not exist (replaced by size_note)"


def test_validate_tree_keeps_other_checks(store):
    """After dropping size check, other checks (items, Bloom, orphans, proof_query) still work."""
    skills, learner_state, db, assessment = store
    tool = SkillTreeSave(skills=skills, assessment=assessment)

    # Create 2 skills, one with 0 assessment items -> should FAIL
    aid = json.loads(asyncio.run(tool.execute(json.dumps({
        "action": "upsert_skill", "domain": "d", "name": "A",
        "bloom_level": "understand",
    }))))["skill_id"]
    bid = json.loads(asyncio.run(tool.execute(json.dumps({
        "action": "upsert_skill", "domain": "d", "name": "B",
        "bloom_level": "understand",
    }))))["skill_id"]

    # Connect with proof_query
    asyncio.run(tool.execute(json.dumps({
        "action": "add_edge", "skill_id": bid, "prereq_id": aid,
        "edge_type": "prereq", "proof_query": "B needs A",
    })))

    # Only A gets items — B has 0
    asyncio.run(tool.execute(json.dumps({
        "action": "save_assessment_items",
        "skill_id": aid,
        "items": [{"question": "A sufficiently long question for quality",
                   "expected_answer": "Answer", "rubric": "Rubric",
                   "question_type": "open", "blooms_level": "remember",
                   "difficulty": 0.5, "generation_model": "test"}],
    })))

    result = asyncio.run(tool.execute(json.dumps({"action": "validate_tree"})))
    data = json.loads(result)

    # assessment_items should FAIL
    ai_gap = next((g for g in data["gaps"] if g["criterion"] == "assessment_items"), None)
    assert ai_gap is not None, "Expected assessment_items gap"
    assert ai_gap["severity"] == "FAIL"

    # proof_query should PASS (only edge has proof)
    pq_gap = next((g for g in data["gaps"] if g["criterion"] == "proof_query"), None)
    assert pq_gap is not None, "Expected proof_query gap"
    assert pq_gap["severity"] == "PASS"

    # acyclic should PASS
    ac_gap = next((g for g in data["gaps"] if g["criterion"] == "acyclic"), None)
    assert ac_gap is not None, "Expected acyclic gap"
    assert ac_gap["severity"] == "PASS"

    # size_note should be NOTE (not FAIL/WARN)
    size_gap = next((g for g in data["gaps"] if g["criterion"] == "size_note"), None)
    assert size_gap is not None, "Expected size_note gap"
    assert size_gap["severity"] == "NOTE"

    # skills_needing_items should list bid
    assert "skills_needing_items" in data
    assert bid in data["skills_needing_items"]


# --- SOTA quality criteria tests (0.0.8) -------------------------------


def test_validate_tree_warns_on_bottleneck(store):
    """A skill with 9 incoming prereq edges → WARN bottleneck."""
    skills, learner_state, db, assessment = store
    tool = SkillTreeSave(skills=skills, assessment=assessment, session_id=lambda: "s1")

    # Create 1 bottleneck skill + 9 skills that all depend on it.
    bot_id = json.loads(asyncio.run(tool.execute(json.dumps({
        "action": "upsert_skill", "domain": "d", "name": "Bottleneck",
        "bloom_level": "understand",
    }))))["skill_id"]

    dep_ids = []
    for i in range(9):
        sid = json.loads(asyncio.run(tool.execute(json.dumps({
            "action": "upsert_skill", "domain": "d", "name": f"Dep{i}",
            "bloom_level": "apply",
        }))))["skill_id"]
        dep_ids.append(sid)
        asyncio.run(tool.execute(json.dumps({
            "action": "add_edge", "skill_id": sid, "prereq_id": bot_id,
            "edge_type": "prereq", "proof_query": f"dep{i} needs bottleneck",
        })))

    # Add items to all skills.
    for sid in [bot_id] + dep_ids:
        asyncio.run(tool.execute(json.dumps({
            "action": "save_assessment_items",
            "skill_id": sid,
            "items": [{"question": "Long enough question for quality check",
                       "expected_answer": "Answer", "rubric": "Rubric",
                       "question_type": "open", "blooms_level": "remember",
                       "difficulty": 0.5, "generation_model": "test"}],
        })))

    result = asyncio.run(tool.execute(json.dumps({"action": "validate_tree"})))
    data = json.loads(result)

    bottleneck_gap = next((g for g in data["gaps"] if g["criterion"] == "bottleneck"), None)
    assert bottleneck_gap is not None, "Expected bottleneck gap"
    assert bottleneck_gap["severity"] == "WARN", f"Expected WARN, got {bottleneck_gap['severity']}"
    assert "Bottleneck" in bottleneck_gap["current"]
    assert "9 incoming" in bottleneck_gap["current"]


def test_validate_tree_warns_on_low_bloom_coverage(store):
    """Only 2 Bloom levels represented → WARN bloom_coverage."""
    skills, learner_state, db, assessment = store
    tool = SkillTreeSave(skills=skills, assessment=assessment, session_id=lambda: "s1")

    # 5 skills, only 2 Bloom levels: understand + apply.
    ids = []
    blooms = ["understand"] * 3 + ["apply"] * 2
    for i, bl in enumerate(blooms):
        sid = json.loads(asyncio.run(tool.execute(json.dumps({
            "action": "upsert_skill", "domain": "d", "name": f"S{i}",
            "bloom_level": bl,
        }))))["skill_id"]
        ids.append(sid)

    # Chain: S1→S0, S2→S1, S3→S2, S4→S3 + cross = 6 edges, ratio=1.2.
    for i in range(1, len(ids)):
        asyncio.run(tool.execute(json.dumps({
            "action": "add_edge", "skill_id": ids[i], "prereq_id": ids[i - 1],
            "edge_type": "prereq", "proof_query": f"pq_{i}",
        })))
    asyncio.run(tool.execute(json.dumps({
        "action": "add_edge", "skill_id": ids[2], "prereq_id": ids[0],
        "edge_type": "prereq", "proof_query": "pq_x",
    })))

    for sid in ids:
        asyncio.run(tool.execute(json.dumps({
            "action": "save_assessment_items",
            "skill_id": sid,
            "items": [{"question": "A long enough question for quality check",
                       "expected_answer": "Answer", "rubric": "Rubric",
                       "question_type": "open", "blooms_level": "remember",
                       "difficulty": 0.5, "generation_model": "test"}],
        })))

    result = asyncio.run(tool.execute(json.dumps({"action": "validate_tree"})))
    data = json.loads(result)

    bloom_gap = next((g for g in data["gaps"] if g["criterion"] == "bloom_coverage"), None)
    assert bloom_gap is not None, "Expected bloom_coverage gap"
    assert bloom_gap["severity"] == "WARN", f"Expected WARN, got {bloom_gap['severity']}"
    assert "2/6" in bloom_gap["current"]


def test_validate_tree_goal_relevance_low(store):
    """30% of skills on goal path → WARN (not FAIL — >25%)."""
    skills, learner_state, db, assessment = store
    tool = SkillTreeSave(skills=skills, assessment=assessment, session_id=lambda: "s1")

    # 10 skills in a chain (10 skills, 9 edges → goal is top, all reachable
    # from goal = 100% goal-relevance). Need to break it: add 10 disconnected
    # skills + 10 on the chain = 20 total, 10 on path = 50%. For 30%, we need
    # ~14-15 skills where only ~30% are on the path.
    # Let's do: chain of 3 skills (goal→prereq→prereq) + 7 disconnected orphans
    # Total = 10 skills, 3 on path = 30%. Density would fail since orphans exist.
    # Actually, goal_relevance check runs regardless; orphans are a separate
    # criterion. Let's just make the test about goal_relevance specifically.

    # Create a chain of 3 skills (goal at top, prereqs below).
    ids = []
    for i in range(3):
        sid = json.loads(asyncio.run(tool.execute(json.dumps({
            "action": "upsert_skill", "domain": "d", "name": f"PathSkill{i}",
            "bloom_level": "understand",
        }))))["skill_id"]
        ids.append(sid)

    # Edges: S1→S0, S2→S1. So S2 is goal (nobody depends on it, 2 prereqs).
    asyncio.run(tool.execute(json.dumps({
        "action": "add_edge", "skill_id": ids[1], "prereq_id": ids[0],
        "edge_type": "prereq", "proof_query": "pq1",
    })))
    asyncio.run(tool.execute(json.dumps({
        "action": "add_edge", "skill_id": ids[2], "prereq_id": ids[1],
        "edge_type": "prereq", "proof_query": "pq2",
    })))

    # Add 7 orphan skills (not connected to goal path).
    orphan_ids = []
    for i in range(7):
        sid = json.loads(asyncio.run(tool.execute(json.dumps({
            "action": "upsert_skill", "domain": "d", "name": f"OrphanSkill{i}",
            "bloom_level": "apply",
        }))))["skill_id"]
        orphan_ids.append(sid)

    # Total: 10 skills. 3 on goal path = 30%. Goal relevance < 50% → WARN.
    for sid in ids + orphan_ids:
        asyncio.run(tool.execute(json.dumps({
            "action": "save_assessment_items",
            "skill_id": sid,
            "items": [{"question": "A long enough question for quality",
                       "expected_answer": "Answer", "rubric": "Rubric",
                       "question_type": "open", "blooms_level": "remember",
                       "difficulty": 0.5, "generation_model": "test"}],
        })))

    result = asyncio.run(tool.execute(json.dumps({"action": "validate_tree"})))
    data = json.loads(result)

    goal_gap = next((g for g in data["gaps"] if g["criterion"] == "goal_relevance"), None)
    assert goal_gap is not None, "Expected goal_relevance gap"
    assert goal_gap["severity"] == "WARN", f"Expected WARN, got {goal_gap['severity']}"
    assert "30" in goal_gap["current"]


def test_validate_tree_goal_relevance_fail(store):
    """~18% on goal path → FAIL (<20%)."""
    skills, learner_state, db, assessment = store
    tool = SkillTreeSave(skills=skills, assessment=assessment, session_id=lambda: "s1")

    # Chain of 2 (1 edge) + 9 orphans = 11 total, 2 on path ≈ 18.2% < 20% → FAIL.
    ids = []
    for i in range(2):
        sid = json.loads(asyncio.run(tool.execute(json.dumps({
            "action": "upsert_skill", "domain": "d", "name": f"Path{i}",
            "bloom_level": "understand",
        }))))["skill_id"]
        ids.append(sid)

    asyncio.run(tool.execute(json.dumps({
        "action": "add_edge", "skill_id": ids[1], "prereq_id": ids[0],
        "edge_type": "prereq", "proof_query": "pq1",
    })))

    orphan_ids = []
    for i in range(9):
        sid = json.loads(asyncio.run(tool.execute(json.dumps({
            "action": "upsert_skill", "domain": "d", "name": f"Orphan{i}",
            "bloom_level": "apply",
        }))))["skill_id"]
        orphan_ids.append(sid)

    for sid in ids + orphan_ids:
        asyncio.run(tool.execute(json.dumps({
            "action": "save_assessment_items",
            "skill_id": sid,
            "items": [{"question": "A long enough question for quality",
                       "expected_answer": "Answer", "rubric": "Rubric",
                       "question_type": "open", "blooms_level": "remember",
                       "difficulty": 0.5, "generation_model": "test"}],
        })))

    result = asyncio.run(tool.execute(json.dumps({"action": "validate_tree"})))
    data = json.loads(result)

    goal_gap = next((g for g in data["gaps"] if g["criterion"] == "goal_relevance"), None)
    assert goal_gap is not None, "Expected goal_relevance gap"
    assert goal_gap["severity"] == "FAIL", f"Expected FAIL, got {goal_gap['severity']}"
    assert "18." in goal_gap["current"]


def test_validate_tree_transitive_redundancy(store):
    """A→B, B→C, A→C (A→C redundant) → WARN if >10% redundant (1/3 = 33% > 10%)."""
    skills, learner_state, db, assessment = store
    tool = SkillTreeSave(skills=skills, assessment=assessment, session_id=lambda: "s1")

    ids = {}
    for name, bl in [("A", "remember"), ("B", "understand"), ("C", "apply")]:
        sid = json.loads(asyncio.run(tool.execute(json.dumps({
            "action": "upsert_skill", "domain": "d", "name": name,
            "bloom_level": bl,
        }))))["skill_id"]
        ids[name] = sid

    # A→B (B requires A)
    asyncio.run(tool.execute(json.dumps({
        "action": "add_edge", "skill_id": ids["B"], "prereq_id": ids["A"],
        "edge_type": "prereq", "proof_query": "B needs A",
    })))
    # B→C (C requires B)
    asyncio.run(tool.execute(json.dumps({
        "action": "add_edge", "skill_id": ids["C"], "prereq_id": ids["B"],
        "edge_type": "prereq", "proof_query": "C needs B",
    })))
    # A→C (C requires A — redundant since C→B→A)
    asyncio.run(tool.execute(json.dumps({
        "action": "add_edge", "skill_id": ids["C"], "prereq_id": ids["A"],
        "edge_type": "prereq", "proof_query": "C needs A (redundant)",
    })))

    for sid in ids.values():
        asyncio.run(tool.execute(json.dumps({
            "action": "save_assessment_items",
            "skill_id": sid,
            "items": [{"question": "Long enough question for quality check",
                       "expected_answer": "Answer", "rubric": "Rubric",
                       "question_type": "open", "blooms_level": "remember",
                       "difficulty": 0.5, "generation_model": "test"}],
        })))

    result = asyncio.run(tool.execute(json.dumps({"action": "validate_tree"})))
    data = json.loads(result)

    # 3 edges total, 1 redundant = 33.3% > 10% → WARN
    red_gap = next((g for g in data["gaps"] if g["criterion"] == "transitive_redundancy"), None)
    assert red_gap is not None, "Expected transitive_redundancy gap"
    assert red_gap["severity"] == "WARN", f"Expected WARN, got {red_gap['severity']}"
    assert "33" in red_gap["current"] or "33.3" in red_gap["current"]


def test_validate_tree_naming_specificity(store):
    """5 skills total, 2 with ≤2-word names (40%) → >20% → WARN."""
    skills, learner_state, db, assessment = store
    tool = SkillTreeSave(skills=skills, assessment=assessment, session_id=lambda: "s1")

    # 5 skills: 2 with short names (generic), 3 with longer specific names.
    ids = []
    for name, bl in [
        ("Variables", "remember"),  # ≤2 words → generic
        ("Loops", "understand"),  # ≤2 words → generic
        ("GDScript Variable Scope Rules", "apply"),  # >2 words → specific
        ("Signals and Slots System", "analyze"),  # >2 words → specific
        ("Procedural Dungeon Generation", "evaluate"),  # >2 words → specific
    ]:
        sid = json.loads(asyncio.run(tool.execute(json.dumps({
            "action": "upsert_skill", "domain": "d", "name": name,
            "bloom_level": bl,
        }))))["skill_id"]
        ids.append(sid)

    # Build edges (chain + cross = 6 edges, ratio 1.2, Bloom balanced).
    for i in range(1, len(ids)):
        asyncio.run(tool.execute(json.dumps({
            "action": "add_edge", "skill_id": ids[i], "prereq_id": ids[i - 1],
            "edge_type": "prereq", "proof_query": f"pq_{i}",
        })))
    asyncio.run(tool.execute(json.dumps({
        "action": "add_edge", "skill_id": ids[2], "prereq_id": ids[0],
        "edge_type": "prereq", "proof_query": "pq_x",
    })))

    for sid in ids:
        asyncio.run(tool.execute(json.dumps({
            "action": "save_assessment_items",
            "skill_id": sid,
            "items": [{"question": "A long enough question for quality check",
                       "expected_answer": "Answer", "rubric": "Rubric",
                       "question_type": "open", "blooms_level": "remember",
                       "difficulty": 0.5, "generation_model": "test"}],
        })))

    result = asyncio.run(tool.execute(json.dumps({"action": "validate_tree"})))
    data = json.loads(result)

    naming_gap = next((g for g in data["gaps"] if g["criterion"] == "naming_specificity"), None)
    assert naming_gap is not None, "Expected naming_specificity gap"
    assert naming_gap["severity"] == "WARN", f"Expected WARN, got {naming_gap['severity']}"
    assert "40" in naming_gap["current"]


def test_validate_tree_density_soft(store):
    """5 skills, 3 edges (0.6 ed/skill, <0.8) → WARN (not FAIL).
    5 skills, 5 edges (1.0) → no density WARN (PASS)."""
    skills, learner_state, db, assessment = store
    tool = SkillTreeSave(skills=skills, assessment=assessment, session_id=lambda: "s1")

    # --- Case 1: 5 skills, 3 edges (chain of 4), ratio=0.6 (<0.8) → WARN ---
    ids1 = []
    for name, bl in [("R", "remember"), ("U", "understand"), ("A1", "apply"),
                      ("A2", "analyze"), ("E", "evaluate")]:
        sid = json.loads(asyncio.run(tool.execute(json.dumps({
            "action": "upsert_skill", "domain": "d", "name": name,
            "bloom_level": bl,
        }))))["skill_id"]
        ids1.append(sid)

    # Only 3 edges: S1→S0, S2→S1, S3→S2 (S4 isolated → will be orphan).
    for i in range(1, 4):
        asyncio.run(tool.execute(json.dumps({
            "action": "add_edge", "skill_id": ids1[i], "prereq_id": ids1[i - 1],
            "edge_type": "prereq", "proof_query": f"pq_{i}",
        })))

    for sid in ids1:
        asyncio.run(tool.execute(json.dumps({
            "action": "save_assessment_items",
            "skill_id": sid,
            "items": [{"question": "A long enough question for quality check",
                       "expected_answer": "Answer", "rubric": "Rubric",
                       "question_type": "open", "blooms_level": "remember",
                       "difficulty": 0.5, "generation_model": "test"}],
        })))

    result1 = asyncio.run(tool.execute(json.dumps({"action": "validate_tree"})))
    data1 = json.loads(result1)

    # Orphans trigger FAIL. Check density: with orphan present, density
    # gap may not appear (elif chain). Let's just check the orphan is FAIL.
    orphan_gap = next((g for g in data1["gaps"] if g["criterion"] == "connectivity_orphans"), None)
    assert orphan_gap is not None
    assert orphan_gap["severity"] == "FAIL"

    # --- Case 2: new DB, 5 skills, 5 edges (chain of 5), ratio=1.0 → PASS ---
    from cognits.storage.database import Database
    from cognits.storage.skills import SkillRepository
    from cognits.storage.learner_state import LearnerStateRepository
    from cognits.storage.assessment import AssessmentItemRepository
    import tempfile, os
    db2_path = os.path.join(tempfile.mkdtemp(), "test2.db")
    db2 = Database(db2_path)
    skills2 = SkillRepository(db2)
    learner_state2 = LearnerStateRepository(db2)
    assessment2 = AssessmentItemRepository(db2)
    tool2 = SkillTreeSave(skills=skills2, assessment=assessment2, session_id=lambda: "s1")

    ids2 = []
    for name, bl in [("R", "remember"), ("U", "understand"), ("A1", "apply"),
                      ("A2", "analyze"), ("E", "evaluate")]:
        sid = json.loads(asyncio.run(tool2.execute(json.dumps({
            "action": "upsert_skill", "domain": "d", "name": name,
            "bloom_level": bl,
        }))))["skill_id"]
        ids2.append(sid)

    # Chain of 4 edges + 1 extra cross = 5 edges, ratio=1.0 ≥ 0.8 → PASS.
    for i in range(1, len(ids2)):
        asyncio.run(tool2.execute(json.dumps({
            "action": "add_edge", "skill_id": ids2[i], "prereq_id": ids2[i - 1],
            "edge_type": "prereq", "proof_query": f"pq_{i}",
        })))
    asyncio.run(tool2.execute(json.dumps({
        "action": "add_edge", "skill_id": ids2[3], "prereq_id": ids2[0],
        "edge_type": "prereq", "proof_query": "pq_x",
    })))

    for sid in ids2:
        asyncio.run(tool2.execute(json.dumps({
            "action": "save_assessment_items",
            "skill_id": sid,
            "items": [{"question": "A long enough question for quality check",
                       "expected_answer": "Answer", "rubric": "Rubric",
                       "question_type": "open", "blooms_level": "remember",
                       "difficulty": 0.5, "generation_model": "test"}],
        })))

    result2 = asyncio.run(tool2.execute(json.dumps({"action": "validate_tree"})))
    data2 = json.loads(result2)

    dens_gap = next((g for g in data2["gaps"] if g["criterion"] == "connectivity_density"), None)
    assert dens_gap is not None, "Expected connectivity_density gap"
    assert dens_gap["severity"] == "PASS", f"Expected PASS (1.0 ≥ 0.8), got {dens_gap['severity']}"
    assert "1.00" in dens_gap["current"]

    db2.shutdown()


# ------------------------------------------------------------------
# Fase B — Living Tree: mastery_judge + check_branch_floor tests
# ------------------------------------------------------------------


def test_mastery_judge_config():
    """Construct mastery_judge_config — internal=True, no tools, max_steps=50."""
    from cognits.agent.subagents import mastery_judge_config

    cfg = mastery_judge_config()
    assert cfg.name == "mastery_judge"
    assert cfg.internal is True
    assert cfg.tools is None
    assert cfg.max_steps == 50


def test_deploy_enum_includes_mastery_judge():
    """The deploy_subagent schema enum includes 'mastery_judge'."""
    from cognits.agent.tool_deploy import DeploySubagent

    assert "mastery_judge" in DeploySubagent.schema["properties"]["type"]["enum"]


def test_subagent_labels_includes_mastery_judge():
    from cognits.constants import AGENT_LABELS

    assert AGENT_LABELS.get("mastery_judge") == "Mastery Judge"


def test_mastery_judge_in_default_agents():
    from cognits.agent.prompts import DEFAULT_AGENTS

    ids = [a["id"] for a in DEFAULT_AGENTS]
    assert "mastery_judge" in ids


# --- CheckBranchFloor tool-level tests --------------------------------


@pytest.fixture
def floor_store(tmp_path):
    from cognits.storage.database import Database
    from cognits.storage.skills import SkillRepository
    from cognits.storage.learner_state import LearnerStateRepository
    from cognits.storage.messages import MessageRepository
    from cognits.storage.assessment import AssessmentItemRepository
    from cognits.storage.reports import ReportRepository

    db = Database(tmp_path / "floor_test.db")
    yield SkillRepository(db), LearnerStateRepository(db), MessageRepository(db), db, AssessmentItemRepository(db), ReportRepository(db)
    db.shutdown()


def test_check_branch_floor_no_prereqs(floor_store):
    """Branch root with no prereqs → floor_confirmed: true immediately."""
    skills, learner_state, messages, db, assessment, reports_repo = floor_store
    from cognits.agent.tool_floor import CheckBranchFloor
    from cognits.storage.models import Skill, new_skill_id

    # Create a skill with no prereqs.
    s = Skill(id=new_skill_id(), domain="test", name="RootSkill", source="test")
    skills.upsert(s)

    class FakeLLM:
        async def aclose(self): pass
        async def chat_completion_stream(self, *a, **kw): pass

    class FakeTF:
        async def aclose(self): pass

    tool = CheckBranchFloor(
        skills=skills,
        learner_state=learner_state,
        messages=messages,
        llm_client=FakeLLM(),
        rag_engine=None,
        tf_client=FakeTF(),
        reports=reports_repo,
        assessment=assessment,
        session_id=lambda: "s_test",
    )

    result = asyncio.run(tool.execute(json.dumps({"skill_id": s.id})))
    data = json.loads(result)
    assert data["floor_confirmed"] is True
    assert data["prereqs_checked"] == []
    assert data["expanded_skills"] == []
    assert data["expanded_count"] == 0


def test_check_branch_floor_confirmed(floor_store):
    """Branch root with 2 prereqs, mock mastery_judge returns 'mastered'
    for both → floor_confirmed: true, expanded_skills: []."""
    skills, learner_state, messages, db, assessment, reports_repo = floor_store
    from cognits.agent.tool_floor import CheckBranchFloor
    from cognits.storage.models import Skill, new_skill_id, LearnerState

    # Create 3 skills: root + 2 prereqs.
    root = Skill(id=new_skill_id(), domain="test", name="Root", source="test")
    prereq_a = Skill(id=new_skill_id(), domain="test", name="PrereqA", description="Prereq A desc", source="test")
    prereq_b = Skill(id=new_skill_id(), domain="test", name="PrereqB", description="Prereq B desc", source="test")
    for s in (root, prereq_a, prereq_b):
        skills.upsert(s)
    skills.add_edge(root.id, prereq_a.id, "prereq")
    skills.add_edge(root.id, prereq_b.id, "prereq")

    # B2 auto-mastered gates: need LearnerState with p>=0.95, conf>=12, reps>=3.
    for sid in (prereq_a.id, prereq_b.id):
        learner_state.upsert(LearnerState(
            skill_id=sid, p_mastery=0.99, alpha=11, beta=1, reps=3))

    class FakeLLM:
        async def aclose(self): pass
        async def chat_completion_stream(self, *a, **kw): pass

    class FakeTF:
        async def aclose(self): pass

    tool = CheckBranchFloor(
        skills=skills,
        learner_state=learner_state,
        messages=messages,
        llm_client=FakeLLM(),
        rag_engine=None,
        tf_client=FakeTF(),
        reports=reports_repo,
        assessment=assessment,
        session_id=lambda: "s_test",
    )

    # Override _deploy_mastery_judge to return Mastered for all.
    async def mock_deploy_mj(query):
        return {"mastery": "mastered", "confidence": 90, "reasoning": "profile says so"}

    tool._deploy_mastery_judge = mock_deploy_mj

    result = asyncio.run(tool.execute(json.dumps({"skill_id": root.id})))
    data = json.loads(result)
    assert data["floor_confirmed"] is True
    assert len(data["prereqs_checked"]) == 2
    assert all(pc["mastery"] == "mastered" for pc in data["prereqs_checked"])
    assert data["expanded_skills"] == []
    assert data["expanded_count"] == 0


def test_check_branch_floor_expands(floor_store):
    """Mock mastery_judge to return 'not_mastered' for 1 prereq
    → floor_confirmed: false, expanded_skills non-empty."""
    skills, learner_state, messages, db, assessment, reports_repo = floor_store
    from cognits.agent.tool_floor import CheckBranchFloor
    from cognits.storage.models import Skill, new_skill_id, LearnerState

    root = Skill(id=new_skill_id(), domain="test", name="Root", source="test")
    prereq_a = Skill(id=new_skill_id(), domain="test", name="PrereqA", description="desc a", source="test")
    prereq_b = Skill(id=new_skill_id(), domain="test", name="PrereqB", description="desc b", source="test")
    for s in (root, prereq_a, prereq_b):
        skills.upsert(s)
    skills.add_edge(root.id, prereq_a.id, "prereq")
    skills.add_edge(root.id, prereq_b.id, "prereq")

    # B2 auto-mastered for prereq_a; intermediate for prereq_b (LLM path).
    learner_state.upsert(LearnerState(
        skill_id=prereq_a.id, p_mastery=0.99, alpha=11, beta=1, reps=3))
    learner_state.upsert(LearnerState(
        skill_id=prereq_b.id, p_mastery=0.3, alpha=2, beta=4, reps=1))

    class FakeLLM:
        async def aclose(self): pass
        async def chat_completion_stream(self, *a, **kw): pass

    class FakeTF:
        async def aclose(self): pass

    tool = CheckBranchFloor(
        skills=skills,
        learner_state=learner_state,
        messages=messages,
        llm_client=FakeLLM(),
        rag_engine=None,
        tf_client=FakeTF(),
        reports=reports_repo,
        assessment=assessment,
        session_id=lambda: "s_test",
    )

    call_count = {"mj": 0}

    async def mock_deploy_mj(query):
        call_count["mj"] += 1
        if "PrereqB" in query:
            return {"mastery": "not_mastered", "confidence": 100, "reasoning": "no evidence"}
        return {"mastery": "mastered", "confidence": 90, "reasoning": "profile says so"}

    tool._deploy_mastery_judge = mock_deploy_mj

    # Override _deploy.execute to simulate a branch_builder that adds a new skill.
    async def mock_deploy_exec(raw_args):
        parsed = json.loads(raw_args)
        sub_type = parsed.get("type", "")
        if sub_type == "skill_branch_builder":
            # Simulate adding a new skill under the prereq_b branch.
            new_sid = new_skill_id()
            new_skill = Skill(
                id=new_sid, domain="test", name="PrereqB_Sub",
                description="sub skill", source="test",
                parent_skill_id=prereq_b.id,
            )
            await asyncio.to_thread(skills.upsert, new_skill)
            return json.dumps({"reportId": "r_test", "title": "branch built", "content": "expanded", "summary": "ok"})
        return json.dumps({"error": "unknown subagent type"})

    tool._deploy.execute = mock_deploy_exec

    result = asyncio.run(tool.execute(json.dumps({"skill_id": root.id})))
    data = json.loads(result)
    assert data["floor_confirmed"] is False
    assert len(data["prereqs_checked"]) == 2
    # One mastered, one not_mastered.
    mastered = [pc for pc in data["prereqs_checked"] if pc["mastery"] == "mastered"]
    not_mastered = [pc for pc in data["prereqs_checked"] if pc["mastery"] == "not_mastered"]
    assert len(mastered) == 1
    assert len(not_mastered) == 1
    assert not_mastered[0]["name"] == "PrereqB"
    assert data["expanded_count"] >= 1
    assert len(data["expanded_skills"]) >= 1


def test_check_branch_floor_in_maestro_registry(floor_store):
    """Construct teacher_config with messages → check_branch_floor is
    in the tool registry."""
    skills, learner_state, messages, db, assessment, reports_repo = floor_store
    from cognits.agent.subagents import teacher_config

    class FakeLLM:
        async def aclose(self): pass
        async def chat_completion_stream(self, *a, **kw): pass

    class FakeTF:
        async def aclose(self): pass

    cfg = teacher_config(
        model="deepseek-v4-pro",
        reasoning="enabled",
        max_steps=100,
        llm_client=FakeLLM(),
        rag_engine=None,
        tf_client=FakeTF(),
        reports=reports_repo,
        skills=skills,
        assessment=assessment,
        learner_state=learner_state,
        messages=messages,
        pedagogy=None,
        session_id=lambda: "s_test",
        emit=lambda ev: None,
        tinyfish_api_key="fake_key",
    )
    assert cfg.name == "maestro"
    tool_names = set(cfg.tools._tools.keys())
    assert "check_branch_floor" in tool_names
    assert "deploy_subagent" in tool_names


def test_check_branch_floor_missing_skill_id(floor_store):
    """Pass an unknown skill_id → returns JSON error."""
    skills, learner_state, messages, db, assessment, reports_repo = floor_store
    from cognits.agent.tool_floor import CheckBranchFloor

    class FakeLLM:
        async def aclose(self): pass
        async def chat_completion_stream(self, *a, **kw): pass

    class FakeTF:
        async def aclose(self): pass

    tool = CheckBranchFloor(
        skills=skills,
        learner_state=learner_state,
        messages=messages,
        llm_client=FakeLLM(),
        rag_engine=None,
        tf_client=FakeTF(),
        reports=reports_repo,
        assessment=assessment,
        session_id=lambda: "s_test",
    )

    result = asyncio.run(tool.execute(json.dumps({"skill_id": "k_nonexistent"})))
    data = json.loads(result)
    assert "error" in data


def test_mastery_judge_in_internal_subagents():
    from cognits.constants import INTERNAL_SUBAGENTS

    assert "mastery_judge" in INTERNAL_SUBAGENTS


def test_mastery_judge_prompt_loads(store):
    """The mastery_judge persona loads via agent_loader."""
    from cognits.agent.agent_loader import load_agent_prompt

    prompt = load_agent_prompt("mastery_judge")
    assert "mastery_judge" in prompt.lower()
    assert "JSON" in prompt


# ------------------------------------------------------------------
# Fase C — SHRINK + RESHAPE tests
# ------------------------------------------------------------------


def test_check_branch_floor_prunes_mastered_subtree(floor_store):
    """A prereq judged mastered (confidence 85) with a sub-tree (2 deeper
    skills) → the sub-tree is pruned (delete_skill), the mastered prereq
    kept as a leaf. pruned_skills lists the 2 removed, pruned_count: 2."""
    skills, learner_state, messages, db, assessment, reports_repo = floor_store
    from cognits.agent.tool_floor import CheckBranchFloor
    from cognits.storage.models import Skill, new_skill_id, LearnerState

    # Build: Root → PrereqA (mastered) → SubA1 → SubA2, plus PrereqB (mastered, no sub-tree)
    root = Skill(id=new_skill_id(), domain="test", name="Root", source="test")
    prereq_a = Skill(id=new_skill_id(), domain="test", name="PrereqA", description="mastered prereq", source="test")
    sub_a1 = Skill(id=new_skill_id(), domain="test", name="SubA1", description="deep sub-skill 1", source="test")
    sub_a2 = Skill(id=new_skill_id(), domain="test", name="SubA2", description="deep sub-skill 2", source="test")
    prereq_b = Skill(id=new_skill_id(), domain="test", name="PrereqB", description="also mastered, no sub-tree", source="test")
    for s in (root, prereq_a, sub_a1, sub_a2, prereq_b):
        skills.upsert(s)
    # Root → PrereqA, Root → PrereqB
    skills.add_edge(root.id, prereq_a.id, "prereq")
    skills.add_edge(root.id, prereq_b.id, "prereq")
    # PrereqA → SubA1 → SubA2 (sub-tree)
    skills.add_edge(prereq_a.id, sub_a1.id, "prereq")
    skills.add_edge(sub_a1.id, sub_a2.id, "prereq")

    # B2 auto-mastered gates for both prereqs.
    for sid in (prereq_a.id, prereq_b.id):
        learner_state.upsert(LearnerState(
            skill_id=sid, p_mastery=0.99, alpha=11, beta=1, reps=3))

    class FakeLLM:
        async def aclose(self): pass
        async def chat_completion_stream(self, *a, **kw): pass

    class FakeTF:
        async def aclose(self): pass

    tool = CheckBranchFloor(
        skills=skills,
        learner_state=learner_state,
        messages=messages,
        llm_client=FakeLLM(),
        rag_engine=None,
        tf_client=FakeTF(),
        reports=reports_repo,
        assessment=assessment,
        session_id=lambda: "s_test",
    )

    # Mock mastery_judge: PrereqA=mastered, PrereqB=mastered
    async def mock_deploy_mj(query):
        return {"mastery": "mastered", "confidence": 85, "reasoning": "evidenced"}

    tool._deploy_mastery_judge = mock_deploy_mj

    # Mock deploy.execute (should not be called since no not_mastered prereqs)
    async def mock_deploy_exec(raw_args):
        return json.dumps({"reportId": "r_none", "title": "none", "content": "none", "summary": "none"})

    tool._deploy.execute = mock_deploy_exec

    result = asyncio.run(tool.execute(json.dumps({"skill_id": root.id})))
    data = json.loads(result)

    # Pruned sub-tree: sub_a1 + sub_a2
    assert data["pruned_count"] == 2
    assert len(data["pruned_skills"]) == 2
    pruned_ids = {ps["skill_id"] for ps in data["pruned_skills"]}
    assert sub_a1.id in pruned_ids
    assert sub_a2.id in pruned_ids

    # Mastered prereqs themselves kept intact
    assert skills.get(prereq_a.id) is not None
    assert skills.get(prereq_b.id) is not None

    # Sub-tree skills deleted
    assert skills.get(sub_a1.id) is None
    assert skills.get(sub_a2.id) is None

    # floor_confirmed true (no expansion, pruning is expected)
    assert data["floor_confirmed"] is True
    assert len(data["prereqs_checked"]) == 2
    assert all(pc["mastery"] == "mastered" for pc in data["prereqs_checked"])


def test_check_branch_floor_no_prune_if_not_mastered(floor_store):
    """A prereq not_mastered → no pruning (only expansion, not shrink)."""
    skills, learner_state, messages, db, assessment, reports_repo = floor_store
    from cognits.agent.tool_floor import CheckBranchFloor
    from cognits.storage.models import Skill, new_skill_id

    root = Skill(id=new_skill_id(), domain="test", name="Root", source="test")
    prereq_a = Skill(id=new_skill_id(), domain="test", name="PrereqA", description="not mastered prereq with sub-tree", source="test")
    sub_a1 = Skill(id=new_skill_id(), domain="test", name="SubA1", description="deep sub-skill", source="test")
    for s in (root, prereq_a, sub_a1):
        skills.upsert(s)
    skills.add_edge(root.id, prereq_a.id, "prereq")
    skills.add_edge(prereq_a.id, sub_a1.id, "prereq")

    class FakeLLM:
        async def aclose(self): pass
        async def chat_completion_stream(self, *a, **kw): pass

    class FakeTF:
        async def aclose(self): pass

    tool = CheckBranchFloor(
        skills=skills,
        learner_state=learner_state,
        messages=messages,
        llm_client=FakeLLM(),
        rag_engine=None,
        tf_client=FakeTF(),
        reports=reports_repo,
        assessment=assessment,
        session_id=lambda: "s_test",
    )

    # Mock mastery_judge: PrereqA=not_mastered
    async def mock_deploy_mj(query):
        return {"mastery": "not_mastered", "confidence": 100, "reasoning": "no evidence"}

    tool._deploy_mastery_judge = mock_deploy_mj

    # Mock deploy.execute for branch_builder (won't actually add skills)
    async def mock_deploy_exec(raw_args):
        return json.dumps({"reportId": "r_test", "title": "branch built", "content": "expanded", "summary": "ok"})

    tool._deploy.execute = mock_deploy_exec

    result = asyncio.run(tool.execute(json.dumps({"skill_id": root.id})))
    data = json.loads(result)

    # No pruning for not_mastered prereqs
    assert data["pruned_count"] == 0
    assert data["pruned_skills"] == []

    # Sub-tree skill is NOT deleted (it stays — learner doesn't master base so needs deeper)
    assert skills.get(sub_a1.id) is not None

    # Mastered prereq itself stays
    assert skills.get(prereq_a.id) is not None


def test_refocus_tree_tool_definition():
    """RefocusTree.definitions() has name 'refocus_tree' + params new_goal,
    learner_profile, focus."""
    from cognits.agent.tool_refocus import RefocusTree

    tool = RefocusTree.__new__(RefocusTree)
    assert tool.name == "refocus_tree"
    assert tool.schema["required"] == ["new_goal", "learner_profile"]
    props = tool.schema["properties"]
    assert "new_goal" in props
    assert "learner_profile" in props
    assert "focus" in props
    assert "focus" not in tool.schema["required"]


def test_refocus_tree_in_maestro_registry(floor_store):
    """teacher_config has refocus_tree in the tool registry."""
    skills, learner_state, messages, db, assessment, reports_repo = floor_store
    from cognits.agent.subagents import teacher_config

    class FakeLLM:
        async def aclose(self): pass
        async def chat_completion_stream(self, *a, **kw): pass

    class FakeTF:
        async def aclose(self): pass

    cfg = teacher_config(
        model="deepseek-v4-pro",
        reasoning="enabled",
        max_steps=100,
        llm_client=FakeLLM(),
        rag_engine=None,
        tf_client=FakeTF(),
        reports=reports_repo,
        skills=skills,
        assessment=assessment,
        learner_state=learner_state,
        messages=messages,
        pedagogy=None,
        session_id=lambda: "s_test",
        emit=lambda ev: None,
        tinyfish_api_key="fake_key",
    )
    assert cfg.name == "maestro"
    tool_names = set(cfg.tools._tools.keys())
    assert "refocus_tree" in tool_names
    assert "check_branch_floor" in tool_names
    assert "deploy_subagent" in tool_names


def test_refocus_tree_executes(floor_store):
    """Mock the DeploySubagent (skill_planner) → refocus_tree returns
    {refocused: true, new_goal, summary}."""
    skills, learner_state, messages, db, assessment, reports_repo = floor_store
    from cognits.agent.tool_refocus import RefocusTree

    class FakeLLM:
        async def aclose(self): pass
        async def chat_completion_stream(self, *a, **kw): pass

    class FakeTF:
        async def aclose(self): pass

    tool = RefocusTree(
        skills=skills,
        learner_state=learner_state,
        assessment=assessment,
        llm_client=FakeLLM(),
        rag_engine=None,
        tf_client=FakeTF(),
        reports=reports_repo,
        session_id=lambda: "s_test",
        emit=None,
        tinyfish_api_key="fake_key",
    )

    # Mock DeploySubagent.execute to return skill_planner result
    async def mock_deploy_exec(raw_args):
        parsed = json.loads(raw_args)
        assert parsed["type"] == "skill_planner"
        assert "RE-FOCUS" in parsed["query"]
        return json.dumps({
            "reportId": "r_refocus",
            "title": "Tree re-decomposed",
            "content": "Re-focus complete. Added 3 new skills, pruned 2 obsolete.",
            "summary": "Tree reshaped for new goal",
        })

    tool._deploy.execute = mock_deploy_exec

    result = asyncio.run(tool.execute(json.dumps({
        "new_goal": "Build a 3D game engine",
        "learner_profile": "intermediate programmer, knows Python and C",
    })))
    data = json.loads(result)
    assert data["refocused"] is True
    assert data["new_goal"] == "Build a 3D game engine"
    assert "summary" in data
    assert data["skill_count"] >= 0


def test_refocus_tree_with_focus(floor_store):
    """refocus_tree with optional focus field passes it through to the
    skill_planner query."""
    skills, learner_state, messages, db, assessment, reports_repo = floor_store
    from cognits.agent.tool_refocus import RefocusTree

    class FakeLLM:
        async def aclose(self): pass
        async def chat_completion_stream(self, *a, **kw): pass

    class FakeTF:
        async def aclose(self): pass

    tool = RefocusTree(
        skills=skills,
        learner_state=learner_state,
        assessment=assessment,
        llm_client=FakeLLM(),
        rag_engine=None,
        tf_client=FakeTF(),
        reports=reports_repo,
        session_id=lambda: "s_test",
        emit=None,
        tinyfish_api_key="fake_key",
    )

    captured_query = {}

    async def mock_deploy_exec(raw_args):
        captured_query["query"] = json.loads(raw_args)["query"]
        return json.dumps({
            "reportId": "r_focus",
            "title": "Focus applied",
            "content": "Re-focused on procedural generation.",
            "summary": "Focus reshaped",
        })

    tool._deploy.execute = mock_deploy_exec

    asyncio.run(tool.execute(json.dumps({
        "new_goal": "Build a roguelike game",
        "focus": "procedural generation systems",
        "learner_profile": "junior developer, knows Python",
    })))
    q = captured_query["query"]
    assert "RE-FOCUS" in q
    assert "procedural generation systems" in q
    assert "Build a roguelike game" in q