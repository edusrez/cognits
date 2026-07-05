# Phase 6 — Hybrid search: RRF fusion, cross-encoder reranker, and paragraph-aware chunking

**Version:** 0.0.7
**Date:** 2026-07-05
**Status:** shipped (retrospective)
**Decisions locked:** RRF k=60 for score combination, cross-encoder Xenova/ms-marco-MiniLM-L-6-v2 (~80 MB), chunker v2 respects ##/### headers with parent_section metadata, v2 is parallel (not replacement) to v1

## Context

Phase 0–3 used dense-only vector search via ChromaDB (`rag.search()`). This had
two limitations:

1. **No sparse retrieval:** semantically similar but lexically different queries
   worked well, but exact keyword matches (skill names, code snippets, proper
   nouns) were missed if the embedding drifted.
2. **Flat chunking:** `split_markdown()` split by paragraph boundaries up to
   `CHUNK_SIZE` (1600 chars) with fixed overlap (160 chars), ignoring document
   structure. A chunk could span across section boundaries, mixing unrelated
   content.

Phase 6 introduced hybrid retrieval combining dense vector search with FTS5
BM25 sparse search, fused via Reciprocal Rank Fusion (RRF), and optionally
re-ranked by a cross-encoder. A new paragraph-aware chunker (v2) respected
markdown headers for section-bounded chunks.

## What changed

### RAG constants centralization (P1 commit)

**File:** `src/cognits/constants.py` (additions), `src/cognits/paths.py` (additions),
`src/cognits/rag/engine.py` (refactored)

Before the hybrid search feature, hardcoded RAG values were centralized:

```python
EMBEDDING_MODEL = "BAAI/bge-m3"
EMBEDDING_DIM = 1024
EMBEDDING_BATCH_SIZE = 32
RAG_COLLECTION_NAME = "reports"
RAG_DISTANCE_METRIC = "cosine"
RAG_DEFAULT_MAX_RESULTS = 10
RAG_WARM_TIMEOUT_S = 300
RAG_WORKER_RLIMIT_GB = 3
```

`paths.py` added `rag_dir()`, `chroma_db_path()`, `fastembed_cache_dir()`.
`app.py` added `AppState.rag_or_none` property, replacing 6 repeated
`st.rag is not None` checks across `chat_service.py`.

### RRF fusion

**File:** `src/cognits/rag/engine.py` (added `rrf_fuse()`)

```python
def rrf_fuse(dense_results, sparse_results, k=60, max_results=10):
```

Reciprocal Rank Fusion combines dense and sparse ranked result lists:

```
score(d) = Σ 1/(k + rank_i(d))
```

Where `k=60` is the damping constant (standard value from the fusion
literature). Documents appearing in both lists receive a boost; documents
appearing in only one list are not penalized.

The function handles edge cases: empty inputs, single-source runs, and
produces a deduplicated ranked list up to `max_results * 2`.

### Cross-encoder reranker

**File:** `src/cognits/rag/engine.py` (added `rerank_cross_encoder()`)

```python
def rerank_cross_encoder(query, candidates):
```

Uses `fastembed.TextCrossEncoder` with `Xenova/ms-marco-MiniLM-L-6-v2`
(~80 MB, downloaded lazily on first use). The cross-encoder scores each
(query, candidate) pair jointly (not as independent vectors), producing
more accurate relevance judgements than cosine similarity alone.

The reranker runs only when `len(fused) > max_results` (i.e., the fused
list has surplus candidates to prune). It adds a `rerank_score` field to
each candidate dict and sorts descending.

### search_hybrid() pipeline

**File:** `src/cognits/rag/engine.py` (added `search_hybrid()` method)

The complete pipeline:

1. **Dense retrieval:** calls `_search_sync()` via the existing ChromaDB path,
   requesting `max_results * 2` candidates.
2. **Sparse retrieval:** calls `reports_repo.search_fts()` (FTS5 BM25) with the
   same `max_results * 2` window. Wrapped in `asyncio.to_thread()` to offload
   blocking SQLite from the event loop. Results are mapped to the same dict
   shape as dense results.
3. **RRF fusion:** `rrf_fuse(dense, sparse, max_results * 2)`.
4. **Cross-encoder rerank:** if `rerank=True` (default), apply
   `rerank_cross_encoder(query, fused)` and trim to `max_results`.
5. **Return** `fused[:max_results]`.

