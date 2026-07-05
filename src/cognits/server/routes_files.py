"""File content endpoints — read / preview files from the project tree."""

from __future__ import annotations

import asyncio
import hashlib
import mimetypes
import os
from pathlib import Path
from urllib.parse import unquote

from fastapi import FastAPI
from fastapi.responses import JSONResponse, StreamingResponse

from cognits.paths import data_dir
from cognits.server.exceptions import CognitsError, ConfigError, NotFoundError, StorageError

# (category, language_hint) keyed by lowercase extension
EXT_MAP: dict[str, tuple[str, str | None]] = {
    ".py": ("code", "python"),
    ".js": ("code", "javascript"),
    ".ts": ("code", "typescript"),
    ".tsx": ("code", "typescript"),
    ".jsx": ("code", "javascript"),
    ".go": ("code", "go"),
    ".rs": ("code", "rust"),
    ".c": ("code", "c"),
    ".cpp": ("code", "cpp"),
    ".h": ("code", "c"),
    ".hpp": ("code", "cpp"),
    ".java": ("code", "java"),
    ".rb": ("code", "ruby"),
    ".php": ("code", "php"),
    ".swift": ("code", "swift"),
    ".kt": ("code", "kotlin"),
    ".kts": ("code", "kotlin"),
    ".lua": ("code", "lua"),
    ".r": ("code", "r"),
    ".dart": ("code", "dart"),
    ".erl": ("code", "erlang"),
    ".ex": ("code", "elixir"),
    ".exs": ("code", "elixir"),
    ".hs": ("code", "haskell"),
    ".scala": ("code", "scala"),
    ".clj": ("code", "clojure"),
    ".cs": ("code", "csharp"),
    ".vue": ("code", "xml"),
    ".svelte": ("code", "xml"),
    ".gd": ("code", None),
    ".diff": ("code", "diff"),
    ".patch": ("code", "diff"),
    ".graphql": ("code", "graphql"),
    ".gql": ("code", "graphql"),
    ".proto": ("code", "protobuf"),
    ".md": ("code", "markdown"),
    ".sh": ("code", "bash"),
    ".bash": ("code", "bash"),
    ".zsh": ("code", "bash"),
    ".sql": ("code", "sql"),
    ".css": ("code", "css"),
    ".scss": ("code", "css"),
    ".less": ("code", "css"),
    ".html": ("code", "xml"),
    ".htm": ("code", "xml"),
    ".xml": ("code", "xml"),
    ".yaml": ("code", "yaml"),
    ".yml": ("code", "yaml"),
    ".json": ("code", "json"),
    ".toml": ("code", "ini"),
    ".ini": ("code", "ini"),
    ".cfg": ("code", "ini"),
    ".conf": ("code", "ini"),
    ".txt": ("text", None),
    ".log": ("text", None),
    ".csv": ("text", None),
    ".env": ("text", None),
    ".gitignore": ("text", None),
    ".editorconfig": ("text", None),
    ".dockerfile": ("text", None),
    ".png": ("image", None),
    ".jpg": ("image", None),
    ".jpeg": ("image", None),
    ".gif": ("image", None),
    ".svg": ("image", None),
    ".webp": ("image", None),
    ".bmp": ("image", None),
    ".ico": ("image", None),
    ".pdf": ("pdf", None),
}

from cognits.constants import MAX_NAME_LENGTH, MAX_TEXT_BYTES


def _resolve_file(rel_path: str) -> Path:
    cwd = Path.cwd().resolve()
    full = (cwd / rel_path).resolve()
    if not full.is_relative_to(cwd):
        raise PermissionError("path outside project directory")
    if not full.exists():
        raise FileNotFoundError("file not found")
    if not full.is_file():
        raise IsADirectoryError("not a file")
    return full


def _classify(file_path: Path) -> tuple[str, str | None]:
    ext = file_path.suffix.lower()
    if ext in EXT_MAP:
        return EXT_MAP[ext]
    # Check full name for special files
    name = file_path.name.lower()
    if name in EXT_MAP:
        return EXT_MAP[name]
    return ("text", None)


