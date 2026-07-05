# Phase 8 — Frontend: API wrapper, SSE types, learner model UI, Vitest

**Version:** 0.0.7
**Date:** 2026-07-05
**Status:** shipped (retrospective)
**Decisions locked:** `apiFetch()` centralized wrapper for all API calls (error normalization), `sse-types.ts` as TypeScript contract mirroring backend SSE wire format, Vitest 4 + happy-dom + `@solidjs/testing-library`, 3 new components for learner model visualization

## Context

The frontend up to Phase 3 used raw `fetch()` calls scattered across stores
and components, with no centralized error handling. SSE event types were
documented only in the backend (AGENTS.md), with no TypeScript mirror.
The learner model (Phases 4–7) had no frontend visualisation — users could
not see their skill tree, mastery levels, or study plan.

Phase 8 addressed three gaps:

1. **API consistency:** a centralized `apiFetch()` wrapper for all backend
   calls, and `sse-types.ts` defining TypeScript interfaces for the 13 SSE
   event types.
2. **Learner model UI:** three new components showing the skill tree with
   mastery badges, a mastery dashboard overview, and the active study plan.
3. **Frontend testing infrastructure:** Vitest 4 + happy-dom setup with tests
   for markdown rendering, SSE frame parsing, and store helpers.

## What changed

### API wrapper

**File:** `frontend/src/lib/api.ts` (new, 43 lines)

```typescript
export async function apiFetch<T = any>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const res = await fetch(path, {
    ...init,
    headers: { "Content-Type": "application/json", ...init.headers },
  });
  if (res.status === 204) return undefined as T;
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    const msg = body?.message || body?.error || `HTTP ${res.status}`;
    const err = new Error(msg) as Error & { status: number; body: any };
    err.status = res.status;
    err.body = body;
    throw err;
  }
  return body as T;
}
```

Key features:
- Sets `Content-Type: application/json` by default (overridable via init).
- Handles 204 No Content (returns `undefined`).
- Parses error responses into a typed `Error` with `status` and `body`.
- One-liner fire-and-forget variant: `apiPostFireAndForget()` for events
  that don't need a response.

All stores were migrated to use `apiFetch` instead of raw `fetch()`.

### SSE type definitions

**File:** `frontend/src/lib/sse-types.ts` (new, 125 lines)

TypeScript interfaces for the full SSE wire format, serving as a single
source of truth that mirrors `routes_stream.py`:

13 named events typed as a discriminated union:

| Event type | Interface | Backend trigger |
|-----------|-----------|----------------|
| `history` | `HistoryEvent` | Initial snapshot |
| `reasoning` | `string` | DeepSeek reasoning_content |
| `error` | `string` | Agent errors |
| `tool_start` | `ToolStartEvent` | Tool execution start |
| `tool_end` | `ToolEndEvent` | Tool execution end |
| `tool_progress` | `ToolProgressEvent` | Banner updates |
| `subagent_end` | `SubagentEndEvent` | Subagent report complete |
| `usage` | `UsageEvent` | Token usage snapshots |
| `session_renamed` | `SessionRenamedEvent` | Auto-naming complete |
| `ui_action` | `UiActionEvent` | Pedagogy stage transitions |
| `setup_complete` | `SetupCompleteEvent` | Setup wizard done |
| `create_learning_session` | `CreateLearningSessionEvent` | New learning session |
| `done` | `DoneEvent` | Stream end |

Plus a `TokenFrame` interface for unnamed token deltas (default event handler)
and a shared `MessageRow` type matching the backend's `MessageRow` dataclass.

The union type `SSEEvent` enables exhaustive type narrowing in consumers:

```typescript
export type SSEEvent =
  | { type: "history"; data: HistoryEvent }
  | { type: "done"; data: DoneEvent | null }
  | { type: "reasoning"; data: string }
  | ...
  | { type: "token"; data: string };
```

### Learner model UI (3 components + 2 stores)

**Files:** `frontend/src/stores/skills-store.ts` (new, 74 lines),
`frontend/src/stores/study-plan-store.ts` (new, 39 lines),
`frontend/src/components/SkillsTree.tsx` (new, 91 lines),
`frontend/src/components/MasteryDashboard.tsx` (new, 55 lines),
`frontend/src/components/StudyPlanView.tsx` (new, 30 lines)

**skills-store.ts** — fetches `/api/skills/tree` and `/api/skills/{id}/state`
via `apiFetch`:

- `tree` resource: `SkillNode[]` + `SkillEdge[]` from `GET /api/skills/tree`.
- `learnerState` resource: triggered by `selectedSkillId()` signal, fetches
  individual learner state. Refetchable via `refetchState()`.
- Helper functions: `getMasteryLabel(p)` maps p_mastery to text labels
  (mastered/proficient/developing/emerging/not_seen), `getStatusColor(p)`
  returns hex colors for the mastery badge.
- `selectedSkillId` signal shared across components.

**SkillsTree.tsx** — DAG view of the skill tree grouped by domain:

- Groups skills by `domain` field, sorted alphabetically.
- Each skill shows a mastery badge (colored dot via `getStatusColor`).
- Prerequisite edges rendered as a flat list per domain (the DAG layout
  was simplified; full interactive DAG was deferred).
- Clicking a skill sets `selectedSkillId`.

**MasteryDashboard.tsx** — overview of learner progress:

