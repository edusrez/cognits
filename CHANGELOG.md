# Changelog

All notable changes to Cognits are documented in this file.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.0.8] - 2026-07-08

### Added

#### Assessment item bank (Phase 1 — T2)
- New `skill_assessment_items` table (IRT-ready, Q-matrix via `skill_ids` JSON,
  structured `rubric_criteria`, `generation_model` provenance for same-model
  bias detection, IRT parameter columns `irt_a/b/c` reserved for future
  calibration). FTS5 external-content index over `question`.
- `AssessmentItemRepository` in `storage/assessment.py` with CRUD, FTS search,
  and `record_response()` (increments `times_presented`/`times_correct`,
  recomputes `p_value`).
- `SaveAssessmentItems` and `ListAssessmentItems` tool actions (via
  `SkillTreeSave` dispatch) — skill_planner persists assessment items per
  skill, evaluator reads banked items for grading.
- Evaluator Phase 1 now persists generated items (not transient); Phase 2 uses
  banked items with rubrics and expected answers for structured grading.

#### Study plan endpoints (Phase 1 — T3)
- `GET /api/study_plan` — retrieves the active study plan with items.
- `POST /api/study_plan` — generates a new plan via `planner.generate_plan()`
  (deterministic, not LLM-authored) and supersedes the old plan.
- SSE event `study_plan_updated` emitted after generation.

#### AND/OR prerequisites (Phase 2 — T4)
- New edge type `alt_prereq` with `group_id` column for OR-bundles:
  multiple `alt_prereq` edges sharing the same `group_id` form an OR gate
  (any one mastered satisfies the prerequisite).
- `EDGE_TYPES` extended to include `alt_prereq`; semantics documented:
  `prereq` = AND, `alt_prereq` = OR, `soft_prereq` = bonus.
- `compute_frontier` extended with OR-group logic: per group_id, at least
  one alt mastered suffices; across groups AND with all `prereq` edges.
- `compute_goal_distances` BFS traverses `alt_prereq` edges.
- Cycle detection covers `alt_prereq` in both `_prereq_reaches` CTE and
  `add_edge` validation.
- `soft_prereq` added to skill_planner prompt with clear semantics.

#### Skill planner prompt rewrite (Phase 2 — T5, T6, T7)
- Bloom hierarchy fix: `BLOOM_RANK` dict (`remember=1`…`create=6`) replaces
  `len(skill.bloom_level)` bug. Bloom level parsed as first word, lowercased,
  default `apply=3` for unknown tags.
- Subject-agnostic generalization: prompt detects domain type
  (programming/tool, language, paper/research, field of knowledge,
  creative/artistic) and adapts atomicity heuristic.
- Bloom level assignment section with balanced distribution guidance
  and domain-specific examples.
- Assessment item generation requirement: ≥3 items per skill
  (1 recall + 1 apply + 1 transfer/analyze).
- `finish_build` post-check warns when skills have <3 items.

#### `validate_tree` deterministic loop (Phase 2 — T7b)
- LLM self-correction with external deterministic validator (SOTA per
  Huang 2024). Validates against self-proposed targets (`propose_targets`
  action), not hardcoded caps.
- Anti-gaming: Bloom full-distribution caps, item quality WARNs
  (not communicated to LLM), stall detection.
- Seed_mastery Beta conjugate prior uses learner's verbatim rating
  (HARD rule: prior ≥0.80, `alpha=prior×C`, `beta=(1-prior)×C`).

#### Adaptive targets (Fase 2.3)
- `propose_targets` action: domain-aware Bloom ranges, self-proposed
  by the LLM, not hardcoded caps.
- `skill_builds.targets` TEXT column for adaptive target persistence.

#### Fractal architecture (Fase 2.4)
- `skill_branch_builder` subagent: level-1 branch builder, per-domain,
  parallel via `asyncio.gather`, web_researcher-only, 2-level bound
  (no self-recursion).
- Global merger: `find_duplicate_skills` (semantic BGE-M3 cosine + FTS5
  fallback) + `merge_skills` (cascade merge).
- `MAX_CONCURRENT_DEPLOYS` bumped from 4 → 16 for fractal fan-out.

