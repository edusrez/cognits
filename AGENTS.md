# Cognits — AI Tutoring System (antes Learn It)

> **Note:** AGENTS.md is the technical reference for coding agents working on this
> codebase. For the full product vision, pedagogical architecture, and roadmap, see
> [IDEA.md](IDEA.md). The design conversation that shaped the vision is in
> [CONVERSACIÓN_CON_LA_IDEA.md](CONVERSACIÓN_CON_LA_IDEA.md).
>
> **Migration note (jun 2026):** the backend was rewritten from Go to Python
> (package `cognits`, CLI `cognits`, distributed via `uv tool install cognits`).
> The original Go implementation is preserved in `legacy/` as reference until
> deleted. The frontend and the HTTP/SSE API contract are unchanged.

## Standing Orders (CRITICAL — override all other behavior)

1. **RESEARCH**: Before answering questions that require external knowledge,
   documentation, web search, or technology evaluation, invoke `@researcher`
   via the task tool. **Include today's date** (from `<env>`) in the task
   description you pass. Do NOT answer research questions from training data.

2. **SKILLS**: At the start of each context, load the `multi-agent-workflow`
   skill using the `skill()` tool. It defines the delegation protocol and
   agent roster — required for every session. Additional skills are
   available — load on-demand when a task matches:
   - `solidjs-patterns` — SolidJS components, signals, stores, JSX (frontend)
   - `tailwind-v4` — Tailwind CSS v4 conventions, @theme, OKLCH (frontend)
   - `sqlite-fts5` — FTS5 full-text search, triggers, BM25, schema migration
   - `sse-streaming` — Server-Sent Events (backend + SolidJS frontend)
   - `deepseek-api` — DeepSeek streaming API, reasoning mode, prompt cache
   - `multi-agent-tools` — Tool registry, subagent spawning, event relay

3. **SKILL WORK**: When asked to create, modify, or research skills, invoke
   `@skill-writer` via the task tool.

4. **CODE EXPLORATION**: For codebase structure or pattern search, invoke
   `@explore` via the task tool.

5. **WORKFLOW**: Write specs first. Delegate code changes to builder
   subagents (one atomic task each, non-overlapping files). After each
   batch: `uv run pytest -q`. Commit after each logical unit. The primary
   agent orchestrates — it does NOT edit files itself (see §7).

6. **NO MICRO-DECISIONS**: When any implementation detail is ambiguous or not
   explicitly specified by the user, the model MUST ask the user before
   proceeding. This applies both during planning and building phases. Do NOT
   assume defaults, conventions, or "reasonable" choices — present the options
   and let the user decide.

