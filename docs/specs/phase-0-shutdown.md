# Phase 0 — Foundations: shutdown & persistence

**Version:** 0.0.7  
**Date:** 2026-07-02  
**Status:** in-progress  
**Decisions locked:** A (shield save + skip index), fsync+dir-fsync, fixes-first → split-last

## Bug: reports lost on shutdown

### Description
When the user closes cognits (Ctrl+C, Ctrl+Q, menu Close) while a subagent
(`deploy_subagent` via web_researcher, documentalista, skill_planner, etc.)
is writing its results, the report can become an **orphan**: saved to SQLite
but never announced to the frontend, never referenced in the assistant
message, and (if cancelled at the wrong instant) missing from the RAG index.

### Root cause trace (file:line)

1. `tool_deploy.py:270-297` — the save→index→emit block has **no `try/finally`**
   and **no `except asyncio.CancelledError`** around the SQLite save at `:272`.
   - AWAIT#2 `await asyncio.to_thread(self.report_store.save, report)` (:272):
     `except Exception as e` (:273) does **not** catch `asyncio.CancelledError`
     (it is a `BaseException` since Python 3.8). A cancel here skips the RAG
     index (:282) and the `subagent_end` emit (:291-297).
   - AWAIT#3 `await self.rag_engine.index(chunks)` (:282):
     `except asyncio.CancelledError: raise` (:286-287) re-raises, skipping
     the `subagent_end` emit (:291-297).

2. `routes_chat.py:580-588` — `sa.live_reports` is populated **only** by the
   `subagent_end` event handler. If `subagent_end` is never emitted,
   `sa.live_reports` never gets the entry.

3. `routes_chat.py:839-876` — the orchestrator's sync `finally` persists the
   assistant `MessageRow` with `reports=json.dumps(sa.live_reports)` (:849).
   Since `sa.live_reports` was never populated, the message row does **not**
   reference the orphaned report.

4. No `PRAGMA wal_checkpoint` anywhere in the codebase (confirmed by grep).
   `ReportStore.close()` (:672-674) just closes the connection. Nothing calls
   `close()` on shutdown. With `synchronous=NORMAL`, recent transactions may
   be only in the WAL file if the process exits without a checkpoint.

5. `storage/files.py:324-326` (`save_session`) and `:374-375` (`reorder_sessions`)
   use plain `Path.write_text()`. A crash mid-write can leave a truncated or
   empty JSON file. `write_file_atomic` (:24-33) exists for config/profile but
   lacks `fsync`, so it provides atomicity (no truncation) without OS-level
   durability.

6. `server/app.py:100` — `drain_agents(timeout=5)` applies the same 5-second
   budget to all agent tasks. Subagent runs (web_researcher with multiple
   search+fetch rounds) routinely take minutes. However, the primary failure
   is that the persist code is not shielded; the timeout is not the root cause.

7. `main.py:437-446` — `rag.shutdown()` and `docling_engine.shutdown()` are
   called twice in `_shutdown` (pre-super at :422-431 + post-super at :437-446),
   plus once in the lifespan shutdown (:101-104), plus once in `atexit` (:665-671).
   Only one belt-suspenders pair per site is needed.

### Why the orchestrator's finally (routes_chat.py:839) doesn't prevent the orphan
The finally persists `sa.live_reports`, but `sa.live_reports` is populated
**only** by the `subagent_end` event handler (routes_chat.py:580-588).
If `deploy_subagent` was cancelled before emitting `subagent_end`, the list
is empty → the persisted message has no report reference → orphan.

## Design decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Cancel-fix strategy | **A: shield save + skip index** | Shield only the fast SQLite save (ms) + emit `subagent_end`. Skip RAG index on cancel (logged). The report is still saved in SQLite + FTS5 (full-text searchable). Only the vector index is deferred. 5s drain timeout remains sufficient. VS B (deferred reindex adds a column + startup loop, unnecessary given FTS5 coverage). VS C (long drain for slow index risks hung shutdown). |
| Atomic write durability | **fsync + dir fsync** | Current `write_file_atomic` is rename-only. Adding `fsync` on the temp file + directory `fsync` ensures OS-level durability on power loss. Writes are infrequent (session save on create/rename/reorder, config on save). Overhead negligible. WSL2 correct. |
| Sequence | **Fixes first, split last** | T2-T6 land on the current codebase so bug fixes ship with minimal collateral change. T7 (main.py split) moves already-correct code. |

