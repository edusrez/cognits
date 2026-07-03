"""Tests for the Maestro (Teacher): session config skill_id, pedagogical
plans CRUD, save_pedagogical_plan tool, build_teacher_system_prompt,
prompt checks, and static wiring."""

import asyncio
import json

import pytest

from cognits.storage.database import Database
from cognits.storage.learner_state import LearnerStateRepository
from cognits.storage.pedagogical import PedagogicalPlanRepository
from cognits.storage.reports import ReportRepository
from cognits.storage.session_config import SessionConfigRepository
from cognits.storage.skills import SkillRepository
from cognits.storage.models import LearnerState, SessionConfigRow, Skill, new_skill_id


@pytest.fixture
def store(tmp_path):
    db = Database(tmp_path / "test.db")
    yield SkillRepository(db), LearnerStateRepository(db), SessionConfigRepository(db), PedagogicalPlanRepository(db), ReportRepository(db)
    db.shutdown()


def _skill(name="Test", domain="d"):
    return Skill(id=new_skill_id(), domain=domain, name=name, source="test", description="A test skill")


def _seed(store, *sk):
    for s in sk:
        store.upsert(s)


# --- session_config skill_id -----------------------------------------

def test_session_config_save_load_skill_id(store):
    skills, learner_state, session_config, pedagogy, reports = store
    cfg = SessionConfigRow("s1", agent_id="maestro", skill_id="k_abc")
    session_config.save(cfg)
    loaded = session_config.load("s1")
    assert loaded is not None and loaded.skill_id == "k_abc"


def test_session_config_default_skill_id_empty(store):
    skills, learner_state, session_config, pedagogy, reports = store
    cfg = SessionConfigRow("s2", agent_id="orchestrator")
    session_config.save(cfg)
    loaded = session_config.load("s2")
    assert loaded is not None and loaded.skill_id == ""


# --- pedagogical_plans CRUD ------------------------------------------

def test_pedagogical_plan_save_and_get(store):
    skills, learner_state, session_config, pedagogy, reports = store
    pedagogy.save("k_x", "# Plan\n\nStage 1")
    got = pedagogy.get("k_x")
    assert got == "# Plan\n\nStage 1"


def test_pedagogical_plan_overwrite(store):
    skills, learner_state, session_config, pedagogy, reports = store
    pedagogy.save("k_x", "Plan A")
    pedagogy.save("k_x", "Plan B")
    assert pedagogy.get("k_x") == "Plan B"


def test_pedagogical_plan_nonexistent(store):
    skills, learner_state, session_config, pedagogy, reports = store
    assert pedagogy.get("k_nonexistent") is None


# --- save_pedagogical_plan tool --------------------------------------

def test_save_pedagogical_plan_tool_persists(store):
    skills, learner_state, session_config, pedagogy, reports = store
    from cognits.agent.pedagogical_plan import SavePedagogicalPlan

    s = _skill("Variables"); _seed(skills, s)
    tool = SavePedagogicalPlan(skills=skills, pedagogy=pedagogy)
    result = asyncio.run(tool.execute(json.dumps({
        "skill_name": "Variables",
        "plan_markdown": "# Plan\n\nStage 1: hello",
    })))
    assert json.loads(result)["saved"] is True
    assert pedagogy.get(s.id) == "# Plan\n\nStage 1: hello"


def test_save_pedagogical_plan_tool_unknown_skill(store):
    skills, learner_state, session_config, pedagogy, reports = store
    from cognits.agent.pedagogical_plan import SavePedagogicalPlan

    tool = SavePedagogicalPlan(skills=skills, pedagogy=pedagogy)
    result = asyncio.run(tool.execute(json.dumps({
        "skill_name": "Nonexistent",
        "plan_markdown": "Plan",
    })))
    assert "error" in json.loads(result)


# --- _build_teacher_system_prompt ------------------------------------

def test_build_teacher_system_prompt_includes_skill_metadata(store):
    skills, learner_state, session_config, pedagogy, reports = store
    from cognits.server.routes_chat import _build_teacher_system_prompt

    s = _skill("Variables"); s.domain = "python"; s.bloom_level = "understand"
    _seed(skills, s)
    prompt = _build_teacher_system_prompt(s.id, skills, learner_state, pedagogy)
    assert "Variables" in prompt
    assert "python" in prompt
    assert "understand" in prompt


def test_build_teacher_system_prompt_includes_learner_state(store):
    skills, learner_state, session_config, pedagogy, reports = store
    from cognits.server.routes_chat import _build_teacher_system_prompt

    s = _skill("FSM"); _seed(skills, s)
    learner_state.upsert(LearnerState(skill_id=s.id, p_mastery=0.78, status_enum="practicing", reps=3))
    prompt = _build_teacher_system_prompt(s.id, skills, learner_state, pedagogy)
    assert "practicing" in prompt
    assert "0.78" in prompt
    assert "3" in prompt