7. **DELEGATION (CRITICAL for context efficiency)**: The primary agent is an
   **orchestrator**, not an implementor. It MUST delegate work to subagents
   and MUST NOT do the work itself, with these rules:

   - **Research / external knowledge** → `@researcher` via the task tool.
     NEVER answer research questions from training data. NEVER fetch URLs
     yourself — researcher does it. Researcher writes reports to
     `_research/` that other agents can read.
   - **Codebase exploration / pattern search** → `@explore` (V4 Pro max,
     fast pattern finding: "where is X", "find all uses of Y") or
     `@explore-deep` (GLM 5.2, in-depth analysis: "trace the flow from A
     to B", "how does X interact with Y") via the task tool. NEVER read
     files one-by-one yourself when a search would suffice.
   - **Code changes (edits, tests, refactors)** → `builder` (flash, default),
     `builder-pro` (pro, complex), or `builder-max` (pro max, escalation)
     via the task tool. Dispatch MULTIPLE builders in PARALLEL when tasks
     touch non-overlapping files. NEVER use the Edit/Write tools yourself
     for code changes — that's what builders are for. The primary agent
     should only use Bash for verification commands (pytest, build, git).
   - **Code review** → `reviewer` via the task tool, auto-triggered after
     each builder or batch. The reviewer is read-only and returns PASS/FAIL.
   - **Documentation drafts** → `scribe` via the task tool, at session wrap
     or after significant features. Scribe drafts to `_drafts/` only.
   - **Escalation**: if a builder fails twice, escalate to the next tier
     (builder → builder-pro → builder-max). Do NOT retry the same tier
     more than twice.
   - **When the primary CAN act directly**: reading a single file to answer
     a quick question, running a verification command, committing, or
     asking the user a microdecision. If in doubt, delegate.

## Identity
Cognits is NOT a coding agent. It NEVER writes, edits, or modifies the user's code.
It is a Socratic tutor that helps the user understand concepts, debug their thinking,
and discover answers through guided inquiry.

## Stack
- Backend: Python 3.11–3.13, FastAPI + uvicorn (asyncio)
- Frontend: SolidJS + Tailwind CSS 4 + Vite (unchanged from the Go era)
- Runtime: Bun (dev/build only, not for distribution)
- LLM: DeepSeek V4 Pro via OpenAI-compatible API (httpx streaming)
- Web Search: TinyFish (search + fetch API)
- DB: SQLite stdlib (`sqlite3`, FTS5, WAL, sqlite-vec 0.1.9, single locked connection)
- RAG: sqlite-vec vec0 (active dense store, brute-force KNN; cosine via L2
  on normalized BGE-M3 vectors) + fastembed 0.8.0 (BGE-M3 ONNX) in a
  worker_proc (embed/query_embed via Pipe RPC).
  Hybrid search: FTS5 BM25 + vec0 dense → RRF → cross-encoder reranker.
  ChromaDB was removed in 0.0.7 (silent HNSW corruption risk, ~23 MB deps,
  single-DB philosophy).
- Packaging: uv + hatchling, wheel `py3-none-any` with the frontend dist as
  package data; `uv tool install cognits`

## Build & Run

### 3-stage workflow (dev → smoke test → publish)
```bash
# Stage 1: fast iteration (source, no packaging)
scripts/dev.sh          # Vite HMR (5174) + uvicorn --reload (5173, ENV=dev)
uv run cognits          # run from source (serves embedded frontend_dist)

# Stage 2: smoke test the wheel before publishing
scripts/build.sh        # typecheck + vite build → src/cognits/frontend_dist → uv build
scripts/test_install.sh # uv build + uv tool install --reinstall --force + --version check
cognits --version       # verify installed version

# Stage 3: publish
uv publish              # publish to PyPI (when ready)
```

### Test commands
```bash
uv run python -m pytest -q            # all tests (crypto, DB/FTS5, chunker, agent loop, SSE framing, teacher prompt, skills API, HTTP routes, planning mode, onboarding, learner model, deploy cancel, database, reports, deepseek streaming, exceptions, agent loader, tool files, tool RAG, chat service, tracer, apply profile)
uv run pytest tests/test_X.py -x    # single file, stop on first failure
uv run pytest tests/test_X.py::test_name -x --tb=short  # single test
```

Env vars: `PORT` (default 5173), `COGNITS_HOST`/`LEARNIT_HOST` (default
127.0.0.1), `ENV=dev` (proxy to Vite), `COGNITS_DISABLE_RAG=1` (skip model
load — useful in dev/tests; first RAG start downloads ~2.3 GB BGE-M3;
automatically set by `tests/conftest.py` autouse fixture for all tests,
so `uv run pytest` works without the explicit prefix),
`COGNITS_JOURNAL_MODE` (override SQLite journal mode:
wal/delete/truncate/persist/memory).

## Project Structure

### Backend (`src/cognits/`)

| File | Purpose | Go reference (legacy/) |
|------|---------|------------------------|
| `main.py` | Entry point: uvicorn programmatic, signal handling (1st Ctrl+C drains agents ≤5s, 2nd hard-kills), browser open | `cmd/learnit/main.go` |
| `paths.py` | Data dir `cwd/.cognits` (uses `.learnit` in place if present), DB filename resolution, Go-compatible `user_config_dir()` (Windows: Roaming) | — |
| `server/app.py` | `AppState` (store, 8 per-domain repos, cached_config, active_agents, rag, docling_engine), app factory, RAG lifespan, `drain_agents` | `internal/server/server.go` |
| `server/session_agent.py` | `SessionAgent`: pub/sub with atomic snapshot+subscribe. ALL methods sync, event-loop only (see invariant in module docstring) | `server.go:22-95` |
| `server/routes_chat.py` | POST /api/chat (409/401/202), config cascade, `build_chat_messages` (Spanish date stamp ONLY on last user msg — prefix cache), delegates to `server/chat_service.py` (ChatService: agent lifecycle, subagent map, tool registry, SSE bridge, sync persist) | `internal/server/chat.go` |
| `server/routes_stream.py` | SSE wire format: history first, tokens unnamed (OpenAI delta), keepalive 15s, drain + `done` (`null` live / `{}` snapshot) | `internal/server/session_stream.go` |
| `server/routes_sessions.py` | Session CRUD (id `%Y-%m-%dT%H-%M-%S`, JSON files) | `internal/server/sessions.go` |
| `server/routes_config.py` | Global config GET/PUT, key masking `••••`+4, mask-preserve on PUT, provider/model/reasoning whitelists | `internal/server/config.go` |
| `server/routes_reports.py` | Reports CRUD + LIKE search + FTS5 (BM25 10/3/1, `<mark>` highlight) | `internal/server/reports.go` |
| `server/routes_misc.py` | health, tree (depth 6, budget 2000), agents, messages, session_config, desktops | `api.go`, `agents.go`, `messages.go`, `session_config.go`, `desktops.go` |
| `server/frontend.py` | Serves `frontend_dist` package data; index no-store + cache-buster regex | `internal/server/frontend.go` |
| `server/devproxy.py` | ENV=dev: HTTP+WebSocket passthrough to Vite (replaces rebuild.go/air) | `frontend.go:22-27` |
| `server/browser.py` | Browser opener (WSL-aware) | `internal/server/browser.go` |
| `server/chat_service.py` | `ChatService`: extracted from `routes_chat.py` — agent lifecycle, subagent map builder, tool registry, SSE event bridging, sync persist (`_persist_partial`), session naming (`_run_session_namer`), context compaction (`_compact`), async reflection (`_reflect_async`) | — |
| `server/exceptions.py` | `CognitsError` hierarchy (base + NotFoundError, SessionNotFound, AgentBusy, ConfigError, StorageError). Registered in `app.py` via `@app.exception_handler` → `{"error", "message", "details"}` JSON shape | — |
| `server/routes_notes.py` | Notebook CRUD routes — notes stored in SQLite | — |
| `server/routes_skills.py` | Skill tree read endpoints (list, tree, learner state) | — |
| `server/routes_files.py` | File content/raw endpoints (text mode + Docling PDF→Markdown) | — |
| `server/dependencies.py` | FastAPI dependency injection: `get_app_state(request)` | — |
| `server/util.py` | Helpers: `text_error` (deprecated), `atoi`, `mask_key`, `MONTHS`/`WEEKDAYS` | — |
| `constants.py` | Centralized literals: model names, max_steps, memory thresholds, concurrency limits, httpx limits, LLM timeouts, mastery threshold, chunk sizes, SSE buffer, name caps, subagent labels, context compaction, reflection loop, TOOL_PHRASES, INTERNAL_SUBAGENTS | — |
| `agent/agent_loader.py` | Parses `agent/agents/*.md` (YAML frontmatter + Markdown body) into `AgentConfig` | — |
| `agent/agents/` | 11 persona `.md` files: web_researcher, documentalist, directory_reader, session_namer, session_analyzer, skill_planner, study_planner, evaluator, maestro, orchestrator, system_support | — |
| `agent/tracer.py` | `Tracer`: structured JSONL trace logging to `.cognits/traces/{session_id}.jsonl`. Wired into `ChatService.run_agent()` and `Agent.__init__` (constructor injection). `emit()` called in agent loop with 6 event types (llm_start, usage, tool_start, tool_end, finish, error). Passed to subagents via `DeploySubagent(tracer=)`. `NoopTracer` for tests. | — |
| `agent/token_counter.py` | `TokenCounter` using `deepseek_tokenizer` (128K BPE, falls back to chars/3.5) | — |
| `agent/agent.py` | Agentic loop: stream → sparse-index tool call accumulation → execute → repeat; tool errors fed back as `{"error": ...}`. `AgentConfig` has `critique_mode` and `tool_registry` fields. Tracer injected via constructor. | `internal/agent/agent.go` |
| `agent/prompts.py` | Agent personas (orchestrator, maestro, system_support, web_researcher, etc.). Prompt text loaded from `agent/agents/*.md` via `agent_loader` | `internal/agent/prompts.go` |
| `agent/subagents.py` | 9 subagent configs (researcher, directory_reader, documentalist, skill_planner, study_planner, evaluator, teacher, session_analyzer, session_namer) + TinyFish tools, deployment wrapping | `internal/agent/subagents/` |
| `agent/tool_deploy.py` | `DeploySubagent`: run subagent → save report → index chunks in RAG → `subagent_end`. Emit wrapper stamps `id`/`parentId`/`parentAgent` on events. Cancel ⇒ no report; failure ⇒ error tool result + clears banner | `internal/agent/tools/deploy.go` |
| `agent/tool_rag.py` | `rag_search` tool | `internal/agent/tools/rag_search.go` |
| `agent/tool_ui.py` | UI action tools: `CreateLearningSession` emits `create_learning_session` SSE event + hides orchestrator session; `FinishSetup` | — |
| `llm/types.py` | `Message`/`ToolCall` with omitempty payload semantics | `internal/llm/llm.go` |
| `llm/deepseek.py` | httpx streaming; idle watchdog = `read=120` timeout; thinking omitted when tools present; retryable error classification (HTTP 429/5xx, ReadTimeout) | `internal/llm/deepseek.go` |
| `llm/base.py` | `LLMClient` Protocol: async streaming interface for any LLM provider. Implementations: `DeepSeekClient` (future: OpenAI, Anthropic). | — |
| `tools.py` | Tool registry, name-sorted `definitions()` (prefix cache) | `internal/tools/tools.go` |
| `tinyfish.py` | TinyFish search/fetch (X-API-Key, configurable timeout) | `internal/tinyfish/client.go` |
| `rag/engine.py` | RagEngine: sqlite-vec vec0 (active dense store). BGE-M3 ONNX via fastembed in worker_proc. `search_hybrid()` with RRF fusion (FTS5 BM25 + dense + cross-encoder reranker) — activated in `rag_search` tool. `db.vector_index` for idempotent re-index (ON CONFLICT DO UPDATE on report_chunks). Worker respawns on `EOFError` (OOM recovery). `ready`/`error` gating. `set_db()` wires the Database. | `internal/rag/` + `sidecar.py` |
| `rag/chunker.py` | Markdown chunker: `split_markdown()` (1600/160 chars, fences atomic) + `split_markdown_v2()` (paragraph-aware, respects headers, `parent_section` metadata). IDs `{report_id}_c{idx}`. | `internal/rag/chunker.go` |
| `rag/embedding_worker.py` | BGE-M3 ONNX inference worker process (embed/query_embed via Pipe RPC, 3 GB RLIMIT) | — |
| `storage/nn` | SQLite files |
| `storage/database.py` | `Database` (single connection, RLock, WAL pragmas, `_migrate`, `transaction()` context manager, `shutdown`) | `internal/storage/db.go` |
| `storage/fsdetect.py` | Filesystem detection for SQLite journal-mode selection: `/proc/mounts` longest-prefix match, `WAL_UNSAFE_FSTYPES` denylist, `choose_journal_mode()`, `COGNITS_JOURNAL_MODE` env var | — |
| `storage/models.py` | Data models: 10 dataclasses (Report, MessageRow, Skill, etc.) + ID generators + FTS helpers | — |
| `storage/reports.py` | `ReportRepository`: CRUD + FTS5/LIKE search + BM25 | — |
| `storage/messages.py` | `MessageRepository`: save/append/load/delete_by_session | — |
| `storage/notes.py` | `NoteRepository`: CRUD + reorder | — |
| `storage/skills.py` | `SkillRepository`: skills tree + prerequisites + builds + FTS5 | — |
| `storage/learner_state.py` | `LearnerStateRepository`: BKT+FSRS upsert/get/get_all | — |
| `storage/study_plans.py` | `StudyPlanRepository`: plans + items + lifecycle | — |
| `storage/pedagogical.py` | `PedagogicalPlanRepository`: save/get | — |
| `storage/session_config.py` | `SessionConfigRepository`: save/load/delete | — |
| `storage/files.py` | Sessions JSON, config with AES-GCM (bit-compatible with Go; key reused from `~/.config/learnit/`, copied to `~/.config/cognits/`) | `internal/storage/storage.go` |
| `learner/model.py` | BKT soft-evidence model + 6-level mastery classifier + FSRS integration | — |
| `learner/fsrs.py` | FSRS-6 spaced repetition scheduler (Anki 24.11 defaults) | — |
| `learner/planner.py` | Deterministic study plan generation: ALEKS outer fringe, BFS goal distances, weighted scoring, adaptive proficiency thresholds | — |
| `learner/pedagogy_engine.py` | External stage management for pedagogical plans: 5-stage progression (activate→introduce→guided→assess→wrap_up). Wired into `ChatService` per maestro session; manages transitions externally to prevent LLM non-compliance. `scaffolding_level` persisted in `learner_state`. | — |

### Frontend (`frontend/src/`) — 65 files, 8615 lines

**Stores (11):** `chat-store.ts` (messages, streaming, tool status), `chat-connection.ts`
(SSE reconnect wrapper), `session-store.ts`, `settings-store.ts` (config, agents, pricing),
`desktop-store.ts` (multi-desktop), `learnit-store.ts` (report search), `notebook-store.ts`,
`report-store.ts`, `setup-store.ts`, `viewport-tree-store.ts` (split-pane viewport tree),
`skills-store.ts` (skill tree + learner state).

**Components (24):** `Chat.tsx` (message list + streaming + tool status), `StreamingMessage.tsx`
(streaming-markdown), `SkillsTree.tsx` (DAG with mastery badges), `MasteryDashboard.tsx`
(learner state overview), `Viewport.tsx` (tab bar + content dispatcher), `Sessions.tsx`,
`Settings.tsx`, `SetupWizard.tsx`, `LearnitView.tsx` (report search/browse), `ReportView.tsx`,
`NoteView.tsx`, `CodeView.tsx`, `TextView.tsx`, `ImageView.tsx`, `PdfView.tsx`, `TabBar.tsx`,
`ContextMenu.tsx`, `DragOverlay.tsx`, `Dropdown.tsx`, `SliderField.tsx`, `Write.tsx`,
`MarkdownView.tsx`, `CollapsibleSection.tsx`.

**Lib (8):** `chat-stream.ts` (SSE client via fetch+ReadableStream), `markdown.ts`
(marked+hljs+DOMPurify), `api.ts` (centralized fetch wrapper), `sse-types.ts` (SSE event
TypeScript types), `tab-kinds.ts`, `settings-sections.ts`, `clipboard.ts`, `file-category.ts`.

All API calls are same-origin relative `/api/*`. AGENT_LABELS loaded from `/api/agents`.

## Architecture invariants (do not break)

### Concurrency model (asyncio replaces goroutines)
- **Everything shared lives on the event loop.** `SessionAgent.publish()` and
  `subscribe_with_snapshot()` are synchronous → atomic in asyncio. An event is
  either in the snapshot or in the queue, never both (the token-duplication
  race). Never call them from threads (use `loop.call_soon_threadsafe`).
- Blocking I/O (sqlite3, fastembed) goes through `asyncio.to_thread`
  or the RAG 1-thread executor. Handlers are `async def`.
- The agent run is an `asyncio.Task`; its `finally` block is 100% synchronous
  (incl. direct sqlite append of the partial response) so a second
  cancellation cannot skip cleanup at an await point.
- Shutdown order: drain agents FIRST, then `server.should_exit = True` —
  uvicorn waits for in-flight SSE connections, which only end when the drain
  closes their `done_event` (reverse order deadlocks).

### SSE wire format (frontend contract)
- `history` always first (atomic snapshot), `done` always last.
- Token frames have NO `event:` line; payload `{"choices":[{"delta":{"content":...}}]}`.
- Named events: `reasoning`, `error`, `tool_start`, `tool_end`,
  `tool_progress`, `subagent_end`, `usage` (usage is snake_case; all else camelCase).
- `tool_progress` data: `id` (per-deploy hex), `agent` (config name),
  `parentId`/`parentAgent` (null for top-level, stamped by parent wrapper for
  nested), `message`, `favicons?`. Favicons are NEVER cleared on Thinking/Writing
  transitions — only updated when the `favicons` key is present in the event data.
- `subagent_end` data: `id`, `agent`, `parentId`/`parentAgent`, `internal` (bool),
  `reportId?`, `title?`, `summary?`.
- `SessionAgent.tool_log` (in-memory, NOT persisted) is the source of truth for
  the frontend tool panel: a list of `{id, agent, parentId, parentAgent, message,
  favicons, done}` entries, upserted by `id` on `tool_progress`, marked `done`
  on `subagent_end`. Reset each turn. Snapshot includes `toolLog`.
- `TOOL_PHRASES` dict in `constants.py` maps tool name → status phrase; default
  "Working..." (NEVER "Searching the Web..." for unknown tools).
- Extra UI events: `session_renamed`, `ui_action`, `setup_complete`,
  `create_learning_session` (sent by backend, consumed by frontend).
- `: keepalive` comment every 15s. Queue (1024) drops on overflow — DB reload
  on `done` is the safety net.
- Two `done` variants: `data: null` (live route) and `data: {}` (snapshot route).

### Storage
- `INSERT ... ON CONFLICT DO UPDATE`, never `INSERT OR REPLACE`, on all
  tables (consistent even on tables without FTS5 external-content indexes).
- API keys encrypted AES-GCM (`base64(nonce12 ‖ ct ‖ tag16)`), key at
  `user_config_dir()/cognits/encryption.key`; API masks keys (`••••`+4) and
  PUT preserves them when the mask is echoed back.
- Data dir: `cwd/.cognits` (a pre-existing `cwd/.learnit` is used in place).
  DB file: `cognits.db` (or pre-existing `learnit.db`).
- Journal mode auto-detection: `Database` inspects the filesystem type via
  `/proc/mounts` longest-prefix match. WAL-unsafe fstypes (DrvFs/9p, CIFS,
  NFS, FUSE) fall back to `journal_mode=MEMORY` + `synchronous=OFF`; safe
  filesystems keep `WAL` + `NORMAL`. Override with `COGNITS_JOURNAL_MODE`
  env var (one of `wal`/`delete`/`truncate`/`persist`/`memory`).
- `Database.journal_mode` is read back from SQLite after connect (it may
  silently downgrade) and logged at startup. `shutdown()` only runs
  `wal_checkpoint(TRUNCATE)` when the current mode is `"wal"`.
- Detection logic in `src/cognits/storage/fsdetect.py`: `choose_journal_mode()`
  + `WAL_UNSAFE_FSTYPES` denylist (includes `fuse.*` catch-all via
  `startswith("fuse.")`).
- `Session` dataclass (JSON files, not SQLite) has a `hidden: bool = False` field.
- `CreateLearningSession` tool hides the orchestrator's planning session
  after emitting `create_learning_session`.
- `GET /api/sessions` excludes hidden sessions by default;
  `?include_hidden=true` includes them.
- `PUT /api/sessions/{id}` accepts `{"hidden": bool}` to hide/unhide
  (optionally combined with `{"name": ...}`).
- `Store.list_sessions(include_hidden=False)` filters AFTER ordering
  (preserves manual reorder).

### Error responses
- Routes raise `CognitsError` subclasses (`NotFoundError`, `StorageError`,
  `AgentBusy`, `ConfigError`, etc.) which the `@app.exception_handler` in
  `app.py` converts to `{"error": code, "message": msg, "details": {...}}`.
- All route files migrated from legacy `text_error` (plain-text) to
  `CognitsError` subclasses (0.0.7 hardening). `text_error` is removed
  from all route imports.

### LLM / prompt cache
- Tool definitions sorted by name; date stamp only on the last user message;
  history persisted unstamped. Breaking either invalidates DeepSeek's prefix cache.
- Thinking param omitted when tools are present (API rejects the combination).

### Session naming
- First-turn naming: `_run_session_namer` filters `role in ("user", "hidden_user")`
  (not just `"user"`). Learning sessions (which start with a `hidden_user`
  instruction to the maestro) get a real name instead of keeping the timestamp.
- The session_namer prompt handles both real user messages and internal tutor
  instructions (infers the skill/topic, does not name after the literal
  "Start teaching..." text).

### Reflection loop (Teacher/Evaluator)
- Post-send async review: the maestro's response reaches the learner
  IMMEDIATELY; a fire-and-forget background task (`_reflect_async`) runs the
  evaluator ONCE after the turn (no-op emit, invisible to the user). No
  in-place revision.
- If verdict != `"pass"` OR `socratic_violations` non-empty, the critique is
  stored in `AppState.pending_critiques[sid]` and injected as a system message
  at the START of the next maestro turn (after compaction, before `ag.run`).
- Coherence trap mitigation: evaluator prompt says "evaluating a DIFFERENT
  agent's response. Be skeptical."
- Gated on `agent_id == "maestro"` + `acc["content"]` +
  `Config.reflection_enabled` (default `True`).
- `_reflect_async` never touches `SessionAgent` (uses `_noop_emit`, writes only
  `pending_critiques`) — `sa` may be torn down by the time it runs.
- The `finally` block remains 100% synchronous; the background task is scheduled
  in the `try` block, not `finally`.
- `REFLECTION_MAX_ITERATIONS` constant remains in `constants.py` but is unused
  (the revision loop was removed in 0.0.7).

### Subagent relay contract
- All research subagents (web_researcher, documentalist) MUST include a
  `key_findings_for_orchestrator` field (1-3 sentences) in their output.
  Prevents the "information withholding" anti-pattern.

### Internal subagents
- `AgentConfig.internal: bool = False` (set True on evaluator,
  session_analyzer, session_namer via `subagents.py`).
- Internal subagents' reports are saved to DB + RAG-indexed but do NOT
  surface as chat cards (`sa.live_reports` gated on `internal=False`;
  frontend `onSubagentEnd` skips the report card when `data.internal`).

### DeploySubagent event stamping
- `DeploySubagent.execute()` generates a per-run `instance_id` (hex).
- Its `emit` wrapper stamps events with three patterns:
  - No `id` → stamp `id` + `agent` (for pass-through events like favicons
    from SearchTool/FetchTool that have no id).
  - `id` present but no `parentId` → stamp `parentId` + `parentAgent` (nested
    subagent event).
  - Both `id` and `parentId` present → pass through unchanged (deeper nested).

### LLM client architecture
- `LLMClient` Protocol defines the async streaming interface. `DeepSeekClient`
  is the current implementation. Adding a new provider (OpenAI, Anthropic)
  = implement the Protocol + add a provider config block.
- Model format: `provider/model-id` (e.g., `deepseek/deepseek-v4-pro`).
  Backward compat with bare model IDs (`parse_model()` in `constants.py`).
- Provider config blocks: `api_key`, `base_url`, per-model capabilities
  (`context_window`, `supports_thinking`) in `MODEL_REGISTRY` +
  `Config.providers` dict (flat `llm_*` fields remain as backward compat).
- `DeepSeekClient` accepts a per-provider `base_url` parameter.
- `get_context_window(model)` looks up `MODEL_REGISTRY` for compaction
  (replaces the hardcoded `MODEL_CONTEXT_WINDOW` constant).
- Error classification: `DeepSeekError.retryable` for transient errors
  (429, 5xx, ReadTimeout). Permanent errors fail immediately.
- Prompt cache: `prompt_cache_hit_tokens` extracted from usage events
  and logged in tracer for per-agent cache hit ratio.

### Tracer (observability)
- `Tracer.emit()` is called in the agent loop with 6 event types:
  `llm_start`, `usage` (with `cache_hit`/`cache_miss`), `tool_start`,
  `tool_end` (with `duration_ms`), `finish`, `error`.
- Tracer is passed to subagents via `DeploySubagent(tracer=)` and to
  the reflection revision agent + session namer.
- `NoopTracer` is the default for tests.

### PedagogyEngine (external stage management)
- `PedagogyEngine` is instantiated per maestro session in `ChatService`,
  restored from `learner_state.scaffolding_level`, and manages 5-stage
  transitions externally (activate→introduce→guided→assess→wrap_up).
- After each teacher turn: `record_interaction()` → `should_advance()`
  → `advance()` + persist `scaffolding_level` + publish `ui_action`.
- The `finally` block remains 100% synchronous (pedagogy logic is in
  the `try` block, before `finally`).

### RAG hybrid search
- `rag_search` tool calls `search_hybrid()` (FTS5 BM25 + dense + RRF +
  cross-encoder reranker), not dense-only `search()`.
- `reports_repo` is wired into `RagSearch` at all call sites.
- `search_fts` is wrapped in `asyncio.to_thread` (off the event loop).
- `db.vector_index` (not `collection.upsert`) — idempotent re-indexing via
  ON CONFLICT DO UPDATE on report_chunks.
- Worker respawns on `EOFError`/`BrokenPipeError` (OOM recovery).

## Design System

For ALL visual decisions — colors, typography, spacing, component styling,
animation, and UI patterns — consult `DESIGN.md` at the repository root.
DESIGN.md is the single source of truth for how Cognits looks and feels
(Google Labs DESIGN.md spec; validate with `npx @google/design.md lint`).

Key rules (full detail in DESIGN.md):
- **Dark-first, monochrome.** No light mode. No chromatic accent (no blue,
  no green-as-accent). Grays + functional red (error) / amber (warning) only.
- **Tool status = bordered square + fill.** Running = empty square (gray
  frame `#555`, black interior `#0d0d0d`); done = filled square (`#cccccc`);
  error = red frame (`#e74c3c`). NO pulse, NO spinner — the fill transition
  (200ms) IS the indicator. Pattern from the textual TUI (`tui.py` SPINNER).
- **No shadows for elevation** (except context menus/dropdowns). Use the
  surface ladder (background color contrast) + hairline borders.

## Design Patterns (frontend)
- Store-driven reactivity via `createMemo` (never destructure store props).
- Unified global context-menu signal (discriminated union).
- `structuredClone(unwrap(store))` to clone SolidJS stores.
- Token batching in chat-store (deltaTime-based RAF draining at ~1200
  chars/sec, flushAll on tool boundaries).
- Autoscroll via `createEffect` (scroll-to-bottom when `autoScroll()` is
  true) + bidirectional IntersectionObserver; CSS `overflow-anchor` as
  supplementary.
- Centralized `apiFetch()` wrapper in `lib/api.ts` (error normalization, JSON parsing).
- SSE event types in `lib/sse-types.ts` (TypeScript contract mirroring backend wire format).
- AGENT_LABELS loaded from `/api/agents` (single source of truth, no hardcoded labels).
- Don't dump docs into LLM context — use curated reports (context rot).
- Skill tree mastery colors match the grayscale-only palette (per DESIGN.md):
  `#cccccc` (mastered) → `#a8a8a8` (proficient) → `#7a7a7a` (developing) →
  `#555555` (emerging) → `#2b2b2b` (not_seen). No chromatic accent —
  replaces the earlier green/lime/yellow/orange scheme.
- SkillsTree renders a parent-tree view (by `parentSkillId`, no domain
  grouping); roots = no parent, orphans → root, depth-indented. READ-ONLY:
  no edit UI in 0.0.7.
- `GET /api/skills/tree` response includes a `states` map
  (`skillId → LearnerState`) so the frontend renders real mastery without
  per-skill calls.
- The `skills` tab is included in the default desktop
  (`createDefaultTree` in `viewport-tree-store.ts`).

## Known deferred items (0.0.7 → 0.0.8)

- **P3 (Chat UX enhancements):** active agent indicator (pulse animation) and
  collapsible tool panels implemented in 0.0.7. Browser-tab favicon/title
  updates during tool execution remain out of scope (user decision).
  Auto-scroll via IntersectionObserver was already implemented.

(Items previously listed here — GrepCode/GlobFiles async, vec0/ChromaDB
cutover, AGENT_LABELS from /api/agents, CI test workflow, Phases 4-8 specs —
were implemented in 0.0.7 per `docs/specs/0.0.7-0.0.8-bringforward.md`.)

## DB Schema Versioning Rule

**SCHEMA_VERSION stays at 1 during all 0.0.X pre-releases.** We are still
defining the canonical schema. Schema migrations (`ALTER TABLE`, new
columns, etc.) run unconditionally for inherited databases (those that
existed before versioning was introduced, detected as `PRAGMA user_version
= 0`). Semantic versioning of the schema starts at 0.1.X when the DB
format stabilizes. Until then, any agent touching `database.py` must:

- Keep `SCHEMA_VERSION = 1`.
- Add new schema changes as idempotent `ALTER TABLE` checks inside the
  `if version < 1:` block in `_migrate()`.
- Update `BASE_SCHEMA` to reflect the canonical schema.
- Do NOT bump `SCHEMA_VERSION`.

## Memory / OOM prevention (WSL)

The process may use ~7 GB RSS under load (BGE-M3 ONNX model,
multi-web_researcher). On machines with ≤8 GB RAM, **add a
4 GB swap file** to give the kernel headroom instead of OOM-killing:
```bash
sudo fallocate -l 4G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
```

The code also sets `oom_score_adj=-500` so the kernel prefers to kill
other processes first, and limits concurrent tool execution (4 general,
2 deploys, down to 1 when memory pressure is high).
