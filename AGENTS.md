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
   documentation, web search, or technology evaluation, invoke `@SOTAbriefing`
   via the task tool. Do NOT answer research questions from training data.

2. **SKILLS**: At the start of each context, load project skills:
   `solidjs-patterns`, `tailwind-v4` using the `skill()` tool.
   Additional specialized skills are available — load when a task matches:
   - `sqlite-fts5` — FTS5 full-text search, triggers, BM25, schema migration
   - `sse-streaming` — Server-Sent Events (backend + SolidJS frontend)
   - `deepseek-api` — DeepSeek streaming API, reasoning mode, prompt cache
   - `multi-agent-tools` — Tool registry, subagent spawning, event relay

3. **SKILL WORK**: When asked to create, modify, or research skills, invoke
   `@skill-writer` via the task tool.

4. **CODE EXPLORATION**: For codebase structure or pattern search, invoke
   `@explore` via the task tool.

5. **WORKFLOW**: Write specs first. One atomic task per message. After each
   change: `uv run pytest -q`. Commit after each logical unit.

6. **NO MICRO-DECISIONS**: When any implementation detail is ambiguous or not
   explicitly specified by the user, the model MUST ask the user before
   proceeding. This applies both during planning and building phases. Do NOT
   assume defaults, conventions, or "reasonable" choices — present the options
   and let the user decide.

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
- DB: SQLite stdlib (`sqlite3`, FTS5, WAL, single locked connection)
- RAG: in-process ChromaDB 1.5.9 + fastembed 0.8.0 (BGE-M3 ONNX) in a
  1-thread executor (the old Python sidecar + venv is gone)
- Packaging: uv + hatchling, wheel `py3-none-any` with the frontend dist as
  package data; `uv tool install cognits`

## Build & Run
```bash
scripts/dev.sh          # Vite HMR (5174) + uvicorn --reload (5173, ENV=dev)
scripts/build.sh        # typecheck + vite build → src/cognits/frontend_dist → uv build
uv run pytest -q        # tests (crypto, db/FTS5, chunker, agent loop, SSE framing)
uv run cognits          # run from source (serves embedded frontend_dist)
uv publish              # publish to PyPI (when ready)
```
Env vars: `PORT` (default 5173), `COGNITS_HOST`/`LEARNIT_HOST` (default
127.0.0.1), `ENV=dev` (proxy to Vite), `COGNITS_DISABLE_RAG=1` (skip model
load — useful in dev/tests; first RAG start downloads ~2.3 GB BGE-M3).

## Project Structure

### Backend (`src/cognits/`)