## Task breakdown

### T2 — Atomic writes with fsync
**Files:** `src/cognits/storage/files.py`

- Upgrade `write_file_atomic(path: Path, data: bytes)` (:24-33):
  1. Write to `path.with_name(path.name + ".tmp")` in the same directory.
  2. `f.flush()` + `os.fsync(f.fileno())` on the temp file.
  3. `os.replace(tmp, path)` (atomic rename, same filesystem only — satisfied since temp is in same dir).
  4. Directory fsync: `dir_fd = os.open(str(path.parent), os.O_RDONLY)`, `os.fsync(dir_fd)`, `os.close(dir_fd)`.
  5. On any `BaseException` during steps 1-3: `tmp.unlink(missing_ok=True)` then `raise`.
- Migrate `save_session` (:324-326) from `write_text(data, ...)` to `write_file_atomic(path, data.encode("utf-8"))`.
- Migrate `reorder_sessions` (:374-375) from `write_text(data, ...)` to `write_file_atomic(path, data.encode("utf-8"))`.
- `save_config` (:451-460) and `save_profile` (:283-286) already use `write_file_atomic` — no change needed (they get fsync for free).
- `routes_misc.py:175` (desktops) already uses `write_file_atomic` — no change needed.

**Tests:** `tests/test_files.py` (new): temp file created in same dir, fsync called, rename atomic, temp cleaned on exception, dir fsync called.

### T3 — Shield the subagent persist
**Files:** `src/cognits/agent/tool_deploy.py`

Restructure the save+index+emit block (:270-297) with explicit cancellation tracking:

```python
saved = False
emitted = False

async def _emit_end():
    nonlocal emitted
    if not emitted and self.emit is not None:
        emitted = True
        self.emit({"type": "subagent_end", "data": {...}})

try:
    if self.report_store is not None:
        await asyncio.to_thread(self.report_store.save, report)
        saved = True

    if self.rag_engine is not None and content:
        chunks = split_markdown(content, report_id, title)
        if chunks:
            n = await self.rag_engine.index(chunks)
            ...

    await _emit_end()

except asyncio.CancelledError:
    # Shield the fast SQLite save (ms) so the report exists in DB + FTS5.
    if not saved and self.report_store is not None:
        await asyncio.shield(
            asyncio.to_thread(self.report_store.save, report)
        )
        saved = True
    # Emit subagent_end so the orchestrator's finally references the report.
    await _emit_end()
    # RAG index is skipped on cancel (slow; FTS5 coverage is sufficient).
    if not saved:  # index was never attempted
        log.warning("deploy: RAG index skipped for report %s (cancelled)", report_id)
    raise  # Always re-raise CancelledError

except Exception as e:
    log.error("deploy: save report %s: %s", report_id, e)
    # ... (existing logic)

# If we got here without cancel or exception: normal path, already saved+emitted.
```

Key semantics:
- `asyncio.shield()` protects the inner `to_thread(save)` from task-level
  cancellation. The thread-side SQLite write runs to completion even though
  the outer task was cancelled.
- `CancelledError` is **always re-raised** — never swallowed.
- `_emit_end()` is idempotent (the `emitted` flag prevents double-emit).
- The RAG vector index is intentionally skipped under cancel; the report
  remains full-text searchable via FTS5.

**Tests:** `tests/test_deploy_cancel.py` (new):
- `test_cancel_during_save` — cancel at `asyncio.to_thread(save)` → report saved to DB, `subagent_end` emitted, `CancelledError` re-raised, RAG index skipped.
- `test_cancel_during_index` — cancel at `rag_engine.index` → report already saved, `subagent_end` emitted, `CancelledError` re-raised.
- `test_normal_path` — save + index + emit all complete; no cancellation.
- Uses `ScriptedLLM` or a mock subagent to control the await points.

### T5 — WAL checkpoint on shutdown
**Files:** `src/cognits/storage/db.py`, `src/cognits/server/app.py`, `src/cognits/main.py`

