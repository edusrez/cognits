"""RAG in-process: fusion of the Flask sidecar (sidecar.py) and its Go client.

ChromaDB and fastembed are synchronous and heavy: they live in a
ThreadPoolExecutor with ONE thread that serializes all access (like the
Flask single-threaded sidecar) without blocking the event loop.
Initialization (ONNX model load, ~5-15s; first time downloads ~2.3 GB)
runs in that thread in the background: the server starts instantly and
tools degrade with a clear error until ready is set.
"""

from __future__ import annotations

import asyncio
import logging
import multiprocessing
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from cognits import paths

log = logging.getLogger("cognits.rag")

COLLECTION_NAME = "reports"


class RagNotReady(Exception):
    pass


class RagEngine:
    def __init__(self, storage_path: Path):
        self.storage_path = storage_path
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="rag")
        self.ready = asyncio.Event()
        self.error: str | None = None
        self.progress: int = 0
        self._model = None
        self._collection = None

    @classmethod
    def start_background(cls) -> "RagEngine":
        engine = cls(paths.data_dir() / "rag" / "chroma_db")
        loop = asyncio.get_running_loop()

        def _init() -> None:
            try:
                engine._load()
            except Exception as e:
                engine.error = f"{e}"
                log.error("rag: init: %s (RAG features disabled)", e)
            else:
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
            import chromadb
            from chromadb.config import Settings
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
            _ = TextEmbedding(model_name="BAAI/bge-m3", cache_dir=cache_dir)
        except Exception as e:
            if error_queue is not None:
                error_queue.put(f"{type(e).__name__}: {e}")
            raise

    def _load(self) -> None:
        import chromadb
        from chromadb.config import Settings

        log.debug("rag: loading BGE-M3 (first time downloads ~2.3 GB)...")
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
            while proc.is_alive():
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

        # Phase 2: init ChromaDB only (lightweight, no ONNX GIL).
        # Model loading is deferred to _ensure_model() so the spinner
        # stays smooth during startup.
        saved = os.dup(2)
        devnull = os.open(os.devnull, os.O_WRONLY)
        os.dup2(devnull, 2)
        os.close(devnull)
        try:
            client = chromadb.PersistentClient(
                path=str(self.storage_path),
                settings=Settings(anonymized_telemetry=False),
            )
            self._collection = client.get_or_create_collection(
                name=COLLECTION_NAME,
                metadata={"hnsw:space": "cosine"},
            )
        finally:
            os.dup2(saved, 2)
            os.close(saved)
        log.debug(
            "rag: ready in %s (collection %s, %d docs; model on demand)",
            self.storage_path,
            COLLECTION_NAME,
            self._collection.count(),
        )

    def shutdown(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)

    def _require_ready(self) -> None:
        if not self.ready.is_set():
            if self.error:
                raise RagNotReady(f"RAG engine not available: {self.error}")
            raise RagNotReady("RAG engine still loading, retry in a few seconds")

    def _ensure_model(self) -> None:
        """Load BGE-M3 on first use — deferred so startup spinner stays smooth.
        Called from the executor thread; blocks briefly during ONNX init
        (~200-500 ms) but has no impact on the TUI spinner."""
        if self._model is not None:
            return
        from fastembed import TextEmbedding
        from fastembed.common.model_description import ModelSource, PoolingType

        path = os.dup(2)
        devnull = os.open(os.devnull, os.O_WRONLY)
        os.dup2(devnull, 2)
        os.close(devnull)
        try:
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
            self._model = TextEmbedding(model_name="BAAI/bge-m3")
        finally:
            os.dup2(path, 2)
            os.close(path)

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
        return await self._run(self._collection.count)

    # --- synchronous implementation (only on the executor thread) ---

    def _search_sync(self, query: str, max_results: int) -> list[dict]:
        self._ensure_model()
        # query_embed returns a generator with ONE embedding; wrapping the
        # entire list in another list produced shape 1x1x1024 and broke.
        query_embedding = next(iter(self._model.query_embed(query)))
        results = self._collection.query(
            query_embeddings=[query_embedding.tolist()],
            n_results=max_results,
            include=["documents", "metadatas", "distances"],
        )

        chunks = []
        if results["ids"] and results["ids"][0]:
            for i, doc_id in enumerate(results["ids"][0]):
                meta = results["metadatas"][0][i] if results["metadatas"] else {}
                chunks.append(
                    {
                        "id": doc_id,
                        "text": results["documents"][0][i] if results["documents"] else "",
                        "distance": results["distances"][0][i] if results["distances"] else 0.0,
                        "report_id": meta.get("report_id", ""),
                        "source_type": meta.get("source_type", ""),
                        "topic": meta.get("topic", ""),
                        "chunk_index": meta.get("chunk_index", 0),
                    }
                )
        return chunks

    def _index_sync(self, chunks: list[dict]) -> int:
        self._ensure_model()
        texts = [c["text"] for c in chunks]
        ids = [c["id"] for c in chunks]
        metadatas = [
            {k: v for k, v in c.items() if k not in ("id", "text")} for c in chunks
        ]

        embeddings = list(self._model.embed(texts, batch_size=min(len(texts), 32)))
        self._collection.add(
            ids=ids,
            embeddings=[e.tolist() for e in embeddings],
            documents=texts,
            metadatas=metadatas,
        )
        log.info("rag: indexed %d chunks (total: %d)", len(chunks), self._collection.count())
        return len(chunks)
