"""Embedding worker process — isolates the BGE-M3 ONNX model in a subprocess
with a hard 3 GB address-space limit. If the model's arena grows too large the
worker dies but the main process survives (the engine reconnects on next use)."""

from __future__ import annotations

import multiprocessing
import os
import resource
import sys
from multiprocessing.connection import Connection

_MODEL_LOADED: bool = False
_MODEL: object = None


def _ensure_model():
    global _MODEL_LOADED, _MODEL
    if _MODEL_LOADED:
        return
    os.dup2(sys.stderr.fileno(), sys.stdout.fileno())
    from fastembed import TextEmbedding
    from fastembed.common.model_description import ModelSource, PoolingType

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
    _MODEL = TextEmbedding(
        model_name="BAAI/bge-m3",
        cache_dir=os.environ.get("FASTEMBED_CACHE_DIR"),
        threads=1,
    )
    _MODEL_LOADED = True


def _handle_embed(texts: list[str]) -> list[list[float]]:
    _ensure_model()
    embeddings = list(_MODEL.embed(texts, batch_size=32))
    return [e.tolist() for e in embeddings]


def _handle_query_embed(text: str) -> list[float]:
    _ensure_model()
    return next(iter(_MODEL.query_embed(text))).tolist()


def _main(pipe: Connection) -> None:
    limit_bytes = 3 * 1024 * 1024 * 1024
    try:
        resource.setrlimit(resource.RLIMIT_AS, (limit_bytes, limit_bytes))
    except (ValueError, OSError):
        pass
    while True:
        try:
            cmd, data = pipe.recv()
        except (EOFError, KeyboardInterrupt):
            break
        if cmd == "embed":
            try:
                result = _handle_embed(data)
                pipe.send(("ok", result))
            except MemoryError:
                pipe.send(("error", "embedding_worker: OOM"))
            except Exception as e:
                pipe.send(("error", f"{type(e).__name__}: {e}"))
        elif cmd == "query_embed":
            try:
                result = _handle_query_embed(data)
                pipe.send(("ok", result))
            except MemoryError:
                pipe.send(("error", "embedding_worker: OOM"))
            except Exception as e:
                pipe.send(("error", f"{type(e).__name__}: {e}"))
        elif cmd == "shutdown":
            pipe.send(("ok", None))
            break


def start_worker() -> tuple[multiprocessing.Process, Connection]:
    parent_pipe, child_pipe = multiprocessing.Pipe()
    proc = multiprocessing.Process(target=_main, args=(child_pipe,))
    proc.start()
    return proc, parent_pipe
