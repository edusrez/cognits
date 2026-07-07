"""Tests for the skill_planner subagent + skill_tree_save tool.
"""

import asyncio
import json

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


def test_subagent_labels_includes_skill_planner_and_web_researcher():
    from cognits.constants import AGENT_LABELS
    assert AGENT_LABELS.get("skill_planner") == "Skill Planner"
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
    """ed/skill ratio < 1.2 → FAIL connectivity_density."""
    skills, learner_state, db, assessment = store
    tool = SkillTreeSave(skills=skills, assessment=assessment, session_id=lambda: "s1")

    # 5 skills, chain S1→S0, S2→S1, S3→S2, S4→S3 = 4 edges, ratio=0.8 < 1.2.
    ids = []
    for name, bl in [("R", "remember"), ("U", "understand"), ("A1", "apply"),
                      ("A2", "analyze"), ("E", "evaluate")]:
        sid = json.loads(asyncio.run(tool.execute(json.dumps({
            "action": "upsert_skill", "domain": "d", "name": name,
            "bloom_level": bl,
        }))))["skill_id"]
        ids.append(sid)

    # Chain only (4 edges = 0.8 ed/skill < 1.2).
    for i in range(1, len(ids)):
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

    # Verify that connectivity_density FAILs (other criteria may pass or not,
    # but connectivity_density must be FAIL).
    assert data["passed"] is False
    dens_gap = next((g for g in data["gaps"] if g["criterion"] == "connectivity_density"), None)
    assert dens_gap is not None
    assert dens_gap["severity"] == "FAIL"
    assert "0.80" in dens_gap["current"] or "0.8" in dens_gap["current"]


def test_validate_tree_warns_on_medium_density(store):
    """1.2 ≤ ed/skill ratio < 1.5 → WARN connectivity_density, not FAIL."""
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
    assert dens_gap["severity"] == "WARN", f"Expected WARN, got {dens_gap['severity']}"
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
    size_gap = next((g for g in data["gaps"] if g["criterion"] == "size_target"), None)
    assert size_gap is not None, "Expected size_target gap"
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
    size_gap = next((g for g in data["gaps"] if g["criterion"] == "size_target"), None)
    assert size_gap is not None, "Expected size_target gap"
    depth_gap = next((g for g in data["gaps"] if g["criterion"] == "depth_target"), None)
    assert depth_gap is not None, "Expected depth_target gap"