def test_build_teacher_system_prompt_handles_missing_plan(store):
    skills, learner_state, session_config, pedagogy, reports = store
    from cognits.server.routes_chat import _build_teacher_system_prompt

    s = _skill("Root"); _seed(skills, s)
    prompt = _build_teacher_system_prompt(s.id, skills, learner_state, pedagogy)
    assert "No pedagogical plan available" in prompt or "Teach from your own" in prompt


def test_build_teacher_system_prompt_includes_plan_when_present(store):
    skills, learner_state, session_config, pedagogy, reports = store
    from cognits.server.routes_chat import _build_teacher_system_prompt

    s = _skill("X"); _seed(skills, s)
    pedagogy.save(s.id, "# Plan\n\nStage 1")
    prompt = _build_teacher_system_prompt(s.id, skills, learner_state, pedagogy)
    assert "# Plan" in prompt
    assert "Stage 1" in prompt


def test_build_teacher_system_prompt_includes_profile_ctx(store):
    skills, learner_state, session_config, pedagogy, reports = store
    from cognits.server.routes_chat import _build_teacher_system_prompt

    s = _skill("Y"); _seed(skills, s)
    prompt = _build_teacher_system_prompt(s.id, skills, learner_state, pedagogy, profile_ctx="Background: physics")
    assert "Background: physics" in prompt


# --- prompt / static checks ------------------------------------------

def test_teacher_in_default_agents():
    from cognits.agent.prompts import DEFAULT_AGENTS
    ids = [a["id"] for a in DEFAULT_AGENTS]
    assert "maestro" in ids


def test_teacher_prompt_includes_hint_ladder():
    from cognits.agent.prompts import TEACHER_SYSTEM_PROMPT
    assert "Hint 1" in TEACHER_SYSTEM_PROMPT or "Light" in TEACHER_SYSTEM_PROMPT
    assert "PROCTOR" in TEACHER_SYSTEM_PROMPT


def test_teacher_prompt_no_hardcoded_spanish():
    from cognits.agent.prompts import TEACHER_SYSTEM_PROMPT
    for phrase in ("He construido", "pestaña", "para comenzar"):
        assert phrase not in TEACHER_SYSTEM_PROMPT


def test_study_planner_prompt_mentions_pedagogical():
    from cognits.agent.prompts import STUDY_PLANNER_SYSTEM_PROMPT
    assert "pedagogical plan" in STUDY_PLANNER_SYSTEM_PROMPT.lower()
    assert "Capability 2" in STUDY_PLANNER_SYSTEM_PROMPT


def test_orchestrator_planning_mode_mentions_pedagogical():
    from cognits.agent.prompts import ORCHESTRATOR_SYSTEM_PROMPT
    assert "pedagogical plan" in ORCHESTRATOR_SYSTEM_PROMPT.lower()


def test_create_learning_session_emits_skill_id(store):
    skills, learner_state, session_config, pedagogy, reports = store
    from cognits.agent.tool_ui import CreateLearningSession

    s = _skill("Variables"); _seed(skills, s)
    events = []
    tool = CreateLearningSession(emit=events.append, skills=skills)
    result = asyncio.run(tool.execute(json.dumps({"skill_name": "Variables"})))
    assert json.loads(result).get("message")
    assert len(events) == 1
    assert events[0]["type"] == "create_learning_session"
    assert events[0]["data"]["skill_name"] == "Variables"
    assert events[0]["data"]["skill_id"] == s.id


def test_teacher_config_builds(store):
    skills, learner_state, session_config, pedagogy, reports = store
    from cognits.agent.subagents import teacher_config

    class FakeLLM:
        async def aclose(self): pass
        async def chat_completion_stream(self, *a, **kw): pass

    class FakeTF:
        async def aclose(self): pass

    s = _skill(); _seed(skills, s)
    cfg = teacher_config(
        model="m", reasoning="", max_steps=10,
        llm_client=FakeLLM(), rag_engine=None, tf_client=FakeTF(),
        reports=store, skills=store, learner_state=store, pedagogy=store, session_id=lambda: "s_test",
        emit=lambda e: None,
    )
    assert cfg.name == "maestro"
    tool_names = set(cfg.tools._tools.keys())
    assert "deploy_subagent" in tool_names
    assert "evaluator" in cfg.subagents
    assert "documentalist" in cfg.subagents


def test_build_teacher_system_prompt_with_real_repos(skills, learner_state, pedagogy):
    """Verify the teacher prompt assembles with real repos (not LegacyStore)."""
    from cognits.server.routes_chat import _build_teacher_system_prompt
    from cognits.storage.models import Skill, new_skill_id

    s = Skill(id=new_skill_id(), domain="test", name="Variables", description="Declaring vars")
    skills.upsert(s)
    ls = LearnerState(skill_id=s.id, p_mastery=0.85, status_enum="practicing")
    learner_state.upsert(ls)
    pedagogy.save(s.id, "# Lesson Plan\n\n## Stage 1\nIntro")

    result = _build_teacher_system_prompt(
        s.id, store=skills, learner_state=learner_state, pedagogy=pedagogy
    )
    assert "Variables" in result
    assert "Declaring vars" in result
    assert "practicing" in result
    assert "0.85" in result
    assert "Lesson Plan" in result