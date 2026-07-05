# Phase 7 — PedagogyEngine external stage management

**Version:** 0.0.7
**Date:** 2026-07-05
**Status:** shipped (retrospective)
**Decisions locked:** 5-stage progression (activate → introduce → guided → assess → wrap_up), mastery-gated transitions + minimum interaction counts, stage managed externally in backend (not by LLM), scaffolding_level persisted in learner_state

## Context

Before Phase 7, pedagogical stage management was entirely prompt-side: the
maestro persona's system prompt described a progression, but the LLM decided
when to transition. Research (Springer 2025 systematic review) found ~30%
non-compliance rates when LLMs self-manage stage transitions — the model
skipped stages, lingered too long on one stage, or jumped ahead prematurely.

Phase 7 introduced `PedagogyEngine`, a deterministic backend component that
manages the 5-stage pedagogical progression externally. The maestro LLM is
informed of the current stage via a `prompt_context()` string but cannot
override it. Transitions are gated on BKT mastery thresholds and minimum
interaction counts.

## What changed

### PedagogyEngine class

**File:** `src/cognits/learner/pedagogy_engine.py` (new, 84 lines)

The 5 stages with their advancement gates:

| Stage | Min interactions | Mastery gate | Purpose |
|-------|-----------------|-------------|---------|
| `activate_prior_knowledge` | 1 | None | Surface what the learner already knows |
| `introduce_concept` | 2 | 0.30 | Present new material |
| `guided_practice` | 3 | 0.80 (MASTERY_PROFICIENT_P) | Solve with scaffolding |
| `assessment` | 1 | 0.80 (MASTERY_PROFICIENT_P) | Formal evaluation |
| `wrap_up` | 1 | 0.95 (MASTERY_THRESHOLD) | Summary and next steps |

Key design:

```python
class Stage(str, Enum):
    ACTIVATE = "activate_prior_knowledge"
    INTRODUCE = "introduce_concept"
    GUIDED = "guided_practice"
    ASSESS = "assessment"
    WRAP_UP = "wrap_up"

class PedagogyEngine:
    def __init__(self):
        self.stage = Stage.ACTIVATE
        self.interactions = 0

    def should_advance(self, p_mastery: float) -> bool:
        """Returns True if both mastery gate and min interactions are met."""
        threshold = ADVANCE_THRESHOLD.get(self.stage)
        if threshold is not None and p_mastery < threshold:
            return False
        return self.interactions >= MIN_INTERACTIONS.get(self.stage, 2)

    def advance(self) -> Stage | None:
        """Moves to next stage, resets interaction counter."""
        idx = STAGE_ORDER.index(self.stage)
        if idx >= len(STAGE_ORDER) - 1:
            return None  # already at wrap_up
        self.stage = STAGE_ORDER[idx + 1]
        self.interactions = 0
        return self.stage

    def record_interaction(self):
        """Called after each teacher turn."""
        self.interactions += 1
```

State serialization:

- `to_scaffolding_level() -> int` — maps current stage to 1–5 (for persistence
  in `learner_state.scaffolding_level`).
- `load_from_scaffolding_level(level: int)` — restores engine state from a
  persisted level (session resumption).
- `prompt_context() -> str` — generates a short string for the maestro prompt
  (e.g., `"You are currently in stage: guided_practice."`).

Mastery thresholds reference `constants.py` values (`MASTERY_PROFICIENT_P=0.80`,
`MASTERY_THRESHOLD=0.95`), ensuring consistency with the BKT classifier.

### ChatService integration

**File:** `src/cognits/server/chat_service.py` (modified)

`PedagogyEngine` is instantiated per maestro session in `ChatService`:

1. **At session start:** instantiated from `learner_state.scaffolding_level`
   via `load_from_scaffolding_level()`. Defaults to stage 1 (activate) for
   new skills.
2. **After each teacher turn:** `record_interaction()` is called, then
   `should_advance(p_mastery)`, and if True, `advance()` transitions to the
   next stage. The new `scaffolding_level` is persisted via
   `learner_state_repo.upsert()`.
3. **On stage advance:** a `ui_action` SSE event is published for the frontend.
4. **Gated on `agent_id == "maestro"`:** the engine only runs for maestro
   sessions (the Socratic tutor). Subagents and other sessions use the old
   prompt-only approach.

### Learner state persistence

**File:** `src/cognits/storage/learner_state.py` (modified)

The `scaffolding_level` column (added in Phase 4 schema) is now actively
written and read:

- `upsert_learner_state()` includes `scaffolding_level` in the SQL.
- `get_learner_state()` and `get_all_learner_states()` return it.
- Default value: `1` (activate stage).

### Session analyzer BKT updates

**File:** `src/cognits/agent/agents/session_analyzer.md` (modified)

The session analyzer persona output gained a `mastery_updates` field: an array
of `{skill_id, correctness, rating, hints_used, evidence}` entries. This
enables the evaluator to produce BKT evidence updates at session end from
transcript-based assessment data, feeding the `update_mastery` tool.

### Tests added

Repository-level tests for the learner model persistence layer:

**File:** `tests/test_learner_state_repo.py` — 5 tests:
- `test_upsert_learner_state` — insert + update
- `test_get_learner_state` — by skill_id
- `test_get_all_learner_states` — full collection
- `test_scaffolding_level_default` — defaults to 1
- `test_scaffolding_level_persist` — round-trip

**File:** `tests/test_study_plans_repo.py` — 6 tests covering
`StudyPlanRepository` (create, supersede, add, replace, update,
get_with_items).

**File:** `tests/test_pedagogy.py` — 4 tests covering
`PedagogicalPlanRepository` CRUD.

**File:** `tests/test_pedagogical_plan.py` — placeholder (async hang in test
env, noted in commit).

## Architecture invariants established

- **External stage management:** the LLM is told the current stage but cannot
  change it. The backend controls all stage transitions deterministically.
  Prevents the ~30% LLM non-compliance rate documented in Springer 2025.
- **BKT mastery is the transition currency:** all advancement gates use BKT
  `p_mastery`, not LLM judgement. This grounds pedagogy in the learner model,
  not the whim of the current response.
- **Interaction counts prevent stage-skipping:** even if p_mastery is high,
  a skill needs a minimum number of learner interactions per stage. This
  prevents the LLM from rushing through stages.
- **Stage state is durable:** `scaffolding_level` is persisted to SQLite,
  so interrupting and resuming a session restores the correct stage.

## Deferred / out of scope

- **LLM-override mechanism:** no endpoint allows the LLM to request a stage
  change. If the evaluator detects that the learner is clearly beyond a stage,
  there is no back-channel to skip it.
- **Stage regression:** if a learner's p_mastery drops (decaying), the engine
  does not regress to an earlier stage. The maestro prompt handles this via
  the adaptive scaffolding text, but the stage enum only moves forward.
- **Per-skill stage tracking:** scaffolding_level is per-skill, not per-session.
  A session that spans multiple skills transitions each skill independently,
  but the `ChatService` integration was designed for single-skill sessions.
- **UI indicators:** stage transitions publish a `ui_action` event, but the
  frontend had no specialized stage indicator component until later.

## Commits

| SHA | Description |
|-----|-------------|
| `847e0d4` | P4+P7 — PedagogyEngine (5-stage external management) + AGENTS.md update |
| `e939c10` | P5+P6 — session analyzer BKT updates + pedagogical tests (learner_state, plans, pedagogy repos) |
| `c98d4fd` | P1 — centralize pedagogical hardcoded values in constants.py |
