"""Docling model engine — loads models in background at startup."""

from __future__ import annotations

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor

log = logging.getLogger(__name__)


class DoclingEngine:
    def __init__(self) -> None:
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="docling")
        self.ready = asyncio.Event()
        self.error: str | None = None
        self._converter = None

    @classmethod
    def start_background(cls) -> "DoclingEngine":
        engine = cls()
        loop = asyncio.get_running_loop()

        def _init() -> None:
            try:
                from docling.utils.model_downloader import download_models

                log.debug("docling: downloading models (~1 GB)...")
                download_models()
                log.debug("docling: models ready")

                from docling.document_converter import DocumentConverter

                engine._converter = DocumentConverter()
            except Exception as e:
                engine.error = str(e)
                log.error("docling: init: %s (PDF AI mode disabled)", e)
            else:
                loop.call_soon_threadsafe(engine.ready.set)

        engine._executor.submit(_init)
        return engine

    @property
    def converter(self):
        if not self.ready.is_set():
            raise RuntimeError("Docling models not loaded yet")
        if self.error:
            raise RuntimeError(f"Docling init failed: {self.error}")
        return self._converter

    def shutdown(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)
