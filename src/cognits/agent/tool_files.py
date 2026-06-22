"""File-reading tools for the directory_reader subagent."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from cognits.paths import data_dir
from cognits.tools import Tool, tool_error

MAX_TEXT_BYTES = 5 * 1024 * 1024
MAX_LINES_DEFAULT = 2000
MAX_CHARS_PER_LINE = 2000


def _resolve_path(rel_path: str) -> Path:
    cwd = Path.cwd().resolve()
    full = (cwd / rel_path).resolve()
    if not full.is_relative_to(cwd):
        raise PermissionError("path outside project directory")
    if not full.exists():
        raise FileNotFoundError(f"{rel_path}: file not found")
    if not full.is_file():
        raise IsADirectoryError(f"{rel_path}: not a file")
    return full


def _resolve_dir(rel_path: str) -> Path:
    cwd = Path.cwd().resolve()
    full = (cwd / rel_path).resolve()
    if not full.is_relative_to(cwd):
        raise PermissionError("path outside project directory")
    if not full.exists():
        raise FileNotFoundError(f"{rel_path}: directory not found")
    if not full.is_dir():
        raise NotADirectoryError(f"{rel_path}: not a directory")
    return full


def _pdf_to_markdown(file_path: Path, docling_engine, docling_config) -> str:
    cache_dir = data_dir() / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)

    key = hashlib.sha256(str(file_path.resolve()).encode()).hexdigest()
    cache_md = cache_dir / f"{key}.md"
    cache_mtime = cache_dir / f"{key}.mtime"

    current_mtime = file_path.stat().st_mtime

    if cache_md.exists() and cache_mtime.exists():
        try:
            cached = float(cache_mtime.read_text().strip())
            if cached == current_mtime:
                return cache_md.read_text(encoding="utf-8")
        except (ValueError, OSError):
            pass

    converter = docling_engine.converter
    result = converter.convert(str(file_path))
    content = result.document.export_to_markdown() or ""

    cache_md.write_text(content, encoding="utf-8")
    cache_mtime.write_text(str(current_mtime))

    return content


def _is_binary(file_path: Path) -> bool:
    try:
        chunk = file_path.open("rb").read(8192)
    except OSError:
        return True
    return b"\x00" in chunk


class ReadFile(Tool):
    def __init__(self, docling_engine=None, docling_config=None):
        self.docling_engine = docling_engine
        self.docling_config = docling_config

    name = "read_file"
    description = (
        "Read a file from the project directory. Returns the content with "
        "line numbers (format: '<line>: <content>'). Use offset and limit "
        "to read large files in chunks. PDF files are automatically converted "
        "to markdown. Binary files are rejected."
    )
    schema = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Path to the file, relative to the project root directory.",
            },
            "offset": {
                "type": "integer",
                "description": "Line number to start reading from (1-indexed). Defaults to 1.",
            },
            "limit": {
                "type": "integer",
                "description": f"Maximum number of lines to return (default {MAX_LINES_DEFAULT}, max {MAX_LINES_DEFAULT}).",
            },
        },
        "required": ["path"],
    }

    async def execute(self, raw_args: str) -> str:
        try:
            args = json.loads(raw_args)
            rel_path = args["path"]
            offset = max(1, int(args.get("offset") or 1))
            limit = int(args.get("limit") or 0)
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as e:
            return tool_error(f"invalid args: {e}")

        if limit <= 0:
            limit = MAX_LINES_DEFAULT
        limit = min(limit, MAX_LINES_DEFAULT)

        try:
            file_path = _resolve_path(rel_path)
        except (PermissionError, FileNotFoundError, IsADirectoryError) as e:
            return tool_error(str(e))

        ext = file_path.suffix.lower()

        if ext == ".pdf":
            if self.docling_engine is None or self.docling_engine.error:
                return tool_error("PDF reading not available (Docling not loaded)")
            try:
                content = await _pdf_to_markdown_in_thread(
                    file_path, self.docling_engine, self.docling_config
                )
            except Exception as e:
                return tool_error(f"PDF conversion failed: {e}")
            return json.dumps({"path": str(file_path), "content": content}, ensure_ascii=False)

        if _is_binary(file_path):
            return tool_error(f"{rel_path}: binary file (cannot read as text)")

        size = file_path.stat().st_size
        truncated = size > MAX_TEXT_BYTES

        try:
            raw = file_path.read_bytes()
        except OSError as e:
            return tool_error(str(e))

        if truncated:
            raw = raw[:MAX_TEXT_BYTES]

        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            try:
                text = raw.decode("latin-1", errors="replace")
            except Exception:
                text = raw.decode("utf-8", errors="replace")

        lines = text.split("\n")
        total_lines = len(lines)

        if offset > total_lines:
            return tool_error(
                f"offset {offset} exceeds file length of {total_lines} lines"
            )

        end = min(offset + limit - 1, total_lines)
        selected = lines[offset - 1 : end]

        out_lines = []
        for i, line in enumerate(selected, start=offset):
            display = line[:MAX_CHARS_PER_LINE]
            if len(line) > MAX_CHARS_PER_LINE:
                display += "..."
            out_lines.append(f"{i}: {display}")

        result = "\n".join(out_lines)
        if truncated and end == total_lines:
            result += "\n\n[File truncated at 5 MB]"

        return json.dumps(
            {
                "path": str(file_path),
                "total_lines": total_lines,
                "offset": offset,
                "limit": limit,
                "content": result,
            },
            ensure_ascii=False,
        )


class ListDir(Tool):
    name = "list_dir"
    description = (
        "List files and subdirectories in a project directory. "
        "Returns entries sorted with directories first, then alphabetically."
    )
    schema = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Directory path relative to the project root. Defaults to '.' (project root).",
            },
        },
    }

    async def execute(self, raw_args: str) -> str:
        try:
            args = json.loads(raw_args)
            rel_path = args.get("path") or "."
        except (json.JSONDecodeError, TypeError) as e:
            return tool_error(f"invalid args: {e}")

        try:
            dir_path = _resolve_dir(rel_path)
        except (PermissionError, FileNotFoundError, NotADirectoryError) as e:
            return tool_error(str(e))

        try:
            entries = sorted(
                os.scandir(dir_path),
                key=lambda e: (not e.is_dir(follow_symlinks=False), e.name.lower()),
            )
        except OSError as e:
            return tool_error(str(e))

        items = []
        for entry in entries:
            item: dict = {
                "name": entry.name,
                "is_dir": entry.is_dir(follow_symlinks=False),
            }
            try:
                if not entry.is_dir(follow_symlinks=False):
                    item["size"] = entry.stat(follow_symlinks=False).st_size
            except OSError:
                pass
            items.append(item)

        return json.dumps(
            {"path": str(dir_path), "entries": items},
            ensure_ascii=False,
        )


async def _pdf_to_markdown_in_thread(file_path, docling_engine, docling_config) -> str:
    import asyncio
    return await asyncio.to_thread(_pdf_to_markdown, file_path, docling_engine, docling_config)
