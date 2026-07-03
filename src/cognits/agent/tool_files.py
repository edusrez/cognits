"""File-reading tools for the directory_reader subagent."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
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

        if await asyncio.to_thread(_is_binary, file_path):
            return tool_error(f"{rel_path}: binary file (cannot read as text)")

        size = file_path.stat().st_size
        truncated = size > MAX_TEXT_BYTES

        try:
            raw = await asyncio.to_thread(file_path.read_bytes)
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


def _list_dir_sync(dir_path):
    entries = sorted(
        os.scandir(dir_path),
        key=lambda e: (not e.is_dir(follow_symlinks=False), e.name.lower()),
    )
    items = []
    for entry in entries:
        item = {"name": entry.name, "is_dir": entry.is_dir(follow_symlinks=False)}
        try:
            if not entry.is_dir(follow_symlinks=False):
                item["size"] = entry.stat(follow_symlinks=False).st_size
        except OSError:
            pass
        items.append(item)
    return items


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

        items = await asyncio.to_thread(_list_dir_sync, dir_path)
        return json.dumps(
            {"path": str(dir_path), "entries": items},
            ensure_ascii=False,
        )


SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist",
             "build", ".cognits", ".learnit", "chroma_db", ".mypy_cache",
             ".pytest_cache", ".ruff_cache"}



def _grep_files_sync(dir_path, pattern, regex, max_results, max_chars, case_sensitive, context_lines):
    """Sync helper: search files recursively. Called via asyncio.to_thread."""
    import fnmatch
    results = []
    for root, dirs, files in os.walk(str(dir_path)):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for fn in sorted(files):
            fpath = Path(root) / fn
            if _is_binary(fpath):
                continue
            try:
                text = fpath.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            lines = text.split("\n")
            for i, line in enumerate(lines, 1):
                # simple string or regex matching
                match = False
                if regex:
                    try:
                        if re.search(pattern, line, 0 if case_sensitive else re.IGNORECASE):
                            match = True
                    except re.error:
                        pass
                else:
                    check = line if case_sensitive else line.lower()
                    if pattern.lower() if not case_sensitive else pattern in check:
                        match = True
                if match:
                    disp = line[:max_chars]
                    if len(line) > max_chars:
                        disp += "..."
                    results.append({"file": str(fpath.relative_to(dir_path)), "line": i, "text": disp})
            if len(results) >= max_results:
                break
        if len(results) >= max_results:
            break
    return results[:max_results]

class GrepCode(Tool):
    name = "grep_code"
    description = (
        "Search file contents with a regex pattern. Returns matches grouped "
        "by file with line numbers. Skips binary files and common non-source "
        "directories (.git, node_modules, etc.). Use this to find code "
        "patterns, function definitions, imports, or any text in the project."
    )
    schema = {
        "type": "object",
        "properties": {
            "pattern": {
                "type": "string",
                "description": "Regex pattern to search for (Python re syntax).",
            },
            "path": {
                "type": "string",
                "description": "Directory to search in, relative to project root. Defaults to '.' (entire project).",
            },
            "include": {
                "type": "string",
                "description": "Glob pattern to filter files (e.g. '*.py', '*.{ts,tsx}'). If omitted, searches all text files.",
            },
            "max_results": {
                "type": "integer",
                "description": "Maximum number of matching lines to return (default 50, max 100).",
            },
        },
        "required": ["pattern"],
    }

    async def execute(self, raw_args: str) -> str:
        try:
            args = json.loads(raw_args)
            pattern = args["pattern"]
            rel_path = args.get("path") or "."
            include = args.get("include") or ""
            max_results = int(args.get("max_results") or 0)
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as e:
            return tool_error(f"invalid args: {e}")

        if max_results <= 0:
            max_results = 50
        max_results = min(max_results, 100)

        try:
            dir_path = _resolve_dir(rel_path)
        except (PermissionError, FileNotFoundError, NotADirectoryError) as e:
            return tool_error(str(e))

        try:
            compiled = re.compile(pattern)
        except re.error as e:
            return tool_error(f"invalid regex: {e}")

        results: list[dict] = []
        total = 0

        try:
            for root, dirs, files in os.walk(str(dir_path)):
                dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith(".")]

                for fname in sorted(files):
                    if include and not Path(fname).match(include):
                        continue

                    fpath = os.path.join(root, fname)
                    if _is_binary(Path(fpath)):
                        continue

                    try:
                        size = os.path.getsize(fpath)
                    except OSError:
                        continue
                    if size > MAX_TEXT_BYTES:
                        continue

                    try:
                        text = Path(fpath).read_text(encoding="utf-8", errors="replace")
                    except OSError:
                        continue

                    file_matches = []
                    for lineno, line in enumerate(text.split("\n"), start=1):
                        match = compiled.search(line)
                        if match:
                            display = line[:300]
                            if len(line) > 300:
                                display += "..."
                            file_matches.append({"line": lineno, "text": display})
                            total += 1
                            if total >= max_results:
                                break

                    if file_matches:
                        rel = os.path.relpath(fpath, dir_path)
                        results.append({"file": rel, "matches": file_matches})

                    if total >= max_results:
                        break

                if total >= max_results:
                    break
        except OSError as e:
            return tool_error(str(e))

        return json.dumps(
            {
                "pattern": pattern,
                "directory": str(dir_path),
                "total_matches": total,
                "truncated": total >= max_results,
                "files": results,
            },
            ensure_ascii=False,
        )


class GlobFiles(Tool):
    name = "glob_files"
    description = (
        "Find files matching a glob pattern. Searches recursively starting "
        "from the given directory. Returns sorted file paths. Skips common "
        "non-source directories (.git, node_modules, etc.)."
    )
    schema = {
        "type": "object",
        "properties": {
            "pattern": {
                "type": "string",
                "description": "Glob pattern (e.g. '*.py', '**/*.tsx', 'src/**/*.go').",
            },
            "path": {
                "type": "string",
                "description": "Directory to search from, relative to project root. Defaults to '.' (entire project).",
            },
        },
        "required": ["pattern"],
    }

    async def execute(self, raw_args: str) -> str:
        try:
            args = json.loads(raw_args)
            pattern = args["pattern"]
            rel_path = args.get("path") or "."
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            return tool_error(f"invalid args: {e}")

        try:
            dir_path = _resolve_dir(rel_path)
        except (PermissionError, FileNotFoundError, NotADirectoryError) as e:
            return tool_error(str(e))

        results: list[str] = []
        try:
            for root, dirs, files in os.walk(str(dir_path)):
                dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith(".")]

                for fname in files:
                    full = os.path.join(root, fname)
                    if Path(fname).match(pattern):
                        results.append(os.path.relpath(full, dir_path))

                    if len(results) >= 200:
                        break

                if len(results) >= 200:
                    break
        except OSError as e:
            return tool_error(str(e))

        return json.dumps(
            {
                "pattern": pattern,
                "directory": str(dir_path),
                "count": len(results),
                "truncated": len(results) >= 200,
                "files": results,
            },
            ensure_ascii=False,
        )


async def _pdf_to_markdown_in_thread(file_path, docling_engine, docling_config) -> str:
    import asyncio
    return await asyncio.to_thread(_pdf_to_markdown, file_path, docling_engine, docling_config)
