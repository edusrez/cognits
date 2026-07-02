# Phase 1 — Storage layer: split God class + centralize constants

**Version:** 0.0.7  
**Date:** 2026-07-02  
**Status:** in-progress  
**Decisions locked:** split completo (no facade), constants.py centralizado, RLock, db.transaction()

## Current state (ground truth)

`src/cognits/storage/db.py` — 1484 lines. One class `ReportStore` (~45 methods
spanning 9 domains) + 15 dataclasses + module-level helpers + FTS5 helpers.
Key structural issues:

1. **God class** — `ReportStore` handles reports, messages, notes, skills, learner_state,
   study_plans, pedagogical_plans, session_config, edges, builds, all FTS5 queries,
   and schema migration. Callers depend on one object for everything.

2. **Non-reentrant `threading.Lock`** — `get_plan_with_items` (db.py:1305-1325)
   inlines a sub-query instead of calling `get_plan_items` because the non-reentrant
   lock would deadlock. `_prereq_reaches` (db.py:954-970) accesses `self._conn`
   directly without acquiring the lock, relying on the caller's lock being held.

3. **Transaction smells** — `upsert_skill` (db.py:863-893), `replace_plan_items`
   (db.py:1239-1264), and `reorder_notes` (db.py:1478-1484) execute multiple
   writes under the lock but without an explicit `BEGIN/COMMIT` → not atomic.

4. **FTS rebuild asymmetry** — `_migrate` (db.py:661) rebuilds `reports_fts` but
   not `skills_fts`. Both are external-content FTS5 tables with identical trigger
   patterns.

5. **`close()` vs `shutdown()` inconsistent** — `close()` (db.py:672-674) just
   closes without checkpoint or `_closed` flag. `shutdown()` (db.py:677-683) does
   both. If `close()` runs first, `shutdown()` later hits a closed connection.

6. **Hardcoded/duplicated literals** across the codebase (see next section).

### Caller coupling map

Every route module touches exactly one domain (read side). The write side is
concentrated in agents (`tool_skill.py`, `tool_study_plan.py`, `tool_mastery.py`,
`pedagogical_plan.py`, `tool_deploy.py`). `routes_chat.py` is the only route
that spans multiple domains (reads session_config, tree, skill, learner_state,
pedagogical_plan; writes messages). `AppState` holds the single `state.report_store`.

## Design

### New architecture

```
src/cognits/
  constants.py              ← centralized literals (model names, thresholds, limits, labels)

  storage/
    models.py               ← dataclasses + ID generators + FTS helpers
    database.py             ← Database (conn, RLock, pragmas, _migrate, BASE_SCHEMA, shutdown, transaction())
    reports.py              ← ReportRepository
    messages.py             ← MessageRepository
    notes.py                ← NoteRepository
    skills.py               ← SkillRepository (skills + edges + builds + FTS)
    learner_state.py        ← LearnerStateRepository
    study_plans.py          ← StudyPlanRepository
    pedagogical.py          ← PedagogicalPlanRepository
    session_config.py       ← SessionConfigRepository
    files.py                ← (unchanged: JSON + AES-GCM crypto)
```

`AppState` changes from `state.report_store` to:
```python
class AppState:
    db: Database
    reports: ReportRepository
    messages: MessageRepository
    notes: NoteRepository
    skills: SkillRepository
    learner_state: LearnerStateRepository
    study_plans: StudyPlanRepository
    pedagogy: PedagogicalPlanRepository
    session_config: SessionConfigRepository
    # ... rag, docling_engine, active_agents, etc.
```

### Database class

```python
class Database:
    def __init__(self, db_path: str):
        self.conn = sqlite3.connect(db_path, check_same_thread=False, isolation_level=None)
        self.lock = threading.RLock()  # reentrant
        self.conn.execute("PRAGMA busy_timeout = 5000")
        self.conn.execute("PRAGMA journal_mode = WAL")
        self.conn.execute("PRAGMA synchronous = NORMAL")
        self._check_fts5()
        self._migrate()

    def shutdown(self) -> None:
        """Checkpoint WAL + close connection. Idempotent."""
        ...

    @contextmanager
    def transaction(self):
        """BEGIN/COMMIT/ROLLBACK with RLock."""
        with self.lock:
            self.conn.execute("BEGIN")
            try:
                yield
                self.conn.execute("COMMIT")
            except Exception:
                self.conn.execute("ROLLBACK")
                raise
```

### Repository pattern

Each repository takes `db: Database` at construction and uses `db.lock` +
`db.conn` for all operations. Repositories manage their own domain data;
they do NOT open transactions themselves (transaction boundaries are managed
by the caller via `db.transaction()` or by individual autocommit statements).

FTS5 queries are co-located with the parent table's repository (e.g.,
`search_reports_fts` stays in `ReportRepository`). FTS5 triggers are created
in `Database._migrate()` ONCE.

### RLock rationale

