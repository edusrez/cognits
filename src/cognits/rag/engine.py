"""RAG engine: dense vector search and hybrid retrieval.

Architecture:
- BGE-M3 ONNX inference via fastembed in a worker process (embed/query_embed
  via Pipe RPC), keeping the event loop free.
- sqlite-vec vec0 virtual table for dense vector storage (cosine via L2 on normalized BGE-M3 embeddings).
- Hybrid search: dense (cosine) + FTS5 BM25 sparse → RRF fusion → optional
  cross-encoder reranker (ms-marco-MiniLM-L-6-v2).
- First-time model download (~2.3 GB) runs in a child process during startup;
  the server starts instantly and tools degrade with a clear error until ready.
"""

from __future__ import annotations

import asyncio
import logging
import multiprocessing
import os
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

log = logging.getLogger("cognits.rag")

from cognits.constants import RAG_DEFAULT_MAX_RESULTS
from cognits.server.exceptions import CognitsError
from cognits.storage.fsdetect import fstype_of, is_wal_unsafe_fstype


class RagNotReady(CognitsError):
    def __init__(self, message: str):
        super().__init__(message, "RAG_NOT_READY", 503)


class RagEngine:
    def __init__(self):
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="rag")
        self.ready = asyncio.Event()
        self.error: str | None = None
        self.progress: int = 0
        self._loop: asyncio.AbstractEventLoop | None = None
        self._warm_proc: multiprocessing.Process | None = None
        self._worker_proc: multiprocessing.Process | None = None
        self._worker_pipe: object | None = None
        self._db = None

    def set_db(self, db) -> None:
        self._db = db

    @classmethod
    def start_background(cls) -> "RagEngine":
        engine = cls()
        engine._loop = asyncio.get_running_loop()
        loop = engine._loop

        def _init() -> None:
            try:
                engine._load()
            except Exception as e:
                engine.error = f"{e}"
                log.error("rag: init: %s (RAG features disabled)", e)
            finally:
                loop.call_soon_threadsafe(engine.ready.set)

        engine._executor.submit(_init)
        return engine

    @staticmethod
    def _warm_cache(error_queue: multiprocessing.Queue | None = None,
                    progress_val: "multiprocessing.Value[int]" | None = None) -> None:
        """Download BGE-M3 model files in a child process so ONNX Runtime
        graph optimisation (which holds the GIL for seconds) never blocks
        the parent's event loop.  The child has its own GIL."""
        try:
            from fastembed import TextEmbedding
            from fastembed.common.model_description import ModelSource, PoolingType
            from huggingface_hub import snapshot_download
            from tqdm.auto import tqdm as base_tqdm

            import onnxruntime as _ort
            _ort.set_default_logger_severity(4)

            class ProgressTqdm(base_tqdm):
                def __init__(self, *args, **kwargs):
                    kwargs.pop("name", None)
                    kwargs["disable"] = False
                    super().__init__(*args, **kwargs)

                def update(self, n=1):
                    super().update(n)
                    if progress_val is not None and self.total:
                        progress_val.value = min(99, int(self.n / self.total * 100))

            # Step 1: download model files with progress tracking.
            cache_dir = os.environ.get("FASTEMBED_CACHE_DIR",
                           str(Path.home() / ".cache" / "fastembed"))
            snapshot_download(
                repo_id="BAAI/bge-m3",
                cache_dir=cache_dir,
                allow_patterns=["onnx/*", "*.json", "*.model"],
                tqdm_class=ProgressTqdm,
            )
            if progress_val is not None:
                progress_val.value = 100

            TextEmbedding.add_custom_model(
                model="BAAI/bge-m3",
                pooling=PoolingType.CLS,
                normalization=True,
                sources=ModelSource(hf="BAAI/bge-m3"),
                dim=1024,
                model_file="onnx/model.onnx",
                description="Text embeddings, Unimodal, Multilingual (100+ languages), 8192 tokens",
                license="mit",
                size_in_gb=2.27,
                additional_files=["onnx/model.onnx_data",
                                   "onnx/sentencepiece.bpe.model"],
            )
            # Step 2: load model (ONNX init, uses cache from step 1).
            _ = TextEmbedding(model_name="BAAI/bge-m3", cache_dir=cache_dir, threads=1)
        except Exception as e:
            if error_queue is not None:
                error_queue.put(f"{type(e).__name__}: {e}")
            raise

    def _load(self) -> None:
        log.debug("rag: loading BGE-M3 (first time downloads ~2.3 GB)...")
        # Redirect model cache to native Linux FS when on 9p/DrvFs.
        # ONNX Runtime mmap's the .onnx model file, which fails on 9p.
        cache_dir = os.environ.get("FASTEMBED_CACHE_DIR",
                       str(Path.home() / ".cache" / "fastembed"))
        if is_wal_unsafe_fstype(fstype_of(cache_dir)):
            redirect = str(Path("/tmp").resolve() / "fastembed_cache")
            Path(redirect).mkdir(parents=True, exist_ok=True)
            os.environ["FASTEMBED_CACHE_DIR"] = redirect
            log.warning(
                "rag: model cache redirected to %s (9p/DrvFs detected at %s)",
                redirect,
                cache_dir,
            )
        # Phase 1: warm cache in subprocess — ONNX holds the GIL for seconds
        # during graph optimisation; a child process has its own GIL so the
        # parent's spinner stays smooth.
        progress_val: multiprocessing.Value[int] = multiprocessing.Value("i", 0)
        try:
            error_queue: multiprocessing.Queue[str] = multiprocessing.Queue()
            proc = multiprocessing.Process(
                target=RagEngine._warm_cache,
                args=(error_queue, progress_val),
            )
            proc.start()
            self._warm_proc = proc  # tracked so shutdown() can terminate it
            deadline = time.monotonic() + 300  # 5 min timeout
            while proc.is_alive():
                if time.monotonic() > deadline:
                    log.warning("rag: warm-cache subprocess timed out after 5 min")
                    proc.terminate()
                    proc.join(timeout=5)
                    break
                proc.join(timeout=0.15)
                self.progress = progress_val.value
            self.progress = 100
            if proc.exitcode != 0:
                detail = ""
                try:
                    detail = f": {error_queue.get_nowait()}"
                except Exception:
                    pass
                log.warning(
                    "rag: warm-cache subprocess failed (exit %d%s), "
                    "loading on first use instead",
                    proc.exitcode,
                    detail,
                )
        except Exception as e:
            log.warning("rag: warm-cache subprocess error: %s", e)

        log.debug("rag: ready (model on demand)")

    def shutdown(self) -> None:
        # Terminate the warm-cache subprocess first, so _load() unblocks from
        # proc.join() and the executor thread can exit. Without this, the
        # thread stays alive and Python's atexit thread.join hangs (Ctrl+C
        # during model download produces a traceback).
        wp = self._warm_proc
        if wp is not None and wp.is_alive():
            try:
                wp.terminate()  # SIGTERM
                wp.join(timeout=3)
                if wp.is_alive():
                    wp.kill()  # SIGKILL — not catchable, force exit
                    wp.join(timeout=2)
            except Exception:
                pass
        if not self.ready.is_set():
            self.error = "shutdown"
            if self._loop:
                self._loop.call_soon_threadsafe(self.ready.set)
        self._executor.shutdown(wait=False, cancel_futures=True)
        if self._worker_pipe is not None:
            try:
                self._worker_pipe.send(("shutdown", None))
                self._worker_pipe.recv()
            except Exception:
                pass
        if self._worker_proc is not None and self._worker_proc.is_alive():
            try:
                self._worker_proc.kill()
                self._worker_proc.join(timeout=2)
            except Exception:
                pass

    def _require_ready(self) -> None:
        if not self.ready.is_set():
            if self.error:
                raise RagNotReady(f"RAG engine not available: {self.error}")
            raise RagNotReady("RAG engine still loading, retry in a few seconds")
        if self._db is None:
            raise RagNotReady("vec0 database not wired")

    def _ensure_worker(self) -> object:
        if self._worker_pipe is not None:
            if self._worker_proc is not None and self._worker_proc.is_alive():
                return self._worker_pipe
            # Worker died (OOM or crash) — respawn
            self._worker_pipe = None
        from cognits.rag.embedding_worker import start_worker
        self._worker_proc, self._worker_pipe = start_worker()
        return self._worker_pipe

    async def _run(self, fn, *args):
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self._executor, fn, *args)

    # --- API equivalente a rag/client.go ---

    async def search(self, query: str, max_results: int = 10) -> list[dict]:
        self._require_ready()
        if max_results <= 0:
            max_results = 10
        return await self._run(self._search_sync, query, max_results)

    async def index(self, chunks: list[dict]) -> int:
        self._require_ready()
        if not chunks:
            return 0
        return await self._run(self._index_sync, chunks)

    async def count(self) -> int:
        self._require_ready()
        return await self._run(self._db.vector_count)

    async def search_hybrid(
        self, query: str, reports_repo=None, db=None,
        max_results: int = 10, rerank: bool = True,
    ) -> list[dict]:
        self._require_ready()
        if max_results <= 0:
            max_results = RAG_DEFAULT_MAX_RESULTS
        dense = await self._run(self._search_sync, query, max_results * 2)
        sparse = []
        if reports_repo is not None:
            try:
                fts_result = await asyncio.to_thread(
                    reports_repo.search_fts, 1, max_results * 2, "score", query
                )
                for r in fts_result.get("reports", []):
                    sparse.append({
                        "id": r.get("id", ""), "report_id": r.get("id", ""),
                        "text": r.get("content", "")[:500], "source_type": "fts5",
                        "topic": r.get("title", ""), "distance": 0.0, "chunk_index": 0,
                    })
            except Exception:
                pass
        fused = rrf_fuse(dense, sparse, max_results=max_results * 2)
        if rerank and len(fused) > max_results:
            fused = rerank_cross_encoder(query, fused)
            fused = fused[:max_results]
        return fused[:max_results]

    # --- synchronous implementation (only on the executor thread) ---

    def _worker_embed(self, texts: list[str]) -> list[list[float]]:
        try:
            pipe = self._ensure_worker()
            pipe.send(("embed", texts))
            status, result = pipe.recv()
        except (EOFError, BrokenPipeError, OSError):
            self._worker_pipe = None  # force respawn on next call
            raise RagNotReady("embedding worker died, respawning — retry in a moment")
        if status != "ok":
            raise RagNotReady(f"embedding worker error: {result}")
        return result

    def _worker_query_embed(self, query: str) -> list[float]:
        try:
            pipe = self._ensure_worker()
            pipe.send(("query_embed", query))
            status, result = pipe.recv()
        except (EOFError, BrokenPipeError, OSError):
            self._worker_pipe = None  # force respawn on next call
            raise RagNotReady("embedding worker died, respawning — retry in a moment")
        if status != "ok":
            raise RagNotReady(f"embedding worker error: {result}")
        return result

    def _search_sync(self, query: str, max_results: int) -> list[dict]:
        query_embedding = self._worker_query_embed(query)
        return self._db.vector_search(query_embedding, max_results)

    def _index_sync(self, chunks: list[dict]) -> int:
        texts = [c["text"] for c in chunks]

        embeddings = self._worker_embed(texts)
        self._db.vector_index(chunks, embeddings)
        log.info("rag: indexed %d chunks (total: %d)", len(chunks), self._db.vector_count())
        del embeddings, texts
        import gc; gc.collect()
        return len(chunks)