- Counts skills by mastery level (mastered, proficient, developing, emerging,
  not_seen).
- Lists all skills grouped with domain tags.
- Shows a placeholder message pointing users to the Skills Tree for
  per-skill detail.
- Uses `createMemo` for reactive counts (no prop destructuring).

**StudyPlanView.tsx** — displays the current study plan:

- Fetches `GET /api/plans/active` via `study-plan-store.ts`.
- Lists plan items in order with skill name and status.
- Minimal layout (list view); full interactive plan editing deferred.

**Tab registration:** Three new tab kinds registered in `tabs.ts` and
`tab-kinds.ts`: `"skills"`, `"mastery"`, `"plan"`.

### Frontend bug fixes (commit `f1c1090`)

- `reasoning: 'high'` → `'enabled'` in `types.ts`, `chat-sections.tsx`,
  `settings-store.ts` (aligns with `VALID_REASONING` in constants.py).
- AGENT_LABELS hardcoded removed from `chat-store.ts` (moved to
  `/api/agents` fetch — completed in T2 of the bring-forward spec).
- `scaffoldingLevel` field added to `models.py` `to_json()` (was missing
  from JSON serialization).
- 20 local constants in `model.py`/`planner.py` migrated to imports from
  `constants.py`.
- i18n leak: `'Ir abajo'` → `'Scroll to bottom'`.
- Naming: `learnit-frontend` → `cognits-frontend`, `Learn It` → `Cognits`
  in `index.html` and `package.json` metadata.

### Test infrastructure (commit `87b6232`)

**Files:** `frontend/vitest.config.ts` (new), `frontend/src/__tests__/` (3 files)

Vitest 4 configuration:

```typescript
export default defineConfig({
  plugins: [solid()],
  test: { environment: "happy-dom", globals: true },
  resolve: { conditions: ["development", "browser"] },
});
```

- `happy-dom` environment (lightweight DOM, no browser).
- `vite-plugin-solid` for JSX compilation.
- `globals: true` so `describe`/`it`/`expect` are available without imports.

Three test files (13 tests total):

- **`markdown.test.ts`** (3 tests) — `renderMarkdown` renders plain text,
  `sanitizeHighlight` allows `<mark>` tags, `highlightCode` handles JS.
- **`chat-stream.test.ts`** (4 tests) — SSE frame format validation: named
  events have `event:` prefix, token frames have no event line, keepalive
  starts with colon, DONE sentinel is the last frame.
- **`components.test.ts`** (2 tests) — skills-store helper functions
  (`getMasteryLabel`, `getStatusColor` return correct values).

Package scripts added to `frontend/package.json`:

```json
{
  "test": "vitest run",
  "test:watch": "vitest"
}
```

### AGENTS.md updates

Commit `4866421` updated the AGENTS.md frontend section: file counts revised
(54 files, 8077 lines, 12 stores, 25 components at the time), 4 undocumented
SSE events documented (session_renamed, ui_action, setup_complete,
create_learning_session), and `apiFetch`/`sse-types` added to the Design
Patterns section.

## Architecture invariants established

- **Centralized API error handling:** all stores use `apiFetch()`. Error
  responses from the backend (`{"error": ..., "message": ..., "details": ...}`)
  are surfaced as typed JavaScript Errors with `status` and `body`.
- **SSE types as contract:** `sse-types.ts` is the TypeScript mirror of
  `routes_stream.py`. Adding a new SSE event requires updating both files.
- **Store-driven reactivity:** all three new components use `createMemo`
  (never destructure store props), following the existing SolidJS pattern.
- **Skill tree data comes from backend:** `skills-store.ts` fetches
  `/api/skills/tree`. The tree structure (nodes + edges) is server-authoritative.
- **Mastery labels are frontend-derived:** `getMasteryLabel()` uses the same
  thresholds as `learner/model.py` (0.95, 0.80, 0.60). These could drift;
  a future improvement would serve labels from the backend.

## Deferred / out of scope

- **Interactive DAG layout:** `SkillsTree.tsx` shows a grouped list, not a
  true DAG with collapsible edges. Full graph visualization deferred.
- **Study plan interaction:** `StudyPlanView.tsx` is read-only. Editing,
  reordering, and manual goal-setting deferred.
- **Per-skill learner state auto-load:** selecting a skill loads its state,
  but there is no batch load of all states for the dashboard counts.
- **Chat UX enhancements (Phase 8 out of scope):** auto-scroll via
  `IntersectionObserver` was already implemented; pulse indicator and
  collapsible tool panels were deferred to the 0.0.7 bring-forward (T3).
- **Agent labels from `/api/agents`:** the initial Phase 8 commit kept
  hardcoded `AGENT_LABELS` in `chat-store.ts` (F1 fix). Loading from the
  backend was completed later in the bring-forward spec (T2).

## Commits

| SHA | Description |
|-----|-------------|
| `f1c1090` | P0 — Phase 8 bugs (reasoning 'high'→'enabled', cleanup, i18n, naming) |
| `5f487ea` | P1+P2 — apiFetch, sse-types.ts, skills-store, MasteryDashboard, SkillsTree, StudyPlanView |
| `87b6232` | P4+P5 — markdown tests, chat-stream tests, Vitest config (Phase 8 complete) |
| `4866421` | P6 — AGENTS.md frontend architecture + 4 undocumented SSE events |
