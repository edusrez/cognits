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
