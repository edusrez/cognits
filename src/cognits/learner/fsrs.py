"""FSRS-6 spaced repetition scheduler.

Pure functions over a per-skill memory state (stability S, difficulty D).
Defaults come from Anki 24.11+ (open-spaced-repetition/fsrs-rs). The caller
owns the LearnerState dataclass and persists it; the helpers here mutate or
return scalars. No I/O, no time parsing — time enters only as
``elapsed_days`` (float) so callers can test with synthetic clocks.

Reference:
  - https://github.com/open-spaced-repetition/fsrs-rs
  - Ye et al., "A Stochastic Shortest Path Algorithm for Optimizing Spaced
    Repetition Scheduling", ACM SIGKDD 2022.
"""

from __future__ import annotations

import datetime
import math
import random

from cognits.storage.db import LearnerState

# Default 21-parameter vector shipped by Anki 24.11 (FSRS-6). Optimised over
# the anki-revlogs-10k dataset (2024). Index 20 is DECAY.
DEFAULT_PARAMS: tuple[float, ...] = (
    0.212,     # w0:  S_init for Again (rating=1)
    1.2931,    # w1:  S_init for Hard  (rating=2)
    2.3065,    # w2:  S_init for Good  (rating=3)
    8.2956,    # w3:  S_init for Easy  (rating=4)
    6.4133,    # w4:  D_init base
    0.8334,    # w5:  D_init multiplier
    3.0194,    # w6:  D delta multiplier
    0.001,     # w7:  mean reversion factor
    1.8722,    # w8:  S_success additive factor
    0.1666,    # w9:  S_success exponent on S
    0.796,     # w10: S_success factor on R
    1.4835,    # w11: S_failure multiplier
    0.0614,    # w12: S_failure exponent on D
    0.2629,    # w13: S_failure exponent on S
    1.6483,    # w14: S_failure factor on R
    0.6014,    # w15: Hard penalty multiplier
    1.8729,    # w16: Easy bonus multiplier
    0.5425,    # w17: short-term S factor
    0.0912,    # w18: short-term S rating shift
    0.0658,    # w19: short-term S exponent
    0.1542,    # w20: DECAY (forgetting curve exponent; used as POSITIVE here)
)

DECAY: float = DEFAULT_PARAMS[20]
S_MIN: float = 0.001
S_MAX: float = 36500.0
D_MIN: float = 1.0
D_MAX: float = 10.0
DESIRED_RETENTION_DEFAULT: float = 0.9


def _clamp(x: float, lo: float, hi: float) -> float:
    return lo if x < lo else hi if x > hi else x


def _parse_iso(s: str | None) -> datetime.datetime | None:
    """Parse an ISO-8601 timestamp (UTC, suffixed with 'Z') into an aware
    datetime. Returns ``None`` if ``s`` is empty/None or unparseable."""
    if not s:
        return None
    text = s.rstrip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    return dt


def retrievability(
    elapsed_days: float,
    stability: float,
    decay: float = DECAY,
) -> float:
    """Power-law forgetting curve. R = (1 + F·Δt/S)^(1/decay).

    The factor F is calibrated so that R(S, Δt=S) = 0.9 exactly: the FSRS
    convention is that after one full stability interval, retention is 90%.
    Note that this function takes ``decay`` as the POSITIVE exponent value
    (0.1542) and applies ``1/decay`` internally, matching the formula
    R = (1 + F·Δt/S)^(1/decay). Stability must be > 0.
    """
    if stability <= 0.0 or elapsed_days <= 0.0:
        return 1.0
    factor = math.exp(math.log(0.9) / (-decay)) - 1.0
    inner = 1.0 + factor * elapsed_days / stability
    if inner <= 0.0:
        return 0.0
    # The forgetting curve uses the NEGATIVE exponent: R = inner^(-decay).
    # Calling code passes the positive constant; flip the sign here.
    return inner ** (-decay)


def next_interval(
    stability: float,
    desired_retention: float = DESIRED_RETENTION_DEFAULT,
    decay: float = DECAY,
) -> float:
    """Inverse of retrievability: the Δt at which R = desired_retention.

    Returns days. ``stability`` must be > 0.
    """
    if stability <= 0.0:
        return 1.0
    factor = math.exp(math.log(0.9) / (-decay)) - 1.0
    base = (desired_retention ** (-1.0 / decay) - 1.0)
    return stability / factor * base


def init_stability(rating: int, w: tuple[float, ...] = DEFAULT_PARAMS) -> float:
    """Initial stability for a brand-new item: S0 = w[rating-1]."""
    if rating < 1 or rating > 4:
        raise ValueError(f"init_stability: rating must be 1..4, got {rating}")
    return max(w[rating - 1], S_MIN)


def init_difficulty(rating: int, w: tuple[float, ...] = DEFAULT_PARAMS) -> float:
    """Initial difficulty: D0 = w4 - exp(w5·(rating-1)) + 1."""
    if rating < 1 or rating > 4:
        raise ValueError(f"init_difficulty: rating must be 1..4, got {rating}")
    return _clamp(w[4] - math.exp(w[5] * (rating - 1)) + 1.0, D_MIN, D_MAX)