#### Organic top-down-to-floor tree generation (Fase A)
- Zero size hardcode: tree size = f(goal complexity − floor height).
- skill_planner rewritten as goal_decomposer (decomposes goal DOWN to
  learner's floor).
- skill_branch_builder rewritten for organic top-down per-rama
  decomposition.
- Mutation tools: `delete_skill` (cascade delete with prereq edge cleanup),
  `remove_edge` (single edge removal).
- `mastery_judge` internal subagent: LLM judgment of P(mastery) from
  learner profile + chat history, conservative bias.
- Roots reframed as learner's floor (not validation failure — correct
  in the top-down model).

#### Living tree — grow (Fase B)
- `check_branch_floor` tool: deploys `mastery_judge` on prerequisite
  skills; for not-mastered prereqs, deploys `skill_branch_builder` to
  expand → tree grows downward toward the learner's floor.

#### Mutation — shrink + reshape (Fase C)
- `check_branch_floor` prunes mastered sub-trees: skills confirmed
  mastered are removed along with their descendant subtrees.
- `refocus_tree` tool: re-decomposes the skill tree on goal change.
  Deploys `skill_planner` with new goal + existing tree context.
  Tree mutates: prune obsolete branches + add new branches.

#### Pedagogy improvements (Fase 3+4)
- Fuzzy goal match: cascading resolution (exact → substring → Levenshtein
  ≤2) replaces exact-name-only match. Logs warning when no match found.
- `estimated_duration_min` populated: formula `15 + difficulty × 45`
  (15–60 min base) × Bloom multiplier
  (remember/understand=0.7, apply=1.0, analyze/evaluate=1.3, create=1.5),
  rounded to nearest 5 minutes.
- Unified 5-stage taxonomy: study_planner pedagogical plan template
  enforces exact PedagogyEngine stage enum names
  (`activate_prior_knowledge`, `introduce_concept`, `guided_practice`,
  `assessment`, `wrap_up`). Validation warning on mismatched stage headers.
- PedagogyEngine `retreat()` method: regresses one stage when learner
  mastery drops ≥0.10 absolute. Persists `scaffolding_level`, emits
  `ui_action` with new stage.
- ASSESS gate threshold lowered from 0.80 → 0.60 (assessment measures
  true mastery, does not gate on it). `wrap_up` stays at 0.95.
- Auto-regen study plan post-session: fire-and-forget background task
  (mirrors `_reflect_async` pattern). Gated on `study_plan_auto_regen`
  config flag (default True). Emits `study_plan_updated` SSE event.
- Scoring improvements: `USER_PRIORITY_MULTIPLIER` 8→3 (priorities still
  dominant but no longer short-circuit other dimensions). Smooth
  `_proficient_threshold` function: `0.75 + min(0.20, dc × 0.04)`
  replaces 3-step jump. ZPD bonus (+1.5) for skills with
  `0.4 ≤ p_mastery ≤ 0.75` (Vygotsky growth zone).

#### SOTA judge quality criteria
- bottleneck detection (skills blocking many descendants),
- goal_relevance (BFS backward from goal, robust detection),
- transitive_redundancy (redundant chains via transitive closure),
- naming_specificity (skill name precision),
- bloom_coverage (Bloom level distribution quality).

#### Feedback loop closure
- `GetCurrentStudyPlan` tool: FSRS-based review-vs-new classification
  (uses `next_review` date, not `p_mastery>0`). Skip seeded-known items
  (p_mastery≥0.95, no `last_review`).
- Plan PUSHED into orchestrator system_prompt (not pulled) — orchestrator
  cannot ignore the deterministic plan.
- `classify_item` module-level function (shared between tool and
  `ChatService._fetch_plan_summary`).
- Floor verification SYSTEM-ENFORCED: `CheckBranchFloor.execute()` called
  programmatically before the maestro agent loop (not agent-discretioned).

#### Development scripts
- `dev_run_skill_planner.py` — standalone skill planner execution.
- `dev_judge_tree.py` — adaptive judge that reads proposed targets and
  validates against them.
- `dev_run_skill_tree_cases.py` — 3-floor comparison + qualitative
  examination.

### Changed

