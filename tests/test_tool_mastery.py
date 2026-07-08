"""Tests for SeedMastery tool: B4 stability initialization + basic tool behavior."""

import asyncio
import json

import pytest

from cognits.agent.tool_mastery import SeedMastery
from cognits.storage.models import Skill, LearnerState, new_skill_id


@pytest.fixture
def skill(skills):
    s = Skill(id="k_seed_stab", domain="math", name="Integration Techniques", description="Test skill")
    skills.upsert(s)
    return s


@pytest.fixture
def seed_tool(learner_state, skills):
    return SeedMastery(learner_state=learner_state, skills=skills)


def _exec(seed_tool, args_dict):
    return asyncio.run(
        seed_tool.execute(json.dumps(args_dict))
    )


# --- B4: SeedMastery stability initialization ---

def test_seed_mastery_sets_stability_high_prior(seed_tool, learner_state, skill):
    r = _exec(seed_tool, {"skill_id": skill.id, "prior": 0.96, "confidence": "diagnostic"})
    data = json.loads(r)
    assert "error" not in data

    state = learner_state.get(skill.id)
    assert state is not None
    assert state.stability == 21.0
    assert state.difficulty == 5.0
    assert state.retrievability is None


def test_seed_mastery_sets_stability_medium_prior(seed_tool, learner_state, skill):
    r = _exec(seed_tool, {"skill_id": skill.id, "prior": 0.85, "confidence": "self_report"})
    data = json.loads(r)
    assert "error" not in data

    state = learner_state.get(skill.id)
    assert state.stability == 7.0
    assert state.difficulty == 5.0


def test_seed_mastery_sets_stability_low_prior(seed_tool, learner_state, skill):
    r = _exec(seed_tool, {"skill_id": skill.id, "prior": 0.50, "confidence": "self_report"})
    data = json.loads(r)
    assert "error" not in data

    state = learner_state.get(skill.id)
    assert state.stability == 1.0
    assert state.difficulty == 5.0


def test_seed_mastery_does_not_set_last_review(seed_tool, learner_state, skill):
    _exec(seed_tool, {"skill_id": skill.id, "prior": 0.90, "confidence": "diagnostic"})
    state = learner_state.get(skill.id)
    assert state.last_review is None, "seeding is not a study event — last_review must be None"


def test_seed_mastery_does_not_set_next_review(seed_tool, learner_state, skill):
    _exec(seed_tool, {"skill_id": skill.id, "prior": 0.90, "confidence": "self_report"})
    state = learner_state.get(skill.id)
    assert state.next_review is None, "seeding is not a study event — next_review must be None"


def test_seed_mastery_sets_reps(seed_tool, learner_state, skill):
    _exec(seed_tool, {"skill_id": skill.id, "prior": 0.90, "confidence": "self_report"})
    state = learner_state.get(skill.id)
    assert state.reps >= 1, "seed_mastery forces reps >= 1"


def test_seed_mastery_computes_status(seed_tool, learner_state, skill):
    _exec(seed_tool, {"skill_id": skill.id, "prior": 0.90, "confidence": "diagnostic"})
    state = learner_state.get(skill.id)
    assert state.status_enum in ("proficient", "mastered", "practicing")
    assert state.status_enum != "not_seen"
