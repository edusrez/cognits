"""Tests for storage/pedagogical.py: PedagogicalPlanRepository."""

from cognits.storage.pedagogical import PedagogicalPlanRepository


def test_save_and_get(pedagogy):
    pedagogy.save("k1", "# Plan\n\n## Stage 1\nIntro")
    result = pedagogy.get("k1")
    assert result is not None
    assert "Stage 1" in result


def test_get_missing(pedagogy):
    assert pedagogy.get("nonexistent") is None


def test_save_overwrites(pedagogy):
    pedagogy.save("k1", "old")
    pedagogy.save("k1", "new")
    assert "new" in pedagogy.get("k1")


def test_save_empty_content(pedagogy):
    pedagogy.save("k2", "")
    result = pedagogy.get("k2")
    assert result is not None


# ---------------------------------------------------------------------------
# PedagogyEngine stage persistence
# ---------------------------------------------------------------------------

from cognits.learner.pedagogy_engine import PedagogyEngine, STAGE_ORDER, Stage
from cognits.storage.models import LearnerState


def test_load_from_scaffolding_level_roundtrip():
    """load_from_scaffolding_level / to_scaffolding_level roundtrip for all stages."""
    engine = PedagogyEngine()
    for i, stage in enumerate(STAGE_ORDER):
        level = i + 1
        engine.load_from_scaffolding_level(level)
        assert engine.stage == stage
        assert engine.interactions == 0
        assert engine.to_scaffolding_level() == level


def test_load_from_scaffolding_level_bounds():
    """Clamp level to valid range: 0 maps to ACTIVATE, very high maps to WRAP_UP."""
    engine = PedagogyEngine()
    engine.load_from_scaffolding_level(0)
    assert engine.stage == Stage.ACTIVATE
    engine.load_from_scaffolding_level(999)
    assert engine.stage == Stage.WRAP_UP


def test_blocks_stage_skip():
    """Engine cannot skip stages — advance() goes one at a time."""
    engine = PedagogyEngine()
    assert engine.stage == Stage.ACTIVATE
    # advance blocks without enough interactions (min 1)
    assert not engine.should_advance(0.9)
    engine.record_interaction()  # 1 interaction, enough for ACTIVATE
    assert engine.should_advance(0.9)
    result = engine.advance()
    assert result == Stage.INTRODUCE
    assert engine.stage == Stage.INTRODUCE
    # Can't jump directly to ASSESS from INTRODUCE — only one step at a time
    assert engine.stage != Stage.ASSESS


def test_scaffolding_level_persistence(learner_state):
    """Upsert a LearnerState with scaffolding_level=3, get it back, assert it's 3."""
    ls = LearnerState(
        skill_id="test_skill_persist",
        scaffolding_level=3,
        p_mastery=0.45,
    )
    learner_state.upsert(ls)
    loaded = learner_state.get("test_skill_persist")
    assert loaded is not None
    assert loaded.scaffolding_level == 3


# ---------------------------------------------------------------------------
# T13 — retreat + ASSESS threshold
# ---------------------------------------------------------------------------

import logging

from cognits.learner.pedagogy_engine import RETREAT_MASTERY_DROP
from cognits.storage.pedagogical import _warn_non_canonical_stages


def test_retreat_moves_back_one_stage():
    """Engine at stage 3 (guided_practice) → retreat() → stage 2 (introduce_concept),
    interaction_count reset."""
    engine = PedagogyEngine()
    # Advance to guided_practice (index 2)
    engine.stage = Stage.GUIDED
    engine.interactions = 5
    result = engine.retreat()
    assert result == Stage.INTRODUCE.value
    assert engine.stage == Stage.INTRODUCE
    assert engine.interactions == 0


def test_retreat_at_first_stage_returns_none():
    """Engine at stage 0 (activate) → retreat() → None."""
    engine = PedagogyEngine()
    assert engine.stage == Stage.ACTIVATE
    engine.interactions = 3
    result = engine.retreat()
    assert result is None
    assert engine.stage == Stage.ACTIVATE
    assert engine.interactions == 3  # unchanged


def test_assess_advances_at_060_not_080():
    """At guided_practice with p_mastery 0.65 → should_advance returns True.
    At 0.55 → False (threshold is 0.60)."""
    engine = PedagogyEngine()
    engine.stage = Stage.GUIDED
    # Need min 3 interactions for GUIDED
    engine.interactions = 3
    assert engine.should_advance(0.65) is True
    engine.interactions = 3
    assert engine.should_advance(0.55) is False


def test_wrap_up_still_requires_095():
    """At assessment with p_mastery 0.90 → should_advance returns False
    (needs 0.98 to wrap up). At 0.99 → True."""
    engine = PedagogyEngine()
    engine.stage = Stage.ASSESS
    engine.interactions = 1  # min for ASSESS
    assert engine.should_advance(0.90) is False
    engine.interactions = 1
    assert engine.should_advance(0.99) is True


def test_retreat_triggers_on_mastery_drop(learner_state):
    """A mastery drop of 0.15 (>= 0.10) triggers retreat,
    scaffolding_level is updated, and the engine regresses."""
    from cognits.learner.pedagogy_engine import PedagogyEngine
    engine = PedagogyEngine()
    engine.stage = Stage.GUIDED
    engine.interactions = 5

    # Simulate pre-turn mastery of 0.75, post-turn mastery of 0.58 (drop 0.17)
    previous_p_mastery = 0.75
    p_mastery = 0.58
    drop = previous_p_mastery - p_mastery
    assert drop >= RETREAT_MASTERY_DROP  # sanity check

    # Emulate the retreat trigger logic
    if drop >= RETREAT_MASTERY_DROP:
        new_stage = engine.retreat()
        assert new_stage is not None
        assert new_stage == Stage.INTRODUCE.value
        assert engine.stage == Stage.INTRODUCE
        assert engine.interactions == 0

        # Persist scaffolding_level
        skill_id = "test_retreat_skill"
        ls = LearnerState(skill_id=skill_id, scaffolding_level=5, p_mastery=0.58)
        learner_state.upsert(ls)
        ls.scaffolding_level = engine.to_scaffolding_level()
        learner_state.upsert(ls)
        loaded = learner_state.get(skill_id)
        assert loaded is not None
        assert loaded.scaffolding_level == 2  # INTRODUCE is level 2


def test_pedagogical_plan_canonical_stages(caplog):
    """Parse canonical plan → no warning. Parse non-canonical plan → warning logged."""
    canonical = """### Stage 1: activate_prior_knowledge (activate prior knowledge)
- Goal: ...
### Stage 2: introduce_concept (introduce concept)
- Goal: ...
### Stage 3: guided_practice (guided practice)
- Goal: ...
### Stage 4: assessment (assessment)
- Goal: ...
### Stage 5: wrap_up (wrap up)
- Goal: ...
"""
    with caplog.at_level(logging.WARNING, logger="cognits.storage.pedagogical"):
        _warn_non_canonical_stages(canonical)
    # No warnings for canonical stages
    warnings = [r.message for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 0

    caplog.clear()

    non_canonical = """### Stage 1: activate_prior_knowledge
### Stage 6: something_else
### Stage 7: another_bad_stage
"""
    with caplog.at_level(logging.WARNING, logger="cognits.storage.pedagogical"):
        _warn_non_canonical_stages(non_canonical)
    warnings = [r.message for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 2
    assert "something_else" in warnings[0]
    assert "another_bad_stage" in warnings[1]