def _stability_after_failure(
    w: tuple[float, ...],
    last_s: float,
    last_d: float,
    r: float,
) -> float:
    """Stability update for rating=1 (Again): the recall failed."""
    new_s = (
        w[11]
        * (last_d ** (-w[12]))
        * ((last_s + 1.0) ** w[13] - 1.0)
        * math.exp((1.0 - r) * w[14])
    )
    return max(new_s, S_MIN)


def _stability_short_term(
    w: tuple[float, ...],
    last_s: float,
    rating: int,
) -> float:
    """Short-term stability override for same-day reviews (Δt == 0)."""
    sinc = math.exp(w[17] * (rating - 3.0 + w[18])) * (last_s ** (-w[19]))
    if rating >= 2:
        sinc = max(sinc, 1.0)
    return last_s * sinc


def step_review(
    state: LearnerState,
    rating: int,
    elapsed_days: float,
    nth_review: int,
    now_iso: str,
    w: tuple[float, ...] = DEFAULT_PARAMS,
    desired_retention: float = DESIRED_RETENTION_DEFAULT,
    rng: random.Random | None = None,
) -> None:
    """Apply one FSRS-6 review to ``state`` in place.

    Updates: stability, difficulty, retrievability, reps, lapses,
    next_review (ISO-8601 derived from ``now_iso`` + fuzz). For the very
    first review (``nth_review`` == 0 AND state.stability is None) the
    init_* values are used instead of the step formulas, matching FSRS
    semantics.

    ``rng=None`` disables fuzz (interval is just ``round()``). Pass a
    ``random.Random(...)`` to get ±5% fuzz on intervals ≥ 3 days.

    Caller supplies ``rating`` (1..4), produced by the evaluator agent; this
    function does NOT map a continuous correctness to rating. ``now_iso`` is
    the absolute timestamp of the review (ISO-8601, UTC suffixed with 'Z').
    """
    if rating < 1 or rating > 4:
        raise ValueError(f"step_review: rating must be 1..4, got {rating}")

    last_s = _clamp(state.stability or 0.0, 0.0, S_MAX)
    last_d = _clamp(state.difficulty or 5.0, D_MIN, D_MAX)

    # First review: init S and D from the rating alone.
    if nth_review == 0 and (state.stability is None or state.stability == 0.0):
        new_s = init_stability(rating, w)
        new_d = init_difficulty(rating, w)
    else:
        r = retrievability(elapsed_days, last_s, w[20])

        # --- Difficulty update (with linear damping + mean reversion) ---
        delta_d = -w[6] * (rating - 3.0)
        damped = (10.0 - last_d) * delta_d / 9.0
        new_d = last_d + damped
        d4 = w[4] - math.exp(w[5] * 3.0) + 1.0
        new_d = w[7] * (d4 - new_d) + new_d
        new_d = _clamp(new_d, D_MIN, D_MAX)

        # --- Stability update ---
        if rating == 1:
            new_s = _stability_after_failure(w, last_s, last_d, r)
        else:
            hard_penalty = w[15] if rating == 2 else 1.0
            easy_bonus = w[16] if rating == 4 else 1.0
            new_s = last_s * (
                math.exp(w[8])
                * (11.0 - last_d)
                * (last_s ** (-w[9]))
                * (math.exp((1.0 - r) * w[10]) - 1.0)
                * hard_penalty
                * easy_bonus
                + 1.0
            )

        # Short-term override: same-day reviews (Δt==0) collapse to the
        # short-term formula regardless of the long-term update above.
        if elapsed_days == 0.0:
            new_s = _stability_short_term(w, last_s, rating)

        new_s = _clamp(new_s, S_MIN, S_MAX)

    # --- Next interval (absolute ISO timestamp from now_iso + interval) ---
    r_now = retrievability(0.0, new_s)  # immediately post-review R ~= 1
    interval_days = next_interval(new_s, desired_retention, w[20])
    interval_int = apply_fuzz(interval_days, rng)

    now_dt = _parse_iso(now_iso)
    if now_dt is None:
        now_dt = datetime.datetime.now(datetime.timezone.utc)
    next_dt = now_dt + datetime.timedelta(days=interval_int)
    next_iso = next_dt.astimezone(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    state.stability = new_s
    state.difficulty = new_d
    state.retrievability = r_now
    state.reps += 1
    if rating == 1:
        state.lapses += 1
    state.next_review = next_iso


def apply_fuzz(interval_days: float, rng: random.Random | None = None) -> int:
    """Round an FSRS interval to integer days, optionally with ±5% fuzz.

    Intervals < 3 days never receive fuzz (FSRS convention). ``rng=None``
    disables fuzz entirely, giving a deterministic ``max(1, round(interval))``
    useful for tests and any caller that wants exact reproducibility.
    """
    interval = max(1, int(round(interval_days)))
    if rng is None or interval < 3:
        return interval
    fuzz = max(1, int(interval * 0.05))
    return interval + rng.randint(-fuzz, fuzz)