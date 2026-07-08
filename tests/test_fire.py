"""FIRe implicit repetition credit: apply_implicit_credit + encompassing repo CRUD."""

import datetime

import pytest

from cognits.learner.fsrs import _parse_iso, retrievability
from cognits.storage.models import LearnerState, Skill, SkillEncompassing, new_skill_id
from cognits.learner.model import apply_implicit_credit


# --- helpers ------------------------------------------------------------

def _iso(dt: datetime.datetime) -> str:
    return dt.astimezone(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# --- apply_implicit_credit ---------------------------------------------

def test_apply_implicit_credit_delays_next_review():
    """Skill with low R (decaying) gets next_review delayed."""
    last = datetime.datetime(2026, 6, 20, 0, 0, 0, tzinfo=datetime.timezone.utc)
    next_rev = datetime.datetime(2026, 6, 25, 0, 0, 0, tzinfo=datetime.timezone.utc)
    # interval = 5 days, stability = 3 days, so R at next_review is low
    state = LearnerState(
        skill_id="k_decay",
        stability=3.0,
        last_review=_iso(last),
        next_review=_iso(next_rev),
        reps=3,
        p_mastery=0.85,
        alpha=10.0,
        beta=2.0,
        status_enum="proficient",
    )
    old_next = state.next_review

    apply_implicit_credit(state, encompassing_weight=0.5)

    new_next_dt = _parse_iso(state.next_review)
    old_next_dt = _parse_iso(old_next)
    assert new_next_dt is not None and old_next_dt is not None
    assert new_next_dt > old_next_dt, "next_review should be delayed by credit"


def test_apply_implicit_credit_noop_healthy_skill():
    """Healthy skill (R >= target_retention) — no credit applied."""
    last = datetime.datetime(2026, 6, 20, 0, 0, 0, tzinfo=datetime.timezone.utc)
    next_rev = datetime.datetime(2026, 6, 23, 0, 0, 0, tzinfo=datetime.timezone.utc)
    # interval = 3 days, stability = 30 days, so R stays high at next_review
    state = LearnerState(
        skill_id="k_healthy",
        stability=30.0,
        last_review=_iso(last),
        next_review=_iso(next_rev),
        reps=5,
        p_mastery=0.95,
        alpha=20.0,
        beta=1.0,
        status_enum="proficient",
    )
    old_next = state.next_review

    apply_implicit_credit(state, encompassing_weight=0.5)

    assert state.next_review == old_next, "healthy skill should not receive implicit credit"


def test_apply_implicit_credit_noop_without_stability():
    """No stability → no-op, no crash."""
    state = LearnerState(
        skill_id="k_nostab",
        last_review="2026-06-20T00:00:00Z",
        next_review="2026-06-25T00:00:00Z",
        reps=1,
    )
    old_next = state.next_review
    apply_implicit_credit(state, encompassing_weight=0.5)
    assert state.next_review == old_next, "no stability → should be no-op"


def test_apply_implicit_credit_does_not_touch_reps():
    """After credit, reps, lapses, p_mastery remain unchanged."""
    last = datetime.datetime(2026, 6, 20, 0, 0, 0, tzinfo=datetime.timezone.utc)
    next_rev = datetime.datetime(2026, 6, 25, 0, 0, 0, tzinfo=datetime.timezone.utc)
    state = LearnerState(
        skill_id="k_fire",
        stability=3.0,
        last_review=_iso(last),
        next_review=_iso(next_rev),
        reps=4,
        lapses=1,
        p_mastery=0.80,
        alpha=9.0,
        beta=2.0,
        status_enum="practicing",
    )

    apply_implicit_credit(state, encompassing_weight=0.5)

    assert state.reps == 4, "reps must not change"
    assert state.lapses == 1, "lapses must not change"
    assert state.alpha == 9.0, "alpha must not change"
    assert state.beta == 2.0, "beta must not change"
    assert state.p_mastery == 0.80, "p_mastery must not change"


def test_apply_implicit_credit_noop_without_next_review():
    """No next_review → no-op, no crash."""
    state = LearnerState(skill_id="k_nonnext", reps=2)
    apply_implicit_credit(state, encompassing_weight=0.5)
    assert state.next_review is None


def test_apply_implicit_credit_noop_with_zero_interval():
    """Zero interval (next = last) → no-op."""
    same = datetime.datetime(2026, 6, 20, 0, 0, 0, tzinfo=datetime.timezone.utc)
    state = LearnerState(
        skill_id="k_zero",
        stability=3.0,
        last_review=_iso(same),
        next_review=_iso(same),
        reps=2,
    )
    apply_implicit_credit(state, encompassing_weight=0.5)
    assert state.next_review == _iso(same)


# --- Encompassing repo CRUD (integration with DB) -----------------------

@pytest.fixture
def skill_a(skills):
    s = Skill(id="k_enc_a", domain="math", name="Add Fractions", description="Simple fractions")
    skills.upsert(s)
    return s


@pytest.fixture
def skill_b(skills):
    s = Skill(id="k_enc_b", domain="math", name="Multiply Fractions", description="Advanced fractions")
    skills.upsert(s)
    return s


def test_encompassing_repo_crud(skills, skill_a, skill_b):
    skills.add_encompassing(skill_b.id, skill_a.id, weight=0.7)

    encs = skills.get_encompassings(skill_b.id)
    assert len(encs) == 1
    assert encs[0].skill_id == skill_b.id
    assert encs[0].encompasses_skill_id == skill_a.id
    assert encs[0].weight == 0.7

    parents = skills.get_encompassing_parents(skill_a.id)
    assert len(parents) == 1
    assert parents[0].skill_id == skill_b.id

    skills.delete_encompassing(skill_b.id, skill_a.id)
    encs = skills.get_encompassings(skill_b.id)
    assert len(encs) == 0


def test_add_encompassing_upserts(skills, skill_a, skill_b):
    skills.add_encompassing(skill_b.id, skill_a.id, weight=0.5)
    skills.add_encompassing(skill_b.id, skill_a.id, weight=0.3)

    encs = skills.get_encompassings(skill_b.id)
    assert len(encs) == 1
    assert encs[0].weight == 0.3