- **Bloom scoring**: `BLOOM_RANK` dict replaces `len(skill.bloom_level)` —
  `len("understand")=10` and `len("create")=6` both clamped to 6, making
  Bloom hierarchy a no-op in scoring. Now `remember=1`…`create=6` with
  proper ordinal comparison.
- **Edges/skill density**: softened from `<1.2` FAIL to `<0.8` WARN —
  no literature supports a hard density target; Math Academy averages ~5
  prereqs per topic.
- **Roots validation**: roots = learner's floor → downgraded from FAIL
  to NOTE (correct in the top-down model).
- **Orchestrator Planning Mode**: now explicitly instructed to "follow the
  injected plan, do not re-derive the frontier."
- **`USER_PRIORITY_MULTIPLIER`**: 8.0 → 3.0 (documented as "3.0 gives
  explicit priorities ~3× weight vs ~8× which made other dimensions noise").
- **Proficient threshold**: 3-step jump replaced with smooth function
  `0.75 + min(0.20, dc × 0.04)` — continuous from 0.75 (0 deps) to 0.95
  (5+ deps).
- **`MAX_CONCURRENT_DEPLOYS`**: 4 → 16 for fractal fan-out.

### Fixed

- **C1 — No assessment items**: new `skill_assessment_items` table with
  Q-matrix, CRUD repo, FTS search, and `record_response()` statistics.
- **C2 — No study plans generated**: `GET/POST /api/study_plan` endpoints;
  auto-regen after learning turns.
- **C3 — `update_mastery` not registered in skill_planner**: now registered
  so onboarding mastery seeding works (root skills no longer stuck at
  p_mastery=0.5/not_seen).
- **B1 — `len(skill.bloom_level)` as Bloom proxy**: replaced with
  `BLOOM_RANK` dict for correct ordinal hierarchy.
- **RAG backfill**: `_backfill_rag_index` startup scan, `ready.set()` in
  `finally` block, `wait_for` timeout increased to 600s.
- **Seed_mastery**: Beta conjugate prior uses learner's verbatim rating
  (HARD rule: prior ≥0.80). Forces `reps=max(reps, 1)`, never leaves
  `status` as `not_seen` after seeding.
- **Gap 1 — Tool registration**: `CheckBranchFloor` and `RefocusTree`
  were registered in `teacher_config`'s subagent config instead of the
  maestro's primary tool registry. Fixed to register in `_build_tool_registry`.
  Also fixed argument mis-mapping (`st.pedagogy` → `st.messages`).
- **Gap 2 — Plan ignored by orchestrator**: plan now PUSHED into
  system_prompt (not pulled). Orchestrator cannot skip deterministic
  planning.
- **MUST-FIX 2 — Review-vs-new classification**: was using `p_mastery>0`;
  now uses FSRS `next_review` comparison + skip seeded-known items
  (p_mastery≥0.95, no `last_review`).
- **`dev_run_skill_planner._emit` signature**: fixed to be sync + single-dict
  (was async with mismatched signature).
- **`skill_tree_cases` schema columns**: corrected column names
  (`question`/`question_type`).
- **goal_relevance judge**: robust goal detection for organic top-down model
  (handles cases where goal skill is deep in tree, not at root level).

### Internal

- **SKILL_PLANNER_MAX_STEPS**: bumped to 999 (was 50) — goal decomposition
  needs many steps.
- **BRANCH_BUILDER_MAX_STEPS**: set to 200 — per-rama decomposition.
- **MASTERY_JUDGE_MAX_STEPS**: set to 50 — proficiency estimation.
- **Test suite**: 570 tests (up from ~500), including 33 new E2E tests
  covering the closed feedback loop (push plan → FSRS classification →
  system-enforce floor → evaluator → UpdateMastery → auto-regen).
- **Prerelease**: version bumped to `0.0.8.dev0` after Phase 1 completion.
- **`dev_run_skill_planner.py`**: autonomy script for standalone
  skill_planner execution with output diffing.
- **`dev_judge_tree.py`**: standalone tree quality judge with adaptive
  target validation.
- **`dev_run_skill_tree_cases.py`**: 3-floor comparison runner with
  qualitative exam output.

## [0.0.8.1] - 2026-07-08

### Added

#### FIRe implicit repetition credit (simplified approximation — M2.a)
- New `skill_encompassings` table for "encompassing" edges (separate from prerequisites).
- `SkillEncompassing` dataclass in `storage/models.py` with `to_json`/`from_json`.
- `SkillRepository` methods: `add_encompassing`, `get_encompassings`,
  `get_encompassing_parents`, `delete_encompassing`.
- `apply_implicit_credit()` in `learner/model.py` — applies fractional credit to
  encompassed skills when the advanced skill is reviewed. Only triggers when
  retrievability < target retention (prevents over-crediting). Caps credit at
  `cap_fraction` (0.5) of current interval × weight.
- FIRe hook in `UpdateMastery`: on successful review (rating ≥ 2), propagates
  direct-only encompassing credit to `next_review` of encompassed skills.
- Encompassing edge generation instructions in `skill_planner.md` prompt.

#### SOTA improvements
- **M1 — Floor gating first-turn-only:** `CheckBranchFloor.execute()` now runs
  only on the maestro's first turn (gated by `existing_user_msgs <= 1`), not
  every turn. Reduces redundant LLM calls from O(N prereqs) per turn to O(N)
  once.
- **M2 — R-based classification:** `classify_item()` in `tool_study_plan.py` now
  uses FSRS retrievability (`R = retrievability(elapsed, stability)`) compared
  to `target_retention` (default 0.9). Falls back to `next_review` date when
  stability is unavailable. Seeded-known skills (p_mastery ≥ threshold, no
  `last_review`) still classified as "skip".
- **M3 — mastery_judge structured rubric:** mastery_judge.md rewritten with
  three structured dimensions (explanation, application, transfer), evidence
  requirements, BKT state acknowledgment, and calibrated confidence thresholds.
- **M4 — Mastery threshold 0.98 (AFL):** `MASTERY_THRESHOLD` raised from 0.95
  to 0.98 (EDM 2025 Zhang et al. Accelerated Future Learning finding). Skills
  with 0.95 ≤ p < 0.98 are now "proficient", not "mastered".
- **M5 — NO_INTERVENTION signaling:** maestro.md now includes a "When NOT to
  intervene" section targeting 30-40% silence/minimal-acknowledgment turns.
  Specific criteria for productive silence, lightest-touch intervention ladder,
  and self-check prompt.
- **M6 — Preventative R-based retreat:** Pre-turn retrievability check in
  `chat_service.py` — if R < 0.80 for a `proficient`/`mastered` skill, injects
  an advisory retention warning into the maestro's system prompt (complements
  the reactive 0.10 p_mastery drop retreat).