| File | Purpose | Go reference (legacy/) |
|------|---------|------------------------|
| `main.py` | Entry point: uvicorn programmatic, signal handling (1st Ctrl+C drains agents ≤5s, 2nd hard-kills), browser open | `cmd/learnit/main.go` |
| `paths.py` | Data dir `cwd/.cognits` (uses `.learnit` in place if present), DB filename resolution, Go-compatible `user_config_dir()` (Windows: Roaming) | — |
| `server/app.py` | `AppState` (store, report_store, cached_config, active_agents), app factory, RAG lifespan, `drain_agents` | `internal/server/server.go` |
| `server/session_agent.py` | `SessionAgent`: pub/sub with atomic snapshot+subscribe. ALL methods sync, event-loop only (see invariant in module docstring) | `server.go:22-95` |
| `server/routes_chat.py` | POST /api/chat (409/401/202), config cascade, `build_chat_messages` (Spanish date stamp ONLY on last user msg — prefix cache), `_run_agent` task with 100%-sync finally (persists partials) | `internal/server/chat.go` |
| `server/routes_stream.py` | SSE wire format: history first, tokens unnamed (OpenAI delta), keepalive 15s, drain + `done` (`null` live / `{}` snapshot) | `internal/server/session_stream.go` |
| `server/routes_sessions.py` | Session CRUD (id `%Y-%m-%dT%H-%M`, JSON files) | `internal/server/sessions.go` |
| `server/routes_config.py` | Global config GET/PUT, key masking `••••`+4, mask-preserve on PUT, provider/model/reasoning whitelists | `internal/server/config.go` |
| `server/routes_reports.py` | Reports CRUD + LIKE search + FTS5 (BM25 10/3/1, `<mark>` highlight) | `internal/server/reports.go` |
| `server/routes_misc.py` | health, tree (depth 6, budget 2000), agents, messages, session_config, desktops | `api.go`, `agents.go`, `messages.go`, `session_config.go`, `desktops.go` |
| `server/frontend.py` | Serves `frontend_dist` package data; index no-store + cache-buster regex | `internal/server/frontend.go` |
| `server/devproxy.py` | ENV=dev: HTTP+WebSocket passthrough to Vite (replaces rebuild.go/air) | `frontend.go:22-27` |
| `server/browser.py` | Browser opener (WSL-aware) | `internal/server/browser.go` |
| `agent/agent.py` | Agentic loop: stream → sparse-index tool call accumulation → execute → repeat; tool errors fed back as `{"error": ...}` | `internal/agent/agent.go` |
| `agent/prompts.py` | Agent personas (orquestador, Socratic) | `internal/agent/prompts.go` |
| `agent/subagents.py` | web_researcher + documentalista configs, TinyFish tools, emit wrapping | `internal/agent/subagents/` |
| `agent/tool_deploy.py` | `deploy_subagent`: run subagent → save report → index chunks in RAG → `subagent_end`. Cancel ⇒ no report; failure ⇒ error tool result + clears banner | `internal/agent/tools/deploy.go` |
| `agent/tool_rag.py` | `rag_search` tool | `internal/agent/tools/rag_search.go` |
| `llm/types.py` | `Message`/`ToolCall` with omitempty payload semantics | `internal/llm/llm.go` |
| `llm/deepseek.py` | httpx streaming; idle watchdog = `read=120` timeout; thinking omitted when tools present | `internal/llm/deepseek.go` |
| `tools.py` | Tool registry, name-sorted `definitions()` (prefix cache) | `internal/tools/tools.go` |
| `tinyfish.py` | TinyFish search/fetch (X-API-Key, 150s) | `internal/tinyfish/client.go` |
| `rag/engine.py` | In-process ChromaDB + fastembed BGE-M3 (custom model registration identical to the old sidecar; reuses its model cache and `chroma_db`). 1-thread executor; background init; `ready`/`error` gating | `internal/rag/` + `sidecar.py` |
| `rag/chunker.py` | Markdown chunker 1600/160 chars, fences atomic; IDs `{report_id}_c{idx}` byte-identical to Go (no re-index dupes) | `internal/rag/chunker.go` |
| `storage/files.py` | Sessions JSON, config with AES-GCM (bit-compatible with Go; key reused from `~/.config/learnit/`, copied to `~/.config/cognits/`) | `internal/storage/storage.go` |
| `storage/db.py` | SQLite: schema + FTS5 external content + triggers, `user_version` migration, `build_fts5_query`, messages CRUD | `internal/storage/db.go` |

### Frontend (`frontend/src/`) — unchanged
See git-less history in `legacy/` docs; key files: `lib/chat-stream.ts` (SSE
client), `stores/*.ts` (signals + API calls), `components/*.tsx`. All API
calls are same-origin relative `/api/*`.

## Architecture invariants (do not break)

### Concurrency model (asyncio replaces goroutines)
- **Everything shared lives on the event loop.** `SessionAgent.publish()` and
  `subscribe_with_snapshot()` are synchronous → atomic in asyncio. An event is
  either in the snapshot or in the queue, never both (the token-duplication
  race). Never call them from threads (use `loop.call_soon_threadsafe`).
- Blocking I/O (sqlite3, chromadb, fastembed) goes through `asyncio.to_thread`
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
- `: keepalive` comment every 15s. Queue (1024) drops on overflow — DB reload
  on `done` is the safety net.
- Two `done` variants: `data: null` (live route) and `data: {}` (snapshot route).

### Storage
- `INSERT ... ON CONFLICT DO UPDATE`, never `INSERT OR REPLACE`, on tables
  with FTS5 external-content indexes (REPLACE deletes without firing triggers).
- API keys encrypted AES-GCM (`base64(nonce12 ‖ ct ‖ tag16)`), key at
  `user_config_dir()/cognits/encryption.key`; API masks keys (`••••`+4) and
  PUT preserves them when the mask is echoed back.
- Data dir: `cwd/.cognits` (a pre-existing `cwd/.learnit` is used in place).
  DB file: `cognits.db` (or pre-existing `learnit.db`).

### LLM / prompt cache
- Tool definitions sorted by name; date stamp only on the last user message;
  history persisted unstamped. Breaking either invalidates DeepSeek's prefix cache.
- Thinking param omitted when tools are present (API rejects the combination).

## Design Patterns (frontend — unchanged)
- Store-driven reactivity via `createMemo` (never destructure store props).
- Unified global context-menu signal (discriminated union).
- `structuredClone(unwrap(store))` to clone SolidJS stores.
- Token batching in chat-store (50ms flush).
- Don't dump docs into LLM context — use curated reports (context rot).