- Add `ReportStore.shutdown()`:
  ```python
  _closed: bool = False

  def shutdown(self) -> None:
      if self._closed:
          return
      with self._lock:
          self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
          self._conn.close()
          self._closed = True
  ```
  - `wal_checkpoint(TRUNCATE)` does a full checkpoint: copies WAL pages to
    the main DB file, fsyncs the DB, then truncates the WAL file to zero.
  - Idempotent via `_closed` flag (safe to call multiple times from
    different shutdown paths).
- Call from lifespan shutdown (`app.py:100-104`):
  ```python
  await state.drain_agents(timeout=...)
  if state.report_store is not None:
      await asyncio.to_thread(state.report_store.shutdown)
  if state.rag is not None:
      state.rag.shutdown()
  if state.docling_engine is not None:
      state.docling_engine.shutdown()
  ```
  Order: drain → checkpoint → RAG shutdown → docling shutdown.
- Call from `main.py:_shutdown` as belt-suspenders (idempotent, no-op if
  lifespan already called it).
- Remove the duplicate `rag.shutdown()`/`docling_engine.shutdown()` block
  at `main.py:437-446` (post-super pair). Keep the pre-super pair (:422-431)
  as belt-suspenders for the thread-join-timeout case.

**Tests:** `tests/test_db.py` additions:
- `test_shutdown_checkpoint` — `shutdown()` calls `wal_checkpoint(TRUNCATE)`, closes connection.
- `test_shutdown_idempotent` — calling `shutdown()` twice does not raise.

### T6 — Drain cleanup
**Files:** `src/cognits/server/app.py`, `src/cognits/main.py`

- Make drain timeout configurable via env var `COGNITS_DRAIN_TIMEOUT`
  (default `5.0`). Read in `drain_agents` or pass from caller.
  ```python
  _DRAIN_TIMEOUT = float(os.environ.get("COGNITS_DRAIN_TIMEOUT", "5.0"))
  ```
- Use `asyncio.gather(*waits, return_exceptions=True)` with
  `asyncio.wait_for` for cleaner error semantics (vs `asyncio.wait` +
  manual pending-cancel loop). Both are equivalent; use whichever is
  simpler given the current code structure.
  - Current code uses `asyncio.wait([tasks], timeout=timeout)` then
    cancels pending. This is already correct in behavior. The change
    is mainly making `timeout` configurable.
- Remove the duplicate `rag.shutdown()`/`docling_engine.shutdown()` pair
  at `main.py:437-446`.

**Tests:** `tests/test_app.py` (new):
- `test_drain_custom_timeout` — timeout from env var respected.
- `test_drain_removes_duplicates` — `main._shutdown` no longer has duplicate engine shutdown calls (structural check).

### T7 — Split main.py
**Files:** `src/cognits/main.py` → `src/cognits/tui.py`, `src/cognits/cli.py`, `src/cognits/shutdown.py`, `src/cognits/bootstrap.py`, `src/cognits/__main__.py`

Extract four modules from `main.py` (743 lines):

| Module | Content | Lines | Dependencies |
|--------|---------|-------|-------------|
| `bootstrap.py` | `_Server(uvicorn.Server)` with no-op signal install + `_setup_file_logging`, `_log_exception`, `_log_handler` + `_cleanup_legacy_sidecar`, `_port_available`, `_kill_port` | 37-70, 173-175, 685-739 | `uvicorn`, `logging`, `sys`, `shutil`, `socket`, `subprocess`, `paths` |
| `shutdown.py` | `shutdown_app(state, server, server_thread, drain_timeout)` — coordinates drain → WAL checkpoint → RAG/docling shutdown → thread join. Called from `tui._shutdown` and as a belt-suspenders. Replaces the scattered/duplicated shutdown calls across `main.py`, `app.py`, and atexit. | NEW (extracted from main.py:408-446 + app.py drain logic) | `AppState`, `asyncio`, `threading`, `atexit` |
| `tui.py` | `SPINNER`, `COGNITS_THEME`, `CSS`, `CognitsTUI` class (app logic) | 72-446 | `textual`, `asyncio`, `signal`, `threading`, `open_browser`, `AppState`, `_Server`, `__version__`, `shutdown_app`, `agent.agent` (lazy) |
| `cli.py` | `main()` entry + `_interactive_uninstall`/`_print_uninstall_hint` + `if __name__ == "__main__"` | 449-524, 531-682, 742-743 | `argparse`, `os`, `sys`, `atexit`, `uvicorn`, `onnxruntime` (lazy), `paths`, `AppState`, `create_app`, `CognitsTUI`, `bootstrap.*`, `shutdown_app` |
| `__main__.py` | `from cognits.cli import main; main()` | 3 | `cli` |