- **M7 — Stability gate ≥ 21 days for "mastered":** `mastery_level()` in
  `model.py` now requires `stability ≥ 21 days` as a fourth gate (alongside
  p ≥ 0.98, confidence ≥ 12, retrievability ≥ 0.90) before classifying a skill
  as "mastered". Prevents "mastered yesterday, forgotten tomorrow."

#### Bugfixes
- **B1 — SkillPrereq.from_json():** Added `SkillPrereq.from_json()` classmethod
  supporting both camelCase and snake_case keys. Updated all call sites
  (`chat_service.py`, `tool_study_plan.py`, `routes_study.py`,
  `test_learning_flow_e2e.py`). Removed dead code at `tool_study_plan.py:152-158`.
  **Severity: CRITICAL** — the study plan feedback loop was broken (TypeError
  silently caught, plan never regenerated).
- **B2 — mastery_judge híbrido (BKT auto + LLM informado):** `tool_floor.py`
  adds auto-mastered gate (BKT p ≥ 0.95, confidence ≥ 12, reps ≥ 3 → skip LLM)
  and auto-not-mastered gate (no evidence → skip LLM). Ambiguous cases pass
  full BKT state to mastery_judge.
- **B3 — Maestro prompt usa status_enum:** maestro.md scaffolding section
  rewritten from raw p_mastery ranges (0.3/0.7/0.9) to `status_enum`-based
  levels. `chat_service.py` injects `status_enum` + p_mastery + stability into
  the maestro system prompt context.
