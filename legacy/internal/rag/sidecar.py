"""
Learn It RAG Sidecar — Flask + ChromaDB + fastembed (BGE-M3)
Provides embedding generation and semantic search for the Go backend.
"""

import os
import sys
import json
import logging
from pathlib import Path

from flask import Flask, request, jsonify
import chromadb
from chromadb.config import Settings
from fastembed import TextEmbedding
from fastembed.common.model_description import PoolingType, ModelSource

logging.basicConfig(level=logging.INFO, format="[rag] %(message)s")
log = logging.getLogger("rag")

STORAGE_PATH = os.environ.get("LEARNIT_RAG_PATH", ".learnit/rag/chroma_db")
COLLECTION_NAME = "reports"

app = Flask(__name__)

# BGE-M3: multilingüe (100+ idiomas), 1024 dims, hasta 8192 tokens y sin la
# asimetría de prefijos query:/passage: que exigía multilingual-e5-large.
#
# BGE-M3 no está soportado nativamente en fastembed 0.8.0 (PR #602 sin
# mergear). Se registra como modelo custom usando el ONNX de HuggingFace.
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
embedding_model = TextEmbedding(model_name="BAAI/bge-m3")
chroma_client = chromadb.PersistentClient(
    path=STORAGE_PATH,
    settings=Settings(anonymized_telemetry=False),
)
collection = chroma_client.get_or_create_collection(
    name=COLLECTION_NAME,
    metadata={"hnsw:space": "cosine"},
)
log.info("ChromaDB ready at %s (collection: %s, %d docs)", STORAGE_PATH, COLLECTION_NAME, collection.count())


@app.route("/health")
def health():
    return jsonify({"status": "ok", "docs": collection.count()})


@app.route("/embed", methods=["POST"])
def embed():
    data = request.get_json()
    if not data or "texts" not in data:
        return jsonify({"error": "missing texts"}), 400

    texts = data["texts"]
    if not texts:
        return jsonify({"embeddings": []})

    embeddings = list(embedding_model.embed(texts, batch_size=min(len(texts), 32)))
    return jsonify({"embeddings": [e.tolist() for e in embeddings]})


@app.route("/search", methods=["POST"])
def search():
    data = request.get_json()
    if not data or "query" not in data:
        return jsonify({"error": "missing query"}), 400

    query = data["query"]
    max_results = int(data.get("max_results", 10))

    # query_embed devuelve un generador con UN embedding; envolver la lista
    # entera en otra lista producía shape 1x1x1024 y la query fallaba siempre.
    query_embedding = next(iter(embedding_model.query_embed(query)))
    results = collection.query(
        query_embeddings=[query_embedding.tolist()],
        n_results=max_results,
        include=["documents", "metadatas", "distances"],
    )

    chunks = []
    if results["ids"] and results["ids"][0]:
        for i, doc_id in enumerate(results["ids"][0]):
            meta = results["metadatas"][0][i] if results["metadatas"] else {}
            chunks.append({
                "id": doc_id,
                "text": results["documents"][0][i] if results["documents"] else "",
                "distance": results["distances"][0][i] if results["distances"] else 0.0,
                "report_id": meta.get("report_id", ""),
                "source_type": meta.get("source_type", ""),
                "topic": meta.get("topic", ""),
                "chunk_index": meta.get("chunk_index", 0),
            })

    return jsonify({"chunks": chunks})


@app.route("/index", methods=["POST"])
def index_chunks():
    data = request.get_json()
    if not data or "chunks" not in data:
        return jsonify({"error": "missing chunks"}), 400

    chunks = data["chunks"]
    if not chunks:
        return jsonify({"indexed": 0})

    texts = [c["text"] for c in chunks]
    ids = [c["id"] for c in chunks]
    metadatas = [{k: v for k, v in c.items() if k not in ("id", "text")} for c in chunks]

    embeddings = list(embedding_model.embed(texts, batch_size=min(len(texts), 32)))
    collection.add(
        ids=ids,
        embeddings=[e.tolist() for e in embeddings],
        documents=texts,
        metadatas=metadatas,
    )

    log.info("indexed %d chunks (total: %d)", len(chunks), collection.count())
    return jsonify({"indexed": len(chunks)})


@app.route("/count")
def count():
    return jsonify({"count": collection.count()})


if __name__ == "__main__":
    port = int(os.environ.get("RAG_PORT", "7825"))
    log.info("starting sidecar on :%d", port)
    app.run(host="127.0.0.1", port=port, debug=False)