**Shared state wiring:**
- `AppState` is constructed in `cli.py:main()` and passed to `CognitsTUI(state, server, port)`.
- `_Server` is created in `cli.py:main()` using `uvicorn.Config` and passed to `CognitsTUI`.
- `shutdown_app(state, server, server_thread, timeout)` accepts all the context it needs. It also registers the `atexit` handler (moved from `main.py:665-671`).
- The `_check_rag` spinner and `_watch_memory` live in `tui.py` (they are TUI methods). Their lazily-imported dependencies (`cognits.agent.agent`, `gc`, `resource`) are preserved lazy to avoid import cycles.
- `_kill_port` + `_port_available` are used by `cli.py:main()` for the `--fresh`/`--force-port` flags — they belong in `bootstrap.py`.

**Import order to avoid cycles:**
```
bootstrap (no cognits deps)
  ← shutdown (depends on bootstrap._log_exception)
    ← tui (depends on shutdown.shutdown_app, bootstrap._Server)
      ← cli (depends on tui, bootstrap, shutdown, app)
```

`cognits.agent.agent` is imported lazily inside `_watch_memory` (already the
case at `main.py:361`) to break the `tui → agent → routes_chat → session_agent → app → rag` import tangle.

**Tests:** `tests/test_main_split.py` (new):
- `test_import_graph_no_cycle` — `python -c "import cognits.{tui,cli,shutdown,bootstrap}"` succeeds.
- `test_smoke_app_starts` — `uv run cognits --version` returns version string.

## Test plan (summary)

| Test file | New? | Covers |
|-----------|------|--------|
| `tests/test_files.py` | NEW | T2: atomic write fsync, temp cleanup, crash resilience |
| `tests/test_deploy_cancel.py` | NEW | T3: cancel@save → saved+emitted; cancel@index → emitted; normal path |
| `tests/test_db.py` (additions) | EXISTING | T5: shutdown checkpoint + idempotent |
| `tests/test_app.py` | NEW | T6: drain custom timeout, duplicate removal |
| `tests/test_main_split.py` | NEW | T7: import graph, smoke start |

## Risk notes

1. **`asyncio.shield` and loop shutdown:** `shield` protects from task-level
   cancellation, not loop shutdown. If `uvicorn` calls `force_exit` before
   the shielded save completes, the write is lost. However: (a) the shielded
   save is a few ms (SQLite INSERT), (b) drain waits on `done_event` with a
   5s budget before uvicorn tears down the loop, (c) the orchestrator's
   `finally` calls `sa.close()` which sets `done_event` → drain unblocks.
   Mitigation: if this proves unreliable in practice, fall back to a
   `try/finally` with a direct sync `report_store.save()` call (no `to_thread`,
   no await) in the finally block — the current orchestrator finally at
   `routes_chat.py:839-876` already uses this pattern for `append_message`.

2. **`wal_checkpoint(TRUNCATE)` on Windows/WSL:** Tested on WSL2 (real Linux
   kernel). The checkpoint blocks until all readers finish, but with a
   single-connection architecture this is immediate. Works correctly.

3. **dir-fsync on WSL1:** WSL1 had fsync issues mapping to NTFS. The environment
   is WSL2 (Linux kernel) — verified in `<env>` as `Platform: linux` with
   `/mnt/c/...` paths. Should work. If WSL1 support is needed, gate dir-fsync
   behind a platform check.

4. **main.py split — TUI regression:** The `CognitsTUI` class touches Textual
   widgets, signal handling, and the server thread. The split preserves all
   existing behavior; the risk is in moving signal handlers (Textual's
   `on_mount` sets them, `_shutdown` cleans up). These stay in `tui.py`.

5. **No schema change:** SCHEMA_VERSION stays at 1. None of T2-T7 modify the
   database schema. The deferred reindex (option B) was explicitly dropped,
   avoiding a new `indexed` column.

6. **`subagent_end` double-emit:** The `emitted` flag prevents double-emit if
   both the normal path and the cancel handler try to emit. The flag is scoped
   to a single `execute()` call.
