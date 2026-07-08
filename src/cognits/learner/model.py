"""Learner model — Beta-Bernoulli BKT (soft evidence) + FSRS-6 (spaced
repetition) integration. Six mastery levels combine the two: BKT proposes a
level from p_mastery and evidence count; FSRS modulates via retrievability
and overdue detection.

All functions are pure with respect to wall-clock time: the caller passes
``now_iso`` explicitly so tests can use synthetic clocks. ``LearnerState``
is mutated IN PLACE (mirrors the codebase's general style — the caller
persists via ``ReportStore.upsert_learner_state``).

Algorithm reference: open-spaced-repetition/fsrs-rs (Anki 24.11 defaults).
Soft-evidence Beta update via pseudo-counts (Cen et al. 2006, "Learning
Factors Analysis").
"""

from __future__ import annotations

import datetime
import random

from cognits.learner import fsrs
from cognits.storage.models import LearnerState
from cognits.constants import (
    BKT_EVIDENCE_THRESHOLD,
    BKT_LAMBDA_HINT,
    BKT_LAMBDA_TIME,
    BKT_PRIOR_ALPHA,
    BKT_PRIOR_BETA,
    MASTERY_DECAY_OVERDUE_FACTOR,
    MASTERY_EXPLORING_P,
    MASTERY_MASTERED_CONFIDENCE,
    MASTERY_MASTERED_RETENTION,
    MASTERY_PRACTICING_MIN_REPS,
    MASTERY_PROFICIENT_CONFIDENCE,
    MASTERY_PROFICIENT_P,
    MASTERY_THRESHOLD as MASTERED_P,
    STABILITY_MASTERED_MIN_DAYS,
)

# --- BKT prior / soft-evidence constants -------------------------------
PRIOR_ALPHA = BKT_PRIOR_ALPHA
PRIOR_BETA = BKT_PRIOR_BETA
LAMBDA_HINT = BKT_LAMBDA_HINT      # per hint used
LAMBDA_TIME = BKT_LAMBDA_TIME      # per unit of time_ratio above 1.0
EVIDENCE_THRESHOLD = BKT_EVIDENCE_THRESHOLD  # α+β below this -> low-confidence estimate

# --- Mastery thresholds (six levels) ----------------------------------
# Ladder (top to bottom of certainty): not_seen -> exploring -> practicing
# -> proficient -> mastered -> decaying (decaying overlays mastered/
# proficient when the FSRS schedule says the review is overdue).
EXPLORING_P = MASTERY_EXPLORING_P          # p < this           -> exploring
PRACTICING_MIN_REPS = MASTERY_PRACTICING_MIN_REPS         # reps < this           -> practicing
PROFICIENT_P = MASTERY_PROFICIENT_P          # p < this           -> not yet proficient
PROFICIENT_CONFIDENCE = MASTERY_PROFICIENT_CONFIDENCE   # α + β below this       -> practicing
MASTERED_CONFIDENCE = MASTERY_MASTERED_CONFIDENCE     # α + β below this       -> proficient
MASTERED_RETENTION = MASTERY_MASTERED_RETENTION    # post-review R below this -> not mastered
DECAY_OVERDUE_FACTOR = MASTERY_DECAY_OVERDUE_FACTOR   # elapsed > next_review * 1.5 -> decaying



def _clamp01(x: float) -> float:
    return 0.0 if x < 0.0 else 1.0 if x > 1.0 else x


def update_mastery(
    state: LearnerState,
    correctness: float,
    hints_used: int = 0,
    time_ratio: float = 1.0,
    confidence: float = 1.0,
    weight: float = 1.0,
) -> None:
    """Bayesian conjugate update of a Beta(α, β) skill-state.

    Binary case (``weight=1, confidence=1, hints_used=0, time_ratio=1``):
    the textbook update ``α += obs; β += 1 - obs`` with ``obs = correctness``
    (which is then in {0, 1}).

    Soft evidence: an evaluator reports a continuous ``correctness ∈ [0, 1]``,
    optionally penalised by hint usage and excessive time-on-task, with a
    per-judgement ``confidence ∈ (0, 1]`` weighting how many pseudo-counts
    the observation contributes. The weighted effective observation is:

        c_adj = clamp(correctness - λ_hint·hints - λ_time·(time_ratio - 1)⁺, 0, 1)
        w_eff = weight · confidence
        α += c_adj · w_eff
        β += (1 - c_adj) · w_eff

    This preserves the Beta conjugacy (it's the "fractional Bayesian update"
    of Cen et al. 2006) and ``α + β`` remains the total evidence count.
    """
    c_adj = correctness - LAMBDA_HINT * max(hints_used, 0)
    c_adj -= LAMBDA_TIME * max(time_ratio - 1.0, 0.0)
    c_adj = _clamp01(c_adj)
    w_eff = max(0.0, weight) * max(0.0, min(confidence, 1.0))
    state.alpha += c_adj * w_eff
    state.beta += (1.0 - c_adj) * w_eff
    state.p_mastery = state.alpha / (state.alpha + state.beta)