- **B4 — SeedMastery inicializa stability:** `SeedMastery.execute()` now sets
  `state.stability` based on the seeded prior (21 days for prior ≥ 0.95, 7 for
  ≥ 0.80, 3 for ≥ 0.60, 1 otherwise) plus neutral `difficulty = 5.0`. Prevents
  FSRS from treating a seeded-known skill as brand-new in the review pipeline.
- **B5 — Plan items transicionan status:** `chat_service.py` now calls
  `plans.update_item()` to transition items: `pending → in_progress` on first
  interaction, `in_progress → done` when p_mastery ≥ MASTERY_THRESHOLD. Runs
  before `_regen_study_plan_async` so done items are not re-included.
- **B6 — actual_duration_min se registra:** Computes session duration from
  message timestamps (first user/hidden_user → last message). Populates
  `actual_duration_min` on `update_item()` when item transitions to `done`.
  Best-effort (skips silently if timestamps unavailable).

### Changed

- **MASTERY_THRESHOLD**: 0.95 → 0.98 (AFL-optimized, Zhang et al. EDM 2025).
- **mastery_level()**: added stability gate (STABILITY_MASTERED_MIN_DAYS = 21.0)
  as a fourth gate for "mastered" classification.
- **classify_item()**: now R-based (retrievability vs target_retention) with
  legacy next_review fallback. `target_retention` parameter defaults to 0.9.
- **Floor verification**: now first-turn-only (M1), not every maestro turn.
- **Maestro prompt**: scaffolding uses status_enum (B3); added NO_INTERVENTION
  section (M5); living-tree section updated to reflect first-turn enforcement.
- **mastery_judge.md**: rewritten with structured 3-dimension rubric (M3),
  BKT state acknowledgment (B2), and conservative calibration guidelines.

### Fixed

- **B1 — SkillPrereq.from_json()**: `SkillPrereq(**e)` where `e` is camelCase
  raised TypeError. Fixed with defensive `from_json()` classmethod supporting
  both camelCase and snake_case. The entire feedback loop (regen study plan)
  was dead on multi-skill trees with prerequisites.
- **B2 — mastery_judge blind to BKT**: added auto-mastered/not-mastered gates
  and BKT state injection in query. Prevents LLM overconfidence while saving
  LLM calls for clear cases.
- **B3 — Maestro p_mastery ranges diverging from classifier**: scaffolding
  now uses the system's deterministic `status_enum`, not raw p_mastery ranges
  that diverged from `model.py:mastery_level()`.
- **B4 — Seeded skills missing stability**: `SeedMastery` now initializes
  stability from the seed prior, preventing FSRS first-review initialization
  for known skills.
- **B5 — Plan items frozen at pending**: wired `update_item()` calls for
  status transitions. Items now progress pending → in_progress → done.
- **B6 — actual_duration_min never populated**: computed from message
  timestamps and stored via `update_item()`.

### Internal

- **New constants in constants.py**: `PROFICIENT_HIGH_P = 0.95`,
  `STABILITY_MASTERED_MIN_DAYS = 21.0`, `RETREAT_PREVENTATIVE_R = 0.80`.
- **New table**: `skill_encompassings` (SQLite) with `(skill_id,
  encompasses_skill_id, weight, created_at)`, primary key + two indexes.
- **New dataclass**: `SkillEncompassing` in `storage/models.py`.
- **New function**: `apply_implicit_credit()` in `learner/model.py`.
- **New repo methods**: 4 methods on `SkillRepository` for encompassing CRUD.
- **Research reports**: 4 new SOTA reports in `_research/`:
  `2026-07-08-sota-adaptive-scheduling.md`,
  `2026-07-08-sota-knowledge-tracing.md`,
  `2026-07-08-sota-learner-profiling.md`,
  `2026-07-08-fire-algorithm-deep-dive.md`.

## [0.0.7.1] - 2026-07-07

### Fixed
- VACUUM INTO + `os.sync` on shutdown for 9p filesystem data persistence
  (ensures DB data survives WSL restart on DrvFs/9p mounts).

### Links

[0.0.7.1]: https://github.com/edusrez/cognits/releases/tag/v0.0.7.1
