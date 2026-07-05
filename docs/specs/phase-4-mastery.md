# Phase 4 — Graduated mastery, adaptive thresholds, and faded scaffolding

**Version:** 0.0.7
**Date:** 2026-07-05
**Status:** shipped (retrospective)
**Decisions locked:** BKT soft-evidence Beta update (conjugate prior), 6-level mastery classifier, adaptive proficiency thresholds by dependent count, 4-level scaffolding driven by p_mastery

## Context

The learner model up to Phase 3 used a single `MASTERY_THRESHOLD` (0.95) as the
binary pass/fail gate for skill mastery. This produced two problems:

1. **Bottleneck in study plan generation:** every skill needed p_mastery >= 0.95
   to exit the frontier. Skills with abundant evidence but practical competence
   (e.g., p=0.85 with 50 observations) stayed indefinitely in the plan, crowding
   out new material.
2. **No scaffolding adaptation:** the tutor (maestro) had the same interaction
   pattern for every skill regardless of the learner's current mastery level.
   A skill at p=0.30 (exploring) got the same Socratic treatment as one at
   p=0.90 (near mastery).

Phase 4 introduced graduated mastery levels, adaptive thresholds that vary by
a skill's structural role, and scaffolding levels that fade as the learner's
p_mastery increases.

## What changed

### Learner model: BKT soft-evidence + 6-level mastery classifier

**Files:** `src/cognits/learner/model.py` (new), `constants.py` (additions)

`learner/model.py` implements a Beta-Bernoulli Bayesian Knowledge Tracing
model with soft-evidence fractional updates:

- Beta(alpha, beta) conjugate prior with `alpha=beta=1.0` (uniform prior).
- Soft evidence: evaluator-supplied `correctness ∈ [0, 1]` with penalty terms
  for hint usage (`LAMBDA_HINT = 0.15` per hint) and excessive time-on-task
  (`LAMBDA_TIME = 0.10` per unit of time_ratio above 1.0).
- Effective observation count weighted by `confidence × weight` (fractional
  Bayesian update per Cen et al. 2006, "Learning Factors Analysis").

Six-level mastery classifier (`mastery_level()`):

| Level | Gate | Semantics |
|-------|------|-----------|
| `not_seen` | reps == 0 | Never attempted |
| `exploring` | p < 0.60 | Initial exposure |
| `practicing` | reps < 3 or alpha+beta < 8 | Building evidence |
| `proficient` | p < 0.80 | Competent but not yet mastered |
| `mastered` | p >= 0.95 and conf >= 12 and R >= 0.90 | Fully acquired |
| `decaying` | Overdue past 1.5x next_review interval | Previously mastered, now fading |

The decay check runs first and only triggers when the learner's previous status
was already `proficient` or `mastered` — this prevents "decaying" from appearing
for skills that never reached proficiency.

`record_review()` applies FSRS-6 first (updates S, D, reps), then BKT
(updates alpha, beta, p_mastery), then recomputes status. This order matches
IntelliCode's Khan-inspired pattern: FSRS needs rating and elapsed_days;
BKT then folds continuous correctness into alpha/beta.

`learner/fsrs.py` (new) implements the FSRS-6 spaced repetition scheduler
with Anki 24.11 default parameters (21-parameter vector). Pure functions with
no I/O: stability, difficulty, retrievability, next interval. All take
`elapsed_days` as a float so callers can inject synthetic clocks for tests.

### Adaptive proficiency thresholds

**File:** `src/cognits/learner/planner.py` (modified)

`_proficient_threshold()` replaces the flat `MASTERY_THRESHOLD` gate in
`compute_frontier()`:

- Skills with >3 downstream dependents (foundational) → 0.90
- Leaf skills with 0 dependents → 0.75
- Default → `MASTERY_PROFICIENT_P` (0.80)

This follows the ALEKS outer fringe algorithm (Cosyn et al. 2021):
foundational skills need higher confidence because their weakness cascades;
leaf skills can advance with less evidence.

