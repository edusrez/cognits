"""RAG in-process: fusión del sidecar Flask (sidecar.py) y su cliente Go.

ChromaDB y fastembed son síncronos y pesados: viven en un ThreadPoolExecutor
de UN hilo que serializa todo el acceso (como el Flask single-threaded del
sidecar) sin bloquear el event loop. La inicialización (carga del modelo
ONNX, ~5-15s; primera vez descarga ~2,3 GB) corre en ese hilo en background:
el servidor arranca al instante y las tools degradan con error claro hasta
que ready se active.
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
        # Imports aquí: son pesados (onnxruntime) y opcionales — si faltan,
        # el resto de la aplicación funciona sin RAG.
        import chromadb
        from chromadb.config import Settings
        from fastembed import TextEmbedding
        from fastembed.common.model_description import ModelSource, PoolingType

        # BGE-M3: multilingüe (100+ idiomas), 1024 dims, hasta 8192 tokens y
        # sin la asimetría de prefijos query:/passage:. No está soportado
        # nativamente en fastembed 0.8.0: se registra como modelo custom con
        # el ONNX de HuggingFace (idéntico al sidecar Go para reutilizar la
        # caché del modelo ya descargado).
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
        log.info("rag: cargando BGE-M3 (la primera vez descarga ~2,3 GB)...")
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
            "rag: listo en %s (colección %s, %d docs)",
            self.storage_path,
            COLLECTION_NAME,
            self._collection.count(),
        )

    def shutdown(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)

    def _require_ready(self) -> None:
        if not self.ready.is_set():
            if self.error:
                raise RagNotReady(f"motor RAG no disponible: {self.error}")
            raise RagNotReady("motor RAG todavía cargando, reintenta en unos segundos")

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

    # --- implementación síncrona (solo en el hilo del executor) ---

    def _search_sync(self, query: str, max_results: int) -> list[dict]:
        # query_embed devuelve un generador con UN embedding; envolver la
        # lista entera en otra lista producía shape 1x1x1024 y fallaba.
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
