"""Learner model: BKT (Beta-Bernoulli soft evidence) + FSRS-6 integration.

Tests use synthetic ``now_iso`` timestamps so the FSRS schedule is fully
deterministic. No DB I/O — everything operates on a bare ``LearnerState``
memory view.
"""

import datetime
import math
import random

import pytest

from cognits.learner import (
    DECAY,
    DEFAULT_PARAMS,
    apply_fuzz,
    init_difficulty,
    init_stability,
    mastery_level,
    next_interval,
    record_review,
    retrievability,
    update_mastery,
)
from cognits.learner.fsrs import _parse_iso
from cognits.storage.models import LearnerState


# --- BKT: conjugate beta update --------------------------------------

def test_bkt_binary_conjugate():
    st = LearnerState(skill_id="k1")          # Beta(1, 1), p=0.5, conf=2
    for _ in range(4):
        update_mastery(st, correctness=1.0)  # 4 binary successes
    assert st.alpha == pytest.approx(5.0)
    assert st.beta == pytest.approx(1.0)
    assert st.p_mastery == pytest.approx(5.0 / 6.0)   # ≈ 0.833
    assert st.alpha + st.beta == pytest.approx(6.0)


def test_bkt_binary_failure_increments_beta():
    st = LearnerState(skill_id="k1")
    update_mastery(st, correctness=0.0)
    assert st.alpha == pytest.approx(1.0)
    assert st.beta == pytest.approx(2.0)
    assert st.p_mastery == pytest.approx(1.0 / 3.0)


def test_bkt_soft_evidence_with_hints_reduces_alpha_gain():
    plain = LearnerState(skill_id="a")
    hints = LearnerState(skill_id="b")
    update_mastery(plain, correctness=1.0)
    update_mastery(hints, correctness=1.0, hints_used=3)
    # hints_used=3 -> λ_hint·3 = 0.45 -> c_adj = 0.55
    # α_plain += 1.0 ; α_hints += 0.55
    assert plain.alpha > hints.alpha
    assert hints.alpha == pytest.approx(1.55)


def test_bkt_soft_evidence_time_penalty():
    st = LearnerState(skill_id="k")
    update_mastery(st, correctness=1.0, time_ratio=3.0)   # +200% over time
    # λ_time · (3 - 1) = 0.20 -> c_adj = 0.80
    assert st.alpha == pytest.approx(1.80)


def test_bkt_confidence_weights_pseudo_counts():
    hi = LearnerState(skill_id="hi")
    lo = LearnerState(skill_id="lo")
    update_mastery(hi, correctness=1.0, confidence=1.0)
    update_mastery(lo, correctness=1.0, confidence=0.25)
    assert hi.alpha == pytest.approx(2.0)
    assert lo.alpha == pytest.approx(1.25)   # +0.25


# --- Cold-start -----------------------------------------------------

def test_cold_start_prior():
    st = LearnerState(skill_id="k")
    assert st.alpha == 1.0 and st.beta == 1.0
    assert st.p_mastery == 0.5
    assert st.alpha + st.beta == 2.0
    assert mastery_level(st, "2026-06-29T00:00:00Z") == "not_seen"


# --- FSRS-6: pure numeric functions ---------------------------------

def test_fsrs_init_values_for_rating_3():
    s0 = init_stability(3)
    d0 = init_difficulty(3)
    assert s0 == pytest.approx(DEFAULT_PARAMS[2])           # 2.3065
    assert d0 == pytest.approx(
        DEFAULT_PARAMS[4] - math.exp(DEFAULT_PARAMS[5] * 2.0) + 1.0
    )


def test_fsrs_retrievability_at_stability_is_0_9():
    S = 7.0
    r = retrievability(S, S)                                # Δt == S
    assert abs(r - 0.9) < 1e-6


def test_fsrs_retrievability_zero_elapsed_is_one():
    assert retrievability(0.0, stability=5.0) == 1.0


def test_fsrs_next_interval_inverts_retrievability():
    S = 10.0
    interval = next_interval(S, desired_retention=0.9)
    # Re-deriving R at that interval should give back ~0.9.
    r = retrievability(interval, S)
    assert abs(r - 0.9) < 1e-6


def test_apply_fuzz_no_rng_is_deterministic():
    assert apply_fuzz(10.0, rng=None) == 10
    assert apply_fuzz(1.5, rng=None) == 2
    assert apply_fuzz(0.2, rng=None) == 1


def test_apply_fuzz_with_rng_in_range():
    rng = random.Random(42)
    for interval in (3.0, 30.0, 365.0):
        fuzzed = apply_fuzz(interval, rng=rng)
        max_fuzz = max(1, int(interval * 0.05))
        assert round(interval) - max_fuzz <= fuzzed <= round(interval) + max_fuzz


# --- record_review: full integration --------------------------------