`compute_frontier()` uses the adaptive threshold by passing each skill's
dependent count derived from the hard-prerequisite edges.

Constants added to `constants.py`:

```python
MASTERY_EXPLORING_P = 0.60
MASTERY_PRACTICING_MIN_REPS = 3
MASTERY_PROFICIENT_P = 0.80
MASTERY_PROFICIENT_CONFIDENCE = 8.0
MASTERY_MASTERED_CONFIDENCE = 12.0
MASTERY_MASTERED_RETENTION = 0.90
MASTERY_DECAY_OVERDUE_FACTOR = 1.5
BKT_PRIOR_ALPHA = 1.0
BKT_PRIOR_BETA = 1.0
BKT_LAMBDA_HINT = 0.15
BKT_LAMBDA_TIME = 0.10
BKT_EVIDENCE_THRESHOLD = 4.0
```

### Faded scaffolding

**Files:** `src/cognits/agent/agents/maestro.md` (modified),
`src/cognits/storage/database.py` (modified), `storage/models.py` (modified)

The maestro persona prompt received an "Adaptive scaffolding" section with
4 levels driven by p_mastery:

| Level | p_mastery range | Tutor behaviour |
|-------|----------------|-----------------|
| 1 — Direct | 0.00–0.30 | Explicit hints, worked examples, step-by-step guidance |
| 2 — Socratic | 0.30–0.60 | Probing questions, "what would happen if" |
| 3 — Guided | 0.60–0.80 | Open challenges, minimal hints on request |
| 4 — Minimal | 0.80–1.00 | Autonomous problem-solving, tutor as observer |

The scaffolding level is persisted in `learner_state.scaffolding_level`
(INTEGER, default 1). An idempotent `ALTER TABLE` migration adds the column
for existing databases:

```sql
ALTER TABLE learner_state ADD COLUMN scaffolding_level INTEGER NOT NULL DEFAULT 1;
```

`LearnerState.scaffolding_level` field added to the dataclass in `models.py`.

## Architecture invariants established

- **BKT + FSRS dual update:** both models run on every review; FSRS handles
  scheduling (S, D, next_review), BKT handles semantic mastery (alpha, beta,
  p_mastery). Neither replaces the other.
- **Mastery levels are strict thresholds, not ML predictions:** the six levels
  are deterministic functions of (p_mastery, confidence, retrievability, reps).
  No hidden state, no training.
- **Adaptive thresholds are structural, not behavioral:** they depend only on
  the skill graph's dependency count, not on the learner's performance.
- **Scaffolding is prompt-side, not code-side:** the maestro prompt encodes the
  4 levels. The backend persists the level but does not enforce transitions
  (that came in Phase 7 with PedagogyEngine).

## Tests added

Pre-existing test files adapted to the new model. The Phase 7 commit
(`e939c10`) later added repository-level tests for learner state persistence:

- `tests/test_learner_state_repo.py` — 5 tests for upsert/get/get_all
  including scaffolding_level default.

## Deferred / out of scope

- Scaffolding level was prompt-only in this phase; backend-driven stage
  transitions came in Phase 7 (PedagogyEngine).
- The decaying check runs at query time; there is no background job to
  proactively flag decaying skills.
- Multi-skill assessment (transfer learning between related skills) was not
  implemented — each skill has an independent Beta posterior.
- `MASTERY_DECAY_OVERDUE_FACTOR` and other FSRS tuning parameters remain
  at Anki defaults; no Cognits-specific calibration was done.

## Commits

| SHA | Description |
|-----|-------------|
| `98c97d4` | P2+P3 — graduated mastery + adaptive thresholds + faded scaffolding |
| `72de415` | AGENTS.md update for Phase 4 (persona count fix, tracer docs, invariants) |
| `c98d4fd` | P1 — centralize pedagogical hardcoded values in constants.py |
