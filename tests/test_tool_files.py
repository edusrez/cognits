"""Tests for agent/tool_files.py: ReadFile, ListDir, GrepCode, GlobFiles."""

import asyncio
import json

import pytest

from cognits.agent.tool_files import GlobFiles, GrepCode, ListDir, ReadFile


def test_read_file_text(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    p = tmp_path / "hello.txt"
    p.write_text("line one\nline two\nline three")
    tool = ReadFile()
    result = asyncio.run(tool.execute(json.dumps(
        {"path": str(p.relative_to(tmp_path))})))
    data = json.loads(result)
    assert "line one" in data["content"]
    assert data["total_lines"] == 3


def test_read_file_binary(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    p = tmp_path / "img.bin"
    p.write_bytes(b"\x00\x01\x02\x03\x04")
    tool = ReadFile()
    result = asyncio.run(tool.execute(json.dumps(
        {"path": str(p.relative_to(tmp_path))})))
    assert "error" in json.loads(result)


def test_read_file_missing_path():
    tool = ReadFile()
    result = asyncio.run(tool.execute(json.dumps({"not_path": "x"})))
    assert "error" in json.loads(result)


def test_read_file_offset(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    p = tmp_path / "lines.txt"
    p.write_text("1\n2\n3\n4\n5\n6\n7\n8\n9\n10")
    tool = ReadFile()
    result = asyncio.run(tool.execute(json.dumps(
        {"path": str(p.relative_to(tmp_path)), "offset": 5, "limit": 2})))
    data = json.loads(result)
    assert "5" in data["content"]
    assert data["total_lines"] == 10


def test_list_dir(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "a.txt").write_text("")
    (tmp_path / "sub").mkdir()
    result = asyncio.run(ListDir().execute(json.dumps({"path": "."})))
    data = json.loads(result)
    names = [e["name"] for e in data["entries"]]
    assert "sub" in names
    assert "a.txt" in names


def test_grep_code(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    p = tmp_path / "greptest.py"
    p.write_text("def foo():\n    return 42\n# hello world\n")
    result = asyncio.run(GrepCode().execute(json.dumps(
        {"pattern": "hello", "path": str(p.parent.relative_to(tmp_path))})))
    data = json.loads(result)
    assert data["total_matches"] >= 1


def test_glob_files(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "a.py").write_text("x")
    (tmp_path / "b.txt").write_text("y")
    result = asyncio.run(GlobFiles().execute(json.dumps(
        {"pattern": "*.py", "path": str(tmp_path)})))
    data = json.loads(result)
    assert data["count"] >= 1
