"""Tests for LearnerStateRepository: upsert, get, get_all."""

from cognits.storage.models import LearnerState


def test_upsert_creates(learner_state):
    st = LearnerState(skill_id="k1", p_mastery=0.3, status_enum="exploring")
    learner_state.upsert(st)
    result = learner_state.get("k1")
    assert result is not None
    assert result.p_mastery == 0.3
    assert result.status_enum == "exploring"


def test_upsert_updates(learner_state):
    learner_state.upsert(LearnerState(skill_id="k2", p_mastery=0.1))
    learner_state.upsert(LearnerState(skill_id="k2", p_mastery=0.9, reps=5))
    result = learner_state.get("k2")
    assert result.p_mastery == 0.9
    assert result.reps == 5


def test_get_missing(learner_state):
    assert learner_state.get("nonexistent") is None


def test_get_all(learner_state):
    learner_state.upsert(LearnerState(skill_id="a", p_mastery=0.1))
    learner_state.upsert(LearnerState(skill_id="b", p_mastery=0.9))
    all_states = learner_state.get_all()
    assert len(all_states) >= 2
    assert all_states["a"].p_mastery == 0.1
    assert all_states["b"].p_mastery == 0.9


def test_scaffolding_level_default(learner_state):
    learner_state.upsert(LearnerState(skill_id="k3", p_mastery=0.5))
    result = learner_state.get("k3")
    assert result.scaffolding_level == 1
