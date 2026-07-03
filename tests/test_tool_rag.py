"""Tests for agent/tool_rag.py: RagSearch tool."""

import asyncio
import json

import pytest

from cognits.agent.tool_rag import RagSearch


class FakeRag:
    def __init__(self, results=None, should_fail=False):
        self.results = results or []
        self.should_fail = should_fail

    async def search(self, query: str, n: int = 5):
        if self.should_fail:
            raise RuntimeError("engine down")
        return self.results[:n]


def test_rag_search_happy_path():
    rag = FakeRag(results=[
        {"text": "answer", "report_id": "r1", "source_type": "web",
         "topic": "x", "distance": 0.2},
    ])
    tool = RagSearch(rag)
    result = asyncio.run(tool.execute(json.dumps({"query": "test", "max_results": 3})))
    data = json.loads(result)
    assert data["found"] is True
    assert len(data["results"]) == 1
    assert data["results"][0]["text"] == "answer"


def test_rag_search_empty():
    rag = FakeRag(results=[])
    tool = RagSearch(rag)
    result = asyncio.run(tool.execute(json.dumps({"query": "nothing"})))
    data = json.loads(result)
    assert data["found"] is False
    assert len(data["results"]) == 0


def test_rag_search_invalid_json():
    tool = RagSearch(FakeRag())
    result = asyncio.run(tool.execute("not json"))
    assert "error" in json.loads(result)


def test_rag_search_missing_query():
    tool = RagSearch(FakeRag())
    result = asyncio.run(tool.execute(json.dumps({"not_query": "x"})))
    assert "error" in json.loads(result)


def test_rag_search_engine_error():
    tool = RagSearch(FakeRag(should_fail=True))
    result = asyncio.run(tool.execute(json.dumps({"query": "test"})))
    data = json.loads(result)
    assert "error" in data
    assert "rag search" in data["error"].lower()
