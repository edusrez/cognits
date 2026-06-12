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

    def _load(self) -> None:
        # Imports here: they're heavy (onnxruntime) and optional — if missing,
        # the rest of the app works without RAG.
        import chromadb
        from chromadb.config import Settings
        from fastembed import TextEmbedding
        from fastembed.common.model_description import ModelSource, PoolingType

        # BGE-M3: multilingual (100+ languages), 1024 dims, up to 8192 tokens,
        # and no query:/passage: prefix asymmetry. Not natively supported in
        # fastembed 0.8.0: registered as a custom model with the HuggingFace
        # ONNX (identical to the Go sidecar to reuse the already downloaded
        # model cache).
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
            additional_files=["onnx/model.onnx_data", "onnx/sentencepiece.bpe.model"],
        )
        log.info("rag: loading BGE-M3 (first time downloads ~2.3 GB)...")
        self._model = TextEmbedding(model_name="BAAI/bge-m3")
        client = chromadb.PersistentClient(
            path=str(self.storage_path),
            settings=Settings(anonymized_telemetry=False),
        )
        self._collection = client.get_or_create_collection(
            name=COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"},
        )
        log.info(
            "rag: ready in %s (collection %s, %d docs)",
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