def _pdf_to_markdown(file_path: Path, engine, docling_cfg, *, force: bool = False) -> str:
    cache_dir = data_dir() / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)

    key = hashlib.sha256(str(file_path.resolve()).encode()).hexdigest()
    cache_md = cache_dir / f"{key}.md"
    cache_mtime = cache_dir / f"{key}.mtime"

    current_mtime = file_path.stat().st_mtime

    if not force and cache_md.exists() and cache_mtime.exists():
        try:
            cached = float(cache_mtime.read_text().strip())
            if cached == current_mtime:
                return cache_md.read_text(encoding="utf-8")
        except (ValueError, OSError):
            pass

    if force:
        from docling.datamodel.base_models import InputFormat
        from docling.datamodel.pipeline_options import PdfPipelineOptions, TableFormerMode
        from docling.document_converter import DocumentConverter, PdfFormatOption

        pipeline_opts = PdfPipelineOptions()
        pipeline_opts.table_structure_options.mode = (
            TableFormerMode.ACCURATE if docling_cfg.table_mode == "accurate"
            else TableFormerMode.FAST
        )
        pipeline_opts.images_scale = docling_cfg.images_scale
        pipeline_opts.do_ocr = docling_cfg.do_ocr
        pipeline_opts.do_code_enrichment = docling_cfg.do_code_enrichment
        pipeline_opts.do_formula_enrichment = docling_cfg.do_formula_enrichment
        pipeline_opts.do_picture_classification = docling_cfg.do_picture_classification
        pipeline_opts.force_backend_text = docling_cfg.force_backend_text

        converter = DocumentConverter(format_options={
            InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_opts),
        })
    else:
        converter = engine.converter

    result = converter.convert(str(file_path))
    content = result.document.export_to_markdown() or ""

    cache_md.write_text(content, encoding="utf-8")
    cache_mtime.write_text(str(current_mtime))

    return content


def register(app: FastAPI, st) -> None:

    @app.get("/api/files/content")
    async def file_content(path: str = "", mode: str = "raw", force: str = ""):
        if not path:
            raise ConfigError("path is required")
        path = unquote(path)

        try:
            file_path = _resolve_file(path)
        except PermissionError:
            raise CognitsError("forbidden", "FORBIDDEN", 403)
        except FileNotFoundError:
            raise NotFoundError("file not found")
        except IsADirectoryError:
            raise ConfigError("not a file")

        category, language = _classify(file_path)
        mime, _ = mimetypes.guess_type(str(file_path))
        mime = mime or "application/octet-stream"
        size = file_path.stat().st_size

        if mode == "ai":
            if category == "image":
                raise ConfigError("AI mode not available for images")
            if category == "pdf":
                engine = st.docling_engine
                if engine is None or engine.error:
                    raise CognitsError("PDF AI mode not available (Docling not loaded)", "SERVICE_UNAVAILABLE", 503)
                try:
                    cfg = st.cached_config.docling_config
                    content = await asyncio.to_thread(
                        _pdf_to_markdown, file_path, engine, cfg,
                        force=force == "true"
                    )
                except Exception as e:
                    raise StorageError(f"conversion failed: {e}")
                return JSONResponse({
                    "path": str(file_path),
                    "category": "text",
                    "language": None,
                    "mime": "text/markdown",
                    "size": len(content.encode("utf-8")),
                    "content": content,
                    "stream_url": None,
                })
            # code / text: same as raw
            mode = "raw"

        # Raw mode
        stream_url = f"/api/files/raw?path={path}"

        if category in ("code", "text"):
            try:
                raw = await asyncio.to_thread(file_path.read_bytes)
            except OSError as e:
                raise StorageError(str(e))

            truncated = len(raw) > MAX_TEXT_BYTES
            if truncated:
                raw = raw[:MAX_TEXT_BYTES]

            encoding = "utf-8"
            try:
                content = raw.decode(encoding)
            except UnicodeDecodeError:
                try:
                    content = raw.decode("latin-1", errors="replace")
                    encoding = "latin-1"
                except Exception:
                    content = raw.decode("utf-8", errors="replace")

            if truncated:
                content += "\n\n[File truncated at 5 MB]"

            return JSONResponse({
                "path": str(file_path),
                "category": category,
                "language": language,
                "mime": mime,
                "size": size,
                "content": content,
                "stream_url": None,
                "truncated": truncated,
            })

        # image / pdf / other: no inline content, serve via stream_url
        return JSONResponse({
            "path": str(file_path),
            "category": category,
            "language": language,
            "mime": mime,
            "size": size,
            "content": None,
            "stream_url": stream_url,
        })

    @app.get("/api/files/raw")
    async def file_raw(path: str = ""):
        if not path:
            raise ConfigError("path is required")
        path = unquote(path)

        try:
            file_path = _resolve_file(path)
        except PermissionError:
            raise CognitsError("forbidden", "FORBIDDEN", 403)
        except FileNotFoundError:
            raise NotFoundError("file not found")
        except IsADirectoryError:
            raise ConfigError("not a file")

        mime, _ = mimetypes.guess_type(str(file_path))
        content_type = mime or "application/octet-stream"

        # Inline display for common types
        if content_type.startswith("text/"):
            content_type += "; charset=utf-8"

        return StreamingResponse(
            file_path.open("rb"),
            media_type=content_type,
            headers={
                "Content-Disposition": f'inline; filename="{file_path.name}"',
            },
        )
