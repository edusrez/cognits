# Phase 5 — sqlite-vec infrastructure for RAG

**Version:** 0.0.7
**Date:** 2026-07-05
**Status:** shipped (retrospective)
**Decisions locked:** sqlite-vec 0.1.9 as dense vector store (shared rowid pattern with report_chunks), ChromaDB retained for active path (dual-wire), SCHEMA_VERSION stays at 1

## Context

RAG dense vector storage in Phase 0–3 relied entirely on ChromaDB 1.5.9
(PersistentClient + HNSW index). This introduced:

- A separate storage directory (`.cognits/rag/chroma_db/`)
- ~23 MB of additional dependencies (chromadb, hnswlib, sentence-transformers chain)
- A separate query path that could diverge from the SQLite data
- Silent HNSW corruption bugs in ChromaDB 1.5.x (later confirmed by SOTA research)

Phase 5 added sqlite-vec 0.1.9, an extension that brings vector storage directly
into the SQLite database. The vec0 virtual table stores embeddings as a column
in the same `.cognits/cognits.db` file. ChromaDB was kept as the active dense
store — this phase was purely infrastructure, with the cutover deferred.

## What changed

### Dependency

**File:** `pyproject.toml`

```toml
dependencies = [
    ...
    "sqlite-vec==0.1.9",
]
```

sqlite-vec v0.1.x is a pre-stable extension. It provides:
- `vec0` virtual tables with configurable distance metric (cosine, L2, IP)
- Brute-force KNN search (no ANN/IVF — acceptable at ≤10 K vectors)
- Native `.load()` via the `sqlite_vec` Python package

### Database schema

**File:** `src/cognits/storage/database.py`

Two new tables in `BASE_SCHEMA`:

```sql
CREATE TABLE IF NOT EXISTS report_chunks (
    id TEXT PRIMARY KEY,
    report_id TEXT NOT NULL,
    text TEXT NOT NULL,
    source_type TEXT NOT NULL DEFAULT 'web',
    topic TEXT NOT NULL DEFAULT '',
    chunk_index INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_chunks_report ON report_chunks(report_id);

CREATE VIRTUAL TABLE IF NOT EXISTS chunks_vec USING vec0(
    embedding float[1024]
);
```

Key design decisions:
- **Shared rowid pattern:** `chunks_vec` has no explicit rowid column. Its
  implicit `rowid` matches the `rowid` of `report_chunks` (via
  `_chunk_id_to_int()`). This enables a JOIN:
  ```sql
  SELECT rc.id, rc.report_id, rc.text, vec_distance_L2(cv.embedding, ?) as dist
  FROM chunks_vec cv
  JOIN report_chunks rc ON rc.rowid = cv.rowid
  ORDER BY dist LIMIT ?
  ```
- **1024 dimensions** matching BGE-M3 output.
- **Cosine distance** via `vec_distance_L2` — since BGE-M3 embeddings are
  L2-normalized, L2 distance is equivalent to cosine distance.

### Extension loading

`Database.__init__()` loads the sqlite-vec extension at connection setup:

```python
self.conn.enable_load_extension(True)
import sqlite_vec
sqlite_vec.load(self.conn)
self.conn.enable_load_extension(False)
```

This is called after pragma setup but before migration, so the `vec0` table
creation runs with the extension available.

### Vector operations

Three new methods on `Database`:

- `vector_index(chunks: list[dict]) -> int` — inserts chunk metadata into
  `report_chunks` and embeddings into `chunks_vec` via shared rowid. Uses
  `INSERT OR REPLACE` for idempotent re-indexing. The chunk dict includes an
  `"embedding"` key serialized as a JSON float array.
- `vector_search(query_embedding, max_results=10) -> list[dict]` — KNN search
  via `vec_distance_L2`, joined with `report_chunks` for metadata. Returns
  id, report_id, text, source_type, topic, chunk_index, distance.
- `vector_count() -> int` — returns total indexed vectors.

Helper functions:
- `_chunk_id_to_int(chunk_id: str) -> int` — maps chunk IDs (e.g.,
  `"report_abc_c0"`) to a deterministic 62-bit integer via `abs(hash()) % 2**62`.
  Note: Python's `hash()` is randomized per process, so rowids are unstable
  across runs. This was flagged as a latent bug (fixed in the 0.0.7 bring-forward
  T5a by replacing with `hashlib.sha1`-based folding).
- `_embed_to_json(floats) -> str` — serializes a list of floats to a compact
  JSON array string for vec0 storage.

### Bug fixes (commit `fb652fc`)

This commit also fixed Phase 5 collateral bugs:
- `fFAVICON_URL_TEMPLATE` → `FAVICON_URL_TEMPLATE` (NameError in subagents.py)
- Dead circuit breaker state removed from `deepseek.py`
- Duplicate `DEFAULT_FLASH_MODEL`/`RESEARCHER_MAX_STEPS` imports removed
- `token_counter.py` docstring: `chars//4` → `chars/3.5`

## Architecture invariants established

- **Dual-wire readiness:** the vec0 infrastructure is fully functional but
  unused at this phase. `RagEngine._index_sync` and `_search_sync` continue
  to use ChromaDB. Switching requires only replacing the collection calls with
  `db.vector_index()` / `db.vector_search()`.
- **Single DB file:** vector data lives in `cognits.db` alongside relational
  data. No separate ChromaDB directory for vectors once cutover is complete.
- **Shared rowid is the coupling mechanism:** `report_chunks` and `chunks_vec`
  are linked by rowid, not by a SQL JOIN on TEXT ids. This is efficient but
  brittle — the rowid generator must be deterministic and stable across restarts.

## Tests added

No new tests in this phase. The vector infrastructure was verified manually
(index, search, count). Automated tests were deferred to Phase 6's RRF and
chunker test files.

## Deferred / out of scope

- **ChromaDB cutover:** ChromaDB remains the active dense store. The vec0 code
  is dead code until `engine.py` is refactored. This was later addressed in
  the 0.0.7 bring-forward (T5).
- **`INSERT OR REPLACE` → `ON CONFLICT DO UPDATE`:** the `vector_index` method
  violates the AGENTS.md invariant. Fixed in T5a of the bring-forward spec.
- **Deterministic rowid generation:** `abs(hash())` is per-process randomized
  in Python 3.8+. Fixed in T5a.
- **Cosine metric declaration:** `chunks_vec` uses L2 in queries but should
  declare `distance_metric=cosine` for correctness. Fixed in T5a.
- **ANN index (IVF/DiskANN):** sqlite-vec v0.1.x is brute-force only. Acceptable
  at ≤10 K vectors; revisit if the user accumulates >50 K chunks.

## Commits

| SHA | Description |
|-----|-------------|
| `681ef0d` | P2 — sqlite-vec infrastructure for RAG (schema, extension loading, vector methods) |
| `fb652fc` | P0 — Phase 5 bug fixes (NameError, dead code, dup imports, docstrings) |
| `77c7f78` | AGENTS.md update for Phase 5 |
