"""Tests for agent/pedagogical_plan.py: SavePedagogicalPlan tool."""

import asyncio
import json

import pytest

from cognits.storage.database import Database
from cognits.storage.pedagogical import PedagogicalPlanRepository
from cognits.storage.skills import SkillRepository
from cognits.storage.models import Skill, new_skill_id


@pytest.fixture
def store(tmp_path):
    db = Database(tmp_path / "test.db")
    yield SkillRepository(db), PedagogicalPlanRepository(db)
    db.shutdown()


def _skill(name="Test", domain="d"):
    return Skill(id=new_skill_id(), domain=domain, name=name, source="test",
                 description="A test skill")


def _seed(skills, *sk):
    for s in sk:
        skills.upsert(s)


# --- save_pedagogical_plan tool (fuzzy matching) -----------------------

def test_save_pedagogical_plan_exact_match(store):
    skills, pedagogy = store
    from cognits.agent.pedagogical_plan import SavePedagogicalPlan

    s = _skill("Variables"); _seed(skills, s)
    tool = SavePedagogicalPlan(skills=skills, pedagogy=pedagogy)
    result = asyncio.run(tool.execute(json.dumps({
        "skill_name": "Variables",
        "plan_markdown": "# Plan\n\nStage 1: hello",
    })))
    assert json.loads(result)["saved"] is True
    assert pedagogy.get(s.id) == "# Plan\n\nStage 1: hello"


def test_save_pedagogical_plan_case_insensitive(store):
    skills, pedagogy = store
    from cognits.agent.pedagogical_plan import SavePedagogicalPlan

    s = _skill("Variables"); _seed(skills, s)
    tool = SavePedagogicalPlan(skills=skills, pedagogy=pedagogy)
    result = asyncio.run(tool.execute(json.dumps({
        "skill_name": "variables",
        "plan_markdown": "plan",
    })))
    assert json.loads(result)["saved"] is True


def test_save_pedagogical_plan_contains_match(store):
    skills, pedagogy = store
    from cognits.agent.pedagogical_plan import SavePedagogicalPlan

    s = _skill("GDScript Fundamentals"); _seed(skills, s)
    tool = SavePedagogicalPlan(skills=skills, pedagogy=pedagogy)
    result = asyncio.run(tool.execute(json.dumps({
        "skill_name": "gdscript",
        "plan_markdown": "plan",
    })))
    assert json.loads(result)["saved"] is True


def test_save_pedagogical_plan_levenshtein_match(store):
    skills, pedagogy = store
    from cognits.agent.pedagogical_plan import SavePedagogicalPlan

    s = _skill("Variables"); _seed(skills, s)
    tool = SavePedagogicalPlan(skills=skills, pedagogy=pedagogy)
    result = asyncio.run(tool.execute(json.dumps({
        "skill_name": "Variabls",
        "plan_markdown": "plan",
    })))
    assert json.loads(result)["saved"] is True


def test_save_pedagogical_plan_no_match(store):
    skills, pedagogy = store
    from cognits.agent.pedagogical_plan import SavePedagogicalPlan

    s = _skill("Variables"); _seed(skills, s)
    tool = SavePedagogicalPlan(skills=skills, pedagogy=pedagogy)
    result = asyncio.run(tool.execute(json.dumps({
        "skill_name": "CompletelyUnrelated",
        "plan_markdown": "plan",
    })))
    assert "error" in json.loads(result)