# -- Hybrid search (RRF + cross-encoder) -----------------------------------

def rrf_fuse(dense_results: list[dict], sparse_results: list[dict],
             k: int = 60, max_results: int = 10) -> list[dict]:
    """Reciprocal Rank Fusion: combine dense and sparse ranked results."""
    scores: dict[str, float] = {}
    docs: dict[str, dict] = {}

    for rank, r in enumerate(dense_results):
        doc_id = r.get("id", "")
        scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (k + rank + 1)
        docs[doc_id] = r

    for rank, r in enumerate(sparse_results):
        doc_id = r.get("id", "")
        scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (k + rank + 1)
        docs[doc_id] = r

    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    return [docs[doc_id] for doc_id, _ in ranked[:max_results]]


def rerank_cross_encoder(query: str, candidates: list[dict]) -> list[dict]:
    """Re-rank top candidates using a cross-encoder model."""
    try:
        from fastembed import TextCrossEncoder
        _ce = TextCrossEncoder(model_name="Xenova/ms-marco-MiniLM-L-6-v2")
        passages = [c.get("text", "") for c in candidates]
        scores = list(_ce.rerank(query, passages))
        for c, s in zip(candidates, scores):
            c["rerank_score"] = float(s)
        candidates.sort(key=lambda c: c.get("rerank_score", 0), reverse=True)
    except ImportError:
        pass
    return candidates

