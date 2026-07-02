# Phase 2 — HTTP/SSE server layer: ChatService, error handling, test coverage

**Version:** 0.0.7  
**Date:** 2026-07-02  
**Status:** in-progress  
**Decisions locked:** ChatService extraction, CognitsError hierarchy, full HTTP test coverage

## Current state

The server layer (`src/cognits/server/`) is 2516 lines across 15 files. Only
4 of 15 modules have real HTTP tests. Multiple hardcoded values, inconsistent
error response shapes, and a 410-line `_run_agent` function with 7 mixed
responsibilities in `routes_chat.py`.

## Design

### ChatService extraction

`routes_chat.py` (876 lines) → split into:
- `routes_chat.py` (~250 lines): HTTP dispatch only — parse request, call ChatService, return responses
- `server/chat_service.py`: `ChatService` class with:
  - `run_agent()` — the orchestrator lifecycle
  - `_build_subagent_map()` — 7 subagents with config cascade
  - `_build_tool_registry()` — tool registration
  - `_make_process_event()` — SSE event bridging
  - `_persist_partial()` — the sync finally block

`ChatService` takes `state: AppState` and `session_id: str` at construction.
Its `run_agent()` method is the extracted body of the current `_run_agent`.

```python
# server/chat_service.py
class ChatService:
    def __init__(self, state: AppState, session_id: str, llm_client, tf_client, cfg):
        self.state = state
        self.sid = session_id
        ...

    async def run_agent(self, incoming_messages, process_event, sa):
        # fire-and-forget session_namer
        # persist history
        # build subagent_map + registry
        # construct Agent
        # await agent.run(...)
        # finally: persist partial, deregister, close clients
```

### Error handling unification

New `server/exceptions.py`:
```python
class CognitsError(Exception):
    def __init__(self, message, code, http_status=500, details=None):
        self.message = message
        self.code = code
        self.http_status = http_status
        self.details = details or {}

class SessionNotFound(CognitsError): ...
class AgentBusy(CognitsError): ...
class ConfigError(CognitsError): ...
class NotFoundError(CognitsError): ...
class StorageError(CognitsError): ...
```

Registered in `app.py` via `@app.exception_handler(CognitsError)` that returns
`JSONResponse({"error": code, "message": message, "details": details})`.

All routes replace `text_error(msg, status)` with `raise CognitsError(...)`.
`util.py:text_error` is removed after migration.

### Test coverage

New test files for the 6 currently untested route modules:
- `tests/test_routes_reports.py`
- `tests/test_routes_sessions.py`
- `tests/test_routes_misc.py`
- `tests/test_routes_config.py`
- `tests/test_routes_notes.py`
- `tests/test_routes_files.py`

All use `real_state` fixture (AppState with real repos, no LegacyStore).

## Task breakdown

### T3 — Spec (this file)

### T4 — Extract ChatService
- Create `server/chat_service.py` with `ChatService` class
- Move `_run_agent` body, `_build_subagent_map`, `_build_tool_registry`, `_make_process_event`, `_persist_partial`
- `routes_chat.py` imports `ChatService` and delegates
- Keep prompt helper functions (`_build_*`) in routes_chat.py (they're HTTP-layer context assembly)
- Tests: existing tests pass; add ChatService unit test

### T5 — Unify error handling
- Create `server/exceptions.py` with CognitsError hierarchy
- Register exception handlers in `app.py`
- Replace `text_error(...)` in all routes with `raise CognitsError(...)`
- Remove `text_error` from `util.py` (keep `mask_key` and `atoi`)
- Tests: all existing tests pass; add error shape tests

### T6 — Centralize remaining hardcoded values
- Add to `constants.py`: `DEFAULT_PORT`, `VITE_PORT`, `TREE_SKIP_DIRS`, `MAX_TOKENS_LIMIT`, `MAX_TEXT_BYTES`, `MAX_NAME_LENGTH` (120), `MAX_SESSION_NAME_LENGTH` (80)
- Update all sites to import from constants

### T7 — De-homogenizations
- `INSERT OR REPLACE` → `ON CONFLICT DO UPDATE` in pedagogical.py, session_config.py
- `/api/agents` serves `AGENT_LABELS` from constants (not `DEFAULT_AGENTS` from agent.prompts)
- Remove duplicate/unused imports: routes_chat.py L20+33, L37; routes_stream.py L41
- Add `Depends(get_app_state)` wrapper in `server/dependencies.py`
- Update AGENTS.md session ID format (add seconds)

### T8 — Full HTTP test coverage
- Create 6 new test files using `real_state` fixture
- Each test: at least one smoke test per endpoint
- SSE stream test using `client.stream()` + `aiter_lines()`

### T9 — Update AGENTS.md
- Session ID format: `%Y-%m-%dT%H-%M-%S`
- Error shape: `{"error": "...", "message": "...", "details": {...}}`
- ChatService, exceptions.py, dependencies.py documentation
- `/api/agents` serves AGENT_LABELS

## Test plan

| Test file | New/Update | Covers |
|-----------|------------|--------|
| `tests/test_chat_service.py` | NEW | ChatService run_agent, subagent_map, registry |
| `tests/test_exceptions.py` | NEW | CognitsError shape, handler registration |
| `tests/test_routes_reports.py` | NEW | CRUD + FTS5/LIKE search |
| `tests/test_routes_sessions.py` | NEW | Session CRUD, reorder, delete cascade |
| `tests/test_routes_misc.py` | NEW | health, tree, agents, messages, config, desktops |
| `tests/test_routes_config.py` | NEW | Config CRUD, masking, test-key |
| `tests/test_routes_notes.py` | NEW | Notes CRUD, reorder |
| `tests/test_routes_files.py` | NEW | Files content + raw |

## Risk notes

1. **T4 is highest-risk** — moving 410 lines between files. Mitigation: extract
   one responsibility at a time, run tests after each, keep old code as reference.
2. **T5 touches all routes** — mechanical (`text_error(msg, 404)` → `raise NotFoundError(msg)`)
   but extensive. Mitigation: one route module at a time.
3. **ChatService is coupled to SSE internals** (SessionAgent, process_event).
   Keep same method signatures; don't redesign the event flow.
