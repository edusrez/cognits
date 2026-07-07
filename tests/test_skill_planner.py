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
from cognits.storage.models import Skill, new_skill_id
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
    """A clean tree: every skill has ≥1 item, apply≤35%, proof_query 100%,
    no orphans, acyclic → passed=true, no FAIL gaps."""
    skills, learner_state, db, assessment = store
    tool = SkillTreeSave(skills=skills, assessment=assessment, session_id=lambda: "s1")

    # Create 2 skills (non-apply), connected with proof_query.
    a_id = json.loads(asyncio.run(tool.execute(json.dumps({
        "action": "upsert_skill", "domain": "d", "name": "Root",
        "bloom_level": "understand",
    }))))["skill_id"]
    b_id = json.loads(asyncio.run(tool.execute(json.dumps({
        "action": "upsert_skill", "domain": "d", "name": "Child",
        "bloom_level": "analyze",
    }))))["skill_id"]

    # Connect B → A with proof_query.
    asyncio.run(tool.execute(json.dumps({
        "action": "add_edge", "skill_id": b_id, "prereq_id": a_id,
        "edge_type": "prereq", "proof_query": "child needs root",
    })))

    # Add ≥1 assessment item to each.
    for sid in (a_id, b_id):
        asyncio.run(tool.execute(json.dumps({
            "action": "save_assessment_items",
            "skill_id": sid,
            "items": [{"question": "Q", "expected_answer": "A", "rubric": "R",
                       "question_type": "open", "blooms_level": "remember",
                       "difficulty": 0.5, "generation_model": "test"}],
        })))

    result = asyncio.run(tool.execute(json.dumps({"action": "validate_tree"})))
    data = json.loads(result)

    assert data["passed"] is True
    assert "PASS" in data["summary"]
    assert data["counts"]["skills"] == 2
    assert data["counts"]["edges"] == 1
    assert data["counts"]["items"] == 2
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
    assert "bloom_apply" in data["summary"]

    bloom_gap = next(g for g in data["gaps"] if g["criterion"] == "bloom_apply")
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

    # 2 skills with non-apply bloom, connected with proof_query.
    a_id = json.loads(asyncio.run(tool.execute(json.dumps({
        "action": "upsert_skill", "domain": "d", "name": "SkillA",
        "bloom_level": "understand",
    }))))["skill_id"]
    b_id = json.loads(asyncio.run(tool.execute(json.dumps({
        "action": "upsert_skill", "domain": "d", "name": "SkillB",
        "bloom_level": "analyze",
    }))))["skill_id"]
    asyncio.run(tool.execute(json.dumps({
        "action": "add_edge", "skill_id": b_id, "prereq_id": a_id,
        "edge_type": "prereq", "proof_query": "b needs a",
    })))

    # Add ONE good item to skill_a, one low-quality item to skill_b.
    asyncio.run(tool.execute(json.dumps({
        "action": "save_assessment_items",
        "skill_id": a_id,
        "items": [{"question": "A real question that is long enough to pass",
                   "expected_answer": "Some answer", "rubric": "Grading guide",
                   "question_type": "open", "blooms_level": "remember",
                   "difficulty": 0.5, "generation_model": "test"}],
    })))
    asyncio.run(tool.execute(json.dumps({
        "action": "save_assessment_items",
        "skill_id": b_id,
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
    assert b_id in data["low_quality_skill_ids"]


def test_validate_tree_warns_on_bloom_over_conversion(store):
    """analyze > 40% triggers a WARN (bloom_balance_overall) but does NOT
    block passed. Tests the cross-check that prevents over-conversion
    from apply->analyze."""
    skills, learner_state, db, assessment = store
    tool = SkillTreeSave(skills=skills, assessment=assessment, session_id=lambda: "s1")

    # 10 skills: 3 understand, 5 analyze (50% > 40%), 2 evaluate
    # apply% = 0% so it doesn't trigger a FAIL.
    ids = []
    blooms = ["understand"] * 3 + ["analyze"] * 5 + ["evaluate"] * 2
    for i, bl in enumerate(blooms):
        sid = json.loads(asyncio.run(tool.execute(json.dumps({
            "action": "upsert_skill", "domain": "d", "name": f"S{i}",
            "bloom_level": bl,
        }))))["skill_id"]
        ids.append(sid)

    # Chain them acyclically, all with proof_query.
    for i in range(1, len(ids)):
        asyncio.run(tool.execute(json.dumps({
            "action": "add_edge", "skill_id": ids[i], "prereq_id": ids[i - 1],
            "edge_type": "prereq", "proof_query": f"pq_{i}",
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
    assert "analyze=50" in bloom_gap["current"] or "analyze=50" in bloom_gap["current"].replace(".0%", ""), (
        f"Expected analyze=50% in current, got: {bloom_gap['current']}"
    )