def mastery_level(
    state: LearnerState,
    now_iso: str,
) -> str:
    """Six-level mastery classifier.

    Levels: ``not_seen`` → ``exploring`` → ``practicing`` → ``proficient``
    → ``mastered`` → ``decaying``. The decay check runs first: if the
    previous status already indicated proficiency and the FSRS schedule
    says the review is overdue past ``next_review * DECAY_OVERDUE_FACTOR``,
    the level drops to ``decaying`` (the skill is decaying even though the
    learner once had it).
    """
    if state.reps == 0:
        return "not_seen"

    p = state.p_mastery
    conf = state.alpha + state.beta
    now_dt = fsrs._parse_iso(now_iso)
    last_dt = fsrs._parse_iso(state.last_review)
    next_dt = fsrs._parse_iso(state.next_review)

    # Decay check: previously proficient/mastered, now overdue past
    # (DECAY_OVERDUE_FACTOR - 1.0) × next_review interval.
    if state.status_enum in ("proficient", "mastered") and now_dt and next_dt:
        planned_interval = _next_review_days(state)
        overdue = (now_dt - next_dt).total_seconds() / 86400.0
        if overdue > planned_interval * (DECAY_OVERDUE_FACTOR - 1.0):
            return "decaying"

    # Progressive thresholds.
    if p < EXPLORING_P:
        return "exploring"
    # Not enough reps yet, or not enough evidence, to claim proficiency.
    if state.reps < PRACTICING_MIN_REPS or conf < PROFICIENT_CONFIDENCE:
        return "practicing"
    if p < PROFICIENT_P:
        return "proficient"
    # Retention gate: post-review R must still be ≥ MASTERED_RETENTION.
    r_now = 1.0
    if state.stability and last_dt and now_dt:
        elapsed = max(0.0, (now_dt - last_dt).total_seconds() / 86400.0)
        r_now = fsrs.retrievability(elapsed, state.stability)
    if p < MASTERED_P or conf < MASTERED_CONFIDENCE or r_now < MASTERED_RETENTION:
        return "proficient"
    # M7: Stability gate — memory must be durable (not just-learned).
    # A skill with high p_mastery but low stability is "proficient", not "mastered".
    if state.stability is not None and state.stability < STABILITY_MASTERED_MIN_DAYS:
        return "proficient"
    return "mastered"


def _next_review_days(state: LearnerState) -> float:
    """How many days from last_review to next_review, as stored. Used by
    the decay overdue check. Falls back to stability if either timestamp
    is missing."""
    last_dt = fsrs._parse_iso(state.last_review)
    next_dt = fsrs._parse_iso(state.next_review)
    if last_dt and next_dt:
        return (next_dt - last_dt).total_seconds() / 86400.0
    return state.stability or 1.0


def record_review(
    state: LearnerState,
    correctness: float,
    rating: int,
    now_iso: str,
    hints_used: int = 0,
    time_ratio: float = 1.0,
    confidence: float = 1.0,
    desired_retention: float = fsrs.DESIRED_RETENTION_DEFAULT,
    rng: random.Random | None = None,
) -> LearnerState:
    """Apply one review: FSRS update first, then BKT, then recompute status.

    The order matches IntelliCode's (Khan-inspired) pattern: FSRS needs
    ``rating`` and ``elapsed_days`` to update S/D; BKT then folds the
    continuous ``correctness`` into α/β; finally ``mastery_level`` derives
    the discrete status. All fields are written by the time this returns.

    ``rating`` is MANDATORY (1..4) and is produced by the evaluator agent.
    This function deliberately does NOT map ``correctness`` to ``rating``
    — the decision "was this response Good or Hard?" requires the
    evaluator's semantic judgement, not a hand-tuned threshold.

    ``now_iso`` is the absolute review timestamp (ISO-8601, UTC + 'Z').
    The function is deterministic w.r.t. its arguments when ``rng=None``
    (fuzz disabled).
    """
    last_dt = fsrs._parse_iso(state.last_review)
    now_dt = fsrs._parse_iso(now_iso) or datetime.datetime.now(datetime.timezone.utc)
    if last_dt is None:
        elapsed_days = 0.0
    else:
        elapsed_days = max(0.0, (now_dt - last_dt).total_seconds() / 86400.0)

    # 1. FSRS step (mutates S, D, reps, lapses, next_review, retrievability).
    fsrs.step_review(
        state,
        rating=rating,
        elapsed_days=elapsed_days,
        nth_review=state.reps,
        now_iso=now_iso,
        desired_retention=desired_retention,
        rng=rng,
    )

    # 2. BKT soft-evidence update (mutates alpha, beta, p_mastery).
    update_mastery(
        state,
        correctness=correctness,
        hints_used=hints_used,
        time_ratio=time_ratio,
        confidence=confidence,
    )

    # 3. Status recompute (mutates status_enum).
    state.status_enum = mastery_level(state, now_iso)
    state.last_review = now_dt.astimezone(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    state.updated_at = state.last_review

    return state


def apply_implicit_credit(
    state: LearnerState,
    encompassing_weight: float,
    target_retention: float = 0.9,
    cap_fraction: float = 0.5,
) -> LearnerState:
    """Apply implicit repetition credit from FIRe (approximation).

    Only applies if R < target_retention (skill is decaying).
    Caps the credit at cap_fraction of the current review interval.
    Does NOT increment reps, lapses, or set last_review (not a real review).
    Only delays next_review.
    """
    if state.stability is None or state.next_review is None or state.last_review is None:
        return state

    last_dt = fsrs._parse_iso(state.last_review)
    next_dt = fsrs._parse_iso(state.next_review)
    if last_dt is None or next_dt is None:
        return state

    current_interval = (next_dt - last_dt).total_seconds() / 86400.0
    if current_interval <= 0:
        return state

    elapsed = current_interval  # at next_review time, elapsed = interval
    r = fsrs.retrievability(elapsed, state.stability)
    if r >= target_retention:
        return state  # skill is healthy at next_review, no credit needed

    # Delay next_review by cap_fraction * current_interval * weight
    credit_days = current_interval * cap_fraction * encompassing_weight
    new_next = next_dt + datetime.timedelta(days=credit_days)
    state.next_review = new_next.isoformat()
    # Do NOT touch stability, difficulty, reps, lapses, alpha, beta, p_mastery
    return state