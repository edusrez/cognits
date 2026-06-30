"""Tests for the Maestro (Teacher): session config skill_id, pedagogical
plans CRUD, save_pedagogical_plan tool, build_teacher_system_prompt,
prompt checks, and static wiring."""

import asyncio
import json

import pytest

from cognits.storage.db import LearnerState, ReportStore, SessionConfigRow, Skill, new_skill_id


@pytest.fixture
def store(tmp_path):
    rs = ReportStore(tmp_path / "test.db")
    yield rs
    rs.close()


def _skill(name="Test", domain="d"):
    return Skill(id=new_skill_id(), domain=domain, name=name, source="test", description="A test skill")


def _seed(store, *skills):
    for s in skills:
        store.upsert_skill(s)


# --- session_config skill_id -----------------------------------------

def test_session_config_save_load_skill_id(store):
    cfg = SessionConfigRow("s1", agent_id="maestro", skill_id="k_abc")
    store.save_session_config(cfg)
    loaded = store.load_session_config("s1")
    assert loaded is not None and loaded.skill_id == "k_abc"


def test_session_config_default_skill_id_empty(store):
    cfg = SessionConfigRow("s2", agent_id="orchestrator")
    store.save_session_config(cfg)
    loaded = store.load_session_config("s2")
    assert loaded is not None and loaded.skill_id == ""


# --- pedagogical_plans CRUD ------------------------------------------

def test_pedagogical_plan_save_and_get(store):
    store.save_pedagogical_plan("k_x", "# Plan\n\nStage 1")
    got = store.get_pedagogical_plan("k_x")
    assert got == "# Plan\n\nStage 1"


def test_pedagogical_plan_overwrite(store):
    store.save_pedagogical_plan("k_x", "Plan A")
    store.save_pedagogical_plan("k_x", "Plan B")
    assert store.get_pedagogical_plan("k_x") == "Plan B"


def test_pedagogical_plan_nonexistent(store):
    assert store.get_pedagogical_plan("k_nonexistent") is None


# --- save_pedagogical_plan tool --------------------------------------

def test_save_pedagogical_plan_tool_persists(store):
    from cognits.agent.pedagogical_plan import SavePedagogicalPlan

    s = _skill("Variables"); _seed(store, s)
    tool = SavePedagogicalPlan(report_store=store)
    result = asyncio.run(tool.execute(json.dumps({
        "skill_name": "Variables",
        "plan_markdown": "# Plan\n\nStage 1: hello",
    })))
    assert json.loads(result)["saved"] is True
    assert store.get_pedagogical_plan(s.id) == "# Plan\n\nStage 1: hello"


def test_save_pedagogical_plan_tool_unknown_skill(store):
    from cognits.agent.pedagogical_plan import SavePedagogicalPlan

    tool = SavePedagogicalPlan(report_store=store)
    result = asyncio.run(tool.execute(json.dumps({
        "skill_name": "Nonexistent",
        "plan_markdown": "Plan",
    })))
    assert "error" in json.loads(result)


# --- _build_teacher_system_prompt ------------------------------------

def test_build_teacher_system_prompt_includes_skill_metadata(store):
    from cognits.server.routes_chat import _build_teacher_system_prompt

    s = _skill("Variables"); s.domain = "python"; s.bloom_level = "understand"
    _seed(store, s)
    prompt = _build_teacher_system_prompt(s.id, store)
    assert "Variables" in prompt
    assert "python" in prompt
    assert "understand" in prompt


def test_build_teacher_system_prompt_includes_learner_state(store):
    from cognits.server.routes_chat import _build_teacher_system_prompt

    s = _skill("FSM"); _seed(store, s)
    store.upsert_learner_state(LearnerState(skill_id=s.id, p_mastery=0.78, status_enum="practicing", reps=3))
    prompt = _build_teacher_system_prompt(s.id, store)
    assert "practicing" in prompt
    assert "0.78" in prompt
    assert "3" in prompt