The `reports_repo` parameter accepts a `ReportRepository` instance wired from
the caller (tool_rag.py at the call site). `db` is accepted but unused at
this phase (reserved for the vec0 cutover).

### Paragraph-aware chunker v2

**File:** `src/cognits/rag/chunker.py` (added `split_markdown_v2()`)

```python
def split_markdown_v2(md, report_id, topic, source_type="web"):
```

Key differences from v1 (`split_markdown`):

| Aspect | v1 | v2 |
|--------|----|----|
| Section boundaries | None — flat paragraph merge | Splits on `## ` and `### ` headers |
| Metadata | id, text, report_id, source_type, topic, chunk_index | Same + `parent_section` (the header text) |
| Paragraph handling | Blind merge up to CHUNK_SIZE | Maintains per-section paragraphs, sub-splits within sections |
| Overlap | Fixed 160-char overlap | Per-section overlap (same function) |
| Fallback | N/A | Falls back to v1 for very large sections |

The `parent_section` metadata enables "small-to-big" retrieval: a chunk can
include its parent section heading in the LLM context, giving the model the
section-level context even when only a sub-section chunk was retrieved.

v2 is added alongside v1, not replacing it. `tool_deploy.py` continues to
use `split_markdown()` — the v2 switch is gated behind a tool parameter.

### Backend cleanup (commit `d135a22`)

- `rag/engine.py`: `COLLECTION_NAME` reads from `constants.RAG_COLLECTION_NAME`
- `rag/engine.py`: `RagNotReady` extends `CognitsError` (consistent error hierarchy)
- `rag/chunker.py`: `source_type` parameter added (was hardcoded `'web'`)

## Tests added

**File:** `tests/test_rrf.py` — 7 tests:

- `test_empty_dense` / `test_empty_sparse` — single-source fusion
- `test_both_empty` — empty inputs produce empty output
- `test_score_combining` — RRF scores verified for overlapping docs
- `test_max_results_cap` — output limited correctly
- `test_overlapping_ranks` — boost visible when document appears in both lists
- `test_document_data_preserved` — original dict keys survive fusion

**File:** `tests/test_chunker_v2.py` — 7 tests:

- `test_header_respect` — sections split on `## ` boundaries
- `test_empty_input` — empty string produces empty chunk list
- `test_chunk_ids` — ID format `{report_id}_c{idx}` preserved
- `test_source_type_passthrough` — source_type propagated
- `test_topic_metadata` — topic propagated
- `test_parent_section_present` — each chunk has non-empty parent_section
- `test_backward_compat` — v1 `split_markdown()` unchanged

## Architecture invariants established

- **Hybrid search is opt-in:** `search()` (dense-only) remains available.
  `search_hybrid()` is a separate method. Tools are migrated individually.
- **FTS5 is the sparse source:** BM25 scores from the FTS5 `reports_fts` table,
  not a separate inverted index. This keeps sparse retrieval within SQLite.
- **reports_repo is wired at call site:** `RagSearch` tool takes `reports_repo`
  as a constructor parameter, not a global. This keeps the dependency explicit.
- **Cross-encoder is lazy:** the model is downloaded on first `rerank_cross_encoder`
  call, not at RagEngine init.

## Deferred / out of scope

- **Chunker v2 is dead code at this phase:** `tool_deploy.py` continues to use
  v1. Activating v2 requires a tool parameter or migration flag.
- **Fence-aware section split:** v2 splits on `##` and `###` but does not handle
  H1/H3 boundaries or code fence-aware paragraph extraction (H1 and H3 were
  documented as future work).
- **Cross-encoder model caching:** the model is loaded on every `rerank_cross_encoder`
  call. A cache (or singleton) was deferred.
- **`reports_repo.search_fts` not wrapped in `to_thread`:** the FTS call in
  `search_hybrid` (line 276–285) runs synchronously inside the executor thread,
  which is correct but the commit message flagged it. Later hardened in T10 of
  the 0.0.7 hardening spec.

## Commits

| SHA | Description |
|-----|-------------|
| `d135a22` | P1 — centralize RAG hardcoded values in constants.py + paths.py + app.rag_or_none |
| `8f1aa15` | P3 — hybrid search (RRF fusion + cross-encoder reranker) |
| `416810b` | P4 — paragraph-aware chunking v2 (header-respecting, parent_section metadata) |
| `251d133` | P5 — tests for RRF fusion (7 tests) + chunker v2 (7 tests) |
| `e5561d0` | AGENTS.md update for Phase 6 (hybrid search docs, chunker v2, embedding_worker) |
