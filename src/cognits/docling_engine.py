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
        self._loop: asyncio.AbstractEventLoop | None = None

    @classmethod
    def start_background(cls) -> "DoclingEngine":
        engine = cls()
        engine._loop = asyncio.get_running_loop()
        loop = engine._loop

        def _init() -> None:
            try:
                import os
                os.environ.setdefault("ORT_LOG_LEVEL", "ERROR")
                os.environ.setdefault("OMP_NUM_THREADS", "8")

                log.debug("docling: loading models (~1 GB)...")
                from docling.datamodel.base_models import InputFormat
                from docling.datamodel.pipeline_options import (
                    PdfPipelineOptions,
                    TableFormerMode,
                )
                from docling.document_converter import (
                    DocumentConverter,
                    PdfFormatOption,
                )

                pipeline_opts = PdfPipelineOptions()
                pipeline_opts.do_ocr = False
                pipeline_opts.do_table_structure = True
                pipeline_opts.table_structure_options.mode = TableFormerMode.FAST
                pipeline_opts.do_code_enrichment = False
                pipeline_opts.do_formula_enrichment = False
                pipeline_opts.do_picture_classification = False
                pipeline_opts.images_scale = 1.0
                pipeline_opts.force_backend_text = True

                engine._converter = DocumentConverter(format_options={
                    InputFormat.PDF: PdfFormatOption(
                        pipeline_options=pipeline_opts,
                    ),
                })
                log.debug("docling: models ready")
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
        if not self.ready.is_set():
            self.error = "shutdown"
            if self._loop:
                self._loop.call_soon_threadsafe(self.ready.set)
        self._executor.shutdown(wait=False, cancel_futures=True)