def test_build_teacher_system_prompt_handles_missing_plan(store):
    from cognits.server.routes_chat import _build_teacher_system_prompt

    s = _skill("Root"); _seed(store, s)
    prompt = _build_teacher_system_prompt(s.id, store)
    assert "No pedagogical plan available" in prompt or "Teach from your own" in prompt


def test_build_teacher_system_prompt_includes_plan_when_present(store):
    from cognits.server.routes_chat import _build_teacher_system_prompt

    s = _skill("X"); _seed(store, s)
    store.save_pedagogical_plan(s.id, "# Plan\n\nStage 1")
    prompt = _build_teacher_system_prompt(s.id, store)
    assert "# Plan" in prompt
    assert "Stage 1" in prompt


def test_build_teacher_system_prompt_includes_profile_ctx(store):
    from cognits.server.routes_chat import _build_teacher_system_prompt

    s = _skill("Y"); _seed(store, s)
    prompt = _build_teacher_system_prompt(s.id, store, profile_ctx="Background: physics")
    assert "Background: physics" in prompt


# --- prompt / static checks ------------------------------------------

def test_teacher_in_default_agents():
    from cognits.agent.prompts import DEFAULT_AGENTS
    ids = [a["id"] for a in DEFAULT_AGENTS]
    assert "maestro" in ids


def test_teacher_prompt_includes_hint_ladder():
    from cognits.agent.subagents import TEACHER_SYSTEM_PROMPT
    assert "Hint 1" in TEACHER_SYSTEM_PROMPT or "Light" in TEACHER_SYSTEM_PROMPT
    assert "PROCTOR" in TEACHER_SYSTEM_PROMPT


def test_teacher_prompt_no_hardcoded_spanish():
    from cognits.agent.subagents import TEACHER_SYSTEM_PROMPT
    for phrase in ("He construido", "pestaña", "para comenzar"):
        assert phrase not in TEACHER_SYSTEM_PROMPT


def test_study_planner_prompt_mentions_pedagogical():
    from cognits.agent.subagents import STUDY_PLANNER_SYSTEM_PROMPT
    assert "pedagogical plan" in STUDY_PLANNER_SYSTEM_PROMPT.lower()
    assert "Capability 2" in STUDY_PLANNER_SYSTEM_PROMPT


def test_orchestrator_planning_mode_mentions_pedagogical():
    from cognits.agent.prompts import ORCHESTRATOR_SYSTEM_PROMPT
    assert "pedagogical plan" in ORCHESTRATOR_SYSTEM_PROMPT.lower()


def test_create_learning_session_emits_skill_id(store):
    from cognits.agent.tool_ui import CreateLearningSession

    s = _skill("Variables"); _seed(store, s)
    events = []
    tool = CreateLearningSession(emit=events.append, report_store=store)
    result = asyncio.run(tool.execute(json.dumps({"skill_name": "Variables"})))
    assert json.loads(result).get("message")
    assert len(events) == 1
    assert events[0]["type"] == "create_learning_session"
    assert events[0]["data"]["skill_name"] == "Variables"
    assert events[0]["data"]["skill_id"] == s.id


def test_teacher_config_builds(store):
    from cognits.agent.subagents import teacher_config

    class FakeLLM:
        async def aclose(self): pass
        async def chat_completion_stream(self, *a, **kw): pass

    class FakeTF:
        async def aclose(self): pass

    s = _skill(); _seed(store, s)
    cfg = teacher_config(
        model="m", reasoning="", max_steps=10,
        llm_client=FakeLLM(), rag_engine=None, tf_client=FakeTF(),
        report_store=store, session_id=lambda: "s_test",
        emit=lambda e: None,
    )
    assert cfg.name == "maestro"
    tool_names = set(cfg.tools._tools.keys())
    assert "deploy_subagent" in tool_names
    assert "evaluator" in cfg.subagents
    assert "documentalist" in cfg.subagents