Switching from `threading.Lock` to `threading.RLock` fixes the non-reentrant
workaround in `get_plan_with_items` — the method can now call `get_plan_items`
normally. With `RLock`, cross-repo methods that need to acquire the lock
multiple times (e.g., a `transaction()` block that calls multiple repos) work
without deadlock. Overhead is negligible (a counter + owner thread ID check
vs. a binary flag).

### constants.py — what it centralizes

| Literal | Current sites | Constant |
|---------|--------------|----------|
| `"deepseek-v4-pro"` | 8+: db.py, routes_chat.py, routes_misc.py, tool_deploy.py, routes_config.py, subagents.py | `DEFAULT_MODEL` |
| `"deepseek-v4-flash"` | 4+: routes_chat.py, subagents.py, routes_config.py | `DEFAULT_FLASH_MODEL` |
| `100` (researcher max_steps) | 4×: routes_chat.py + subagents.py ×3 | `RESEARCHER_MAX_STEPS` |
| `999` (orchestrator max_steps) | routes_chat.py | `ORCHESTRATOR_MAX_STEPS` |
| `6200/6800/5000` MB (memory) | agent.py + tui.py (diverging) | `MEM_WARN`, `MEM_HIGH`, `MEM_CRITICAL` |
| `4/2/1` (concurrency) | agent.py | `MAX_CONCURRENT_TOOLS`, `MAX_CONCURRENT_DEPLOYS`, `TOOL_SEM_LOW` |
| httpx `Limits(10, 4)` | deepseek.py + tinyfish.py | `HTTPX_MAX_CONNECTIONS`, `HTTPX_MAX_KEEPALIVE` |
| Subagent labels | 3 dicts diverging (tool_deploy.py, routes_chat.py, chat-store.ts) | `AGENT_LABELS` (decision needed — see below) |
| `CHUNK_SIZE/OVERLAP` (1600/160) | chunker.py | `CHUNK_SIZE`, `CHUNK_OVERLAP` |
| `SUBSCRIBER_BUFFER` (1024) | session_agent.py | `SUBSCRIBER_BUFFER` |
| `KEEPALIVE_SECONDS` (15) | routes_stream.py | `KEEPALIVE_SECONDS` |
| `busy_timeout` (5000) | db.py → database.py | `BUSY_TIMEOUT_MS` |
| `TREE_MAX_DEPTH/ENTRIES` (6/2000) | routes_misc.py | `TREE_MAX_DEPTH`, `TREE_MAX_ENTRIES` |

**Subagent labels decision:** the three dicts disagree on `teacher` vs `maestro`,
absence of `documentalist`/`session_namer`/`evaluator`. Resolution: define a
single canonical `AGENT_LABELS` in `constants.py` with the union of all personas,
using the subagent type name as key. The `teacher`/`maestro` split: `maestro`
refers to the orchestrator persona (the Socratic tutor), `teacher` refers to
a dedicated analysis subagent. Both are separate personas with separate keys
(`"maestro"` and `"teacher"`). The frontend fetches labels from `/api/agents`
(already served by `routes_misc.py:87`). This decision is made within T2.

## Task breakdown

### T2 — constants.py
- Create `src/cognits/constants.py` with all centralized literals.
- Define canonical `AGENT_LABELS` dict.
- Update all sites (~15 files) to import from `constants`.
- `subagents.py` prompt strings are NOT in scope (Phase 4).

### T3 — storage/models.py
- Move all dataclasses (Report, MessageRow, Note, Skill, SkillPrereq, SkillBuild,
  LearnerState, StudyPlan, StudyPlanItem, SessionConfigRow) from `db.py` to `models.py`.
- Move ID generators (new_report_id, new_note_id, etc.) and FTS helpers
  (escape_like, build_fts5_query, _clamp, _SORT_SQL, _unmarshal_sources).
- Move constant enums (EDGE_TYPES, PLAN_STATUS, etc.).
- Move BASE_SCHEMA string.
- `db.py` imports models.

### T4 — storage/database.py
- Extract `Database` class from `ReportStore.__init__` + `_check_fts5` +
  `_migrate` + `_backup` + `shutdown` + `close` (unified into `shutdown`).
- Switch `threading.Lock` → `threading.RLock`.
- Add `transaction()` context manager (BEGIN/COMMIT/ROLLBACK with RLock).
- `BASE_SCHEMA` lives here (or in models.py — decided: models.py owns the
  string, Database.run_migration() executes it).

### T5 — per-domain repositories
Create 8 new files. Each repo:
- Takes `db: Database` at `__init__`.
- Methods use `with self.db.lock:` for single-operation autocommit writes.
- Methods use `with self.db.transaction():` for multi-statement writes (only
  the methods that need it: `upsert_skill`, `replace_plan_items`, `reorder_notes`).
- Data model: repo methods accept/return dataclasses from `models.py`.
- FTS5 queries co-located (e.g., `search_reports_fts` in ReportRepository).

### T6 — Migrate callers + delete ReportStore
- Update `AppState` (app.py): create `Database`, all 8 repos. Remove
  `state.report_store`.