def test_first_review_uses_init_not_step():
    st = LearnerState(skill_id="k1")
    record_review(st, correctness=0.95, rating=3, now_iso="2026-06-29T00:00:00Z")
    # First review: S = init_stability(3), D = init_difficulty(3).
    assert st.stability == pytest.approx(DEFAULT_PARAMS[2])
    assert st.difficulty == pytest.approx(
        DEFAULT_PARAMS[4] - math.exp(DEFAULT_PARAMS[5] * 2.0) + 1.0
    )
    assert st.reps == 1 and st.lapses == 0
    assert st.next_review.startswith("2026-")
    # BKT: α = 1 + 0.95, β = 1 + 0.05 -> p ≈ 0.65
    assert st.alpha == pytest.approx(1.95)
    assert st.beta == pytest.approx(1.05)
    assert st.p_mastery == pytest.approx(1.95 / 3.0)
    # reps=1 < PRACTICING_MIN_REPS -> practicing
    assert st.status_enum == "practicing"


def test_record_review_full_cycle_fsrs_then_bkt():
    st = LearnerState(skill_id="k1")
    record_review(st, correctness=0.95, rating=3, now_iso="2026-06-29T00:00:00Z")
    # Second review two days later.
    record_review(st, correctness=1.0, rating=3, now_iso="2026-07-01T00:00:00Z")
    # reps incremented, last_review advanced, status coherent.
    assert st.reps == 2
    assert st.last_review == "2026-07-01T00:00:00Z"
    assert st.status_enum in ("practicing", "proficient")
    # FSRS stability should have moved (non-trivial update relative to init).
    assert st.stability > DEFAULT_PARAMS[2]


def test_record_review_failure_increments_lapses():
    st = LearnerState(skill_id="k")
    record_review(st, correctness=0.95, rating=3, now_iso="2026-06-29T00:00:00Z")
    # Then a failure (rating=1).
    record_review(st, correctness=0.1, rating=1, now_iso="2026-07-08T00:00:00Z")
    assert st.lapses == 1
    assert st.reps == 2
    # β grew, p_mastery dropped relative to post-first-review value.
    assert st.beta > 1.05


# --- Mastery transitions --------------------------------------------

def test_mastery_level_transitions():
    """Walk a skill from not_seen up toward mastered."""
    st = LearnerState(skill_id="k")
    # not_seen before any review.
    assert mastery_level(st, "2026-06-29T00:00:00Z") == "not_seen"
    # First review (rating=4 Easy on a near-perfect answer).
    record_review(st, correctness=1.0, rating=4, now_iso="2026-06-29T00:00:00Z")
    assert st.status_enum == "practicing"   # only 1 rep so far
    # Second through twelfth perfect Easy reviews at the scheduled interval,
    # each ~FSRS-prescribed but we approximate with 1-day spacing (fuzz off).
    now = _parse_iso("2026-06-29T00:00:00Z")
    for _ in range(19):
        now = now + datetime.timedelta(days=1)
        now_iso = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        # Drive elapsed via last_review; correctness=1, rating=4 stable growth.
        record_review(
            st, correctness=1.0, rating=4, now_iso=now_iso
        )
    # After 20 perfect reviews: α=21, β=1, p ≈ 0.955 → mastered (r_now ~ 1
    # because last_review == now).
    assert st.status_enum in ("mastered", "proficient")
    assert st.p_mastery > 0.95


def test_decaying_after_overdue():
    """A mastered skill whose FSRS schedule is overdue past 1.5× the
    planned interval drops to 'decaying'."""
    st = LearnerState(skill_id="k")
    # Force into mastered: high α, low β, plenty of reps.
    st.alpha = 50.0
    st.beta = 1.0
    st.p_mastery = 50.0 / 51.0
    st.reps = 20
    st.status_enum = "mastered"
    st.stability = 3.0
    # Set up last_review and next_review so the planned interval is clear.
    last_dt = _parse_iso("2026-01-01T00:00:00Z")
    planned_interval = next_interval(3.0, desired_retention=0.9)
    next_dt = last_dt + datetime.timedelta(days=planned_interval)
    st.last_review = last_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    st.next_review = next_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    # Advance the clock to 1 day past (DECAY_OVERDUE_FACTOR - 1) × interval.
    far_future = next_dt + datetime.timedelta(
        days=planned_interval * 0.5 + 1.0
    )
    now_iso = far_future.strftime("%Y-%m-%dT%H:%M:%SZ")
    assert mastery_level(st, now_iso) == "decaying"
    # Sanity: just barely past next_review (but not past 1.5× mark) does NOT
    # decay yet — it stays in the prior level.
    barely = next_dt + datetime.timedelta(hours=1)
    assert mastery_level(st, barely.strftime("%Y-%m-%dT%H:%M:%SZ")) != "decaying"


def _next_review_days(state) -> float:
    last = _parse_iso(state.last_review)
    nxt = _parse_iso(state.next_review)
    if last and nxt:
        return (nxt - last).total_seconds() / 86400.0
    return state.stability or 1.0