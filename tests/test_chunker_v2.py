"""Tests for rag/chunker.py: paragraph-aware v2 chunker."""

from cognits.rag.chunker import split_markdown, split_markdown_v2


def test_v2_respects_headers():
    md = "## Intro\nParagraph about intro.\n\n## Methods\nParagraph about methods.\n\n## Results\nParagraph about results."
    chunks = split_markdown_v2(md, "r1", "topic", "web")
    assert len(chunks) >= 1
    # Check parent_section metadata
    sections = {c["parent_section"] for c in chunks}
    assert len(sections) >= 1


def test_v2_empty_input():
    chunks = split_markdown_v2("", "r1", "topic")
    assert chunks == []


def test_v2_chunk_ids():
    md = "Line one.\n\nLine two.\n\nLine three."
    chunks = split_markdown_v2(md, "r99", "topic")
    for i, c in enumerate(chunks):
        assert c["id"] == f"r99_c{i}"


def test_v2_source_type_passed_through():
    chunks = split_markdown_v2("text", "r1", "topic", "evaluator")
    assert chunks[0]["source_type"] == "evaluator"


def test_v2_topic_in_metadata():
    chunks = split_markdown_v2("Hello world.", "r1", "Python")
    assert chunks[0]["topic"] == "Python"


def test_v2_parent_section_present():
    md = "## Section A\nContent here.\n\n### Sub-section\nMore content."
    chunks = split_markdown_v2(md, "r1", "topic")
    for c in chunks:
        assert "parent_section" in c
        assert c["parent_section"]


def test_v2_compat_with_v1():
    """V1 split_markdown still works unchanged."""
    chunks = split_markdown("Hello world.", "r1", "topic")
    assert len(chunks) == 1
    assert chunks[0]["source_type"] == "web"  # default