- Update every caller (~20 files):
  | Call site | Old | New |
  |-----------|-----|-----|
  | `routes_reports.py` | `st.report_store.get/save/search/delete` | `st.reports.*` |
  | `routes_chat.py` | `st.report_store.save_messages/append_message/load_messages + get_skill/get_learner_state/get_pedagogical_plan + ...` | `st.messages.* / st.skills.* / st.learner_state.* / st.pedagogy.* / ...` |
  | `routes_misc.py` | `st.report_store.*` | per-domain |
  | `routes_sessions.py` | `st.report_store.delete_messages/delete_session_config` | `st.messages.delete_by_session / st.session_config.delete` |
  | `routes_stream.py` | `st.report_store.load_messages` | `st.messages.load` |
  | `routes_notes.py` | `st.report_store.*` | `st.notes.*` |
  | `routes_skills.py` | `st.report_store.*` | `st.skills.* / st.learner_state.*` |
  | `tool_deploy.py` | `self.report_store.save` | `self.reports.save` |
  | `tool_skill.py` | `self.report_store.*` | `self.skills.*` |
  | `tool_study_plan.py` | `self.store.*` | `self.plans.* / self.skills.* / self.learner_state.*` |
  | `tool_mastery.py` | `self.store.*` | `self.learner_state.*` |
  | `pedagogical_plan.py` | `self.store.*` | `self.pedagogy.* / self.skills.*` |
  | `app.py` lifespan | `state.report_store.shutdown()` | `state.db.shutdown()` |
  | `tui.py` _shutdown | `self._state.report_store.shutdown()` | `self._state.db.shutdown()` |
- Delete `storage/db.py`.
- Update all tests.

### T7 — Fix transaction smells
- `upsert_skill` → wrap skill upsert + learner_state seed in `db.transaction()`.
- `replace_plan_items` → wrap delete + reinsert in `db.transaction()`.
- `reorder_notes` → wrap loop of updates in `db.transaction()`.
- FTS rebuild symmetry: `_migrate` now rebuilds `skills_fts` too.
- `get_plan_with_items` now calls `get_plan_items` (RLock makes this safe).

### T8 — Tests
- New per-repo tests with `:memory:` or tmp-file fixtures.
- Transaction rollback tests.
- RLock reentrancy test (get_plan_with_items calls get_plan_items).
- All existing tests adapted to new API (part of T6).

## Test plan

| Test file | New/Update | Covers |
|-----------|------------|--------|
| `tests/test_db.py` | Removed (replaced by per-repo tests) | — |
| `tests/test_reports.py` | NEW | ReportRepository CRUD + FTS5 |
| `tests/test_messages.py` | NEW | MessageRepository save/append/load/delete |
| `tests/test_notes.py` | NEW | NoteRepository CRUD + reorder + transaction |
| `tests/test_skills.py` | NEW | SkillRepository + edges + FTS + builds |
| `tests/test_learner_state.py` | NEW | LearnerStateRepository |
| `tests/test_study_plans.py` | NEW (replaces study_planner test repo part) | StudyPlanRepository + transaction |
| `tests/test_pedagogical.py` | NEW | PedagogicalPlanRepository |
| `tests/test_session_config.py` | NEW | SessionConfigRepository |
| `tests/test_database.py` | NEW | Database shutdown + transaction |
| Adapted tests | UPDATE | test_deploy_cancel, test_skills_api, test_planning_mode, test_teacher, test_study_planner, test_evaluator, test_skill_planner |

## Risk notes

1. **T6 is the highest-risk task** — ~20 callers migrated mechanically.
   Mitigation: one commit per domain group, full test suite after each,
   `grep report_store` to verify zero remaining references at the end.

2. **RLock impact** — well-understood change. No perf impact (single-writer,
   no contention). Already validated by SOTA research.

3. **`db.transaction()` vs autocommit** — repos use autocommit for single-statement
   writes, `db.transaction()` for multi-statement. This is the standard pattern.
   `isolation_level=None` remains. No risk of uncommitted data leaking.

4. **SCHEMA_VERSION stays 1** — `_migrate` moves to `Database` but keeps the
   same idempotent logic. BASE_SCHEMA unchanged.

5. **Module naming** — `storage/learner_state.py` avoids collision with
   `learner/` package. `storage/session_config.py` avoids confusion with
   `server/routes_config.py`.

6. **constants.py** — literals that are configuration (not truly constant)
   should still read env vars as before (e.g., `_DRAIN_TIMEOUT` stays
   `float(os.environ.get("COGNITS_DRAIN_TIMEOUT", "5.0"))`). Pure constants
   (model names, limits) go into `constants.py` as simple attributes.

7. **Delete db.py** — `ReportStore` is removed. `db.py` can be deleted or
   kept as a re-export stub during T6's migration window. After T6 completes,
   it's deleted. `grep ReportStore` across src/ and tests/ must return 0.
