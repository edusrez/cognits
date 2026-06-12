"""Markdown chunker tests (parity with internal/rag/chunker.go)."""

from cognits.rag.chunker import CHUNK_SIZE, split_markdown, split_paragraphs


def test_split_paragraphs_basic():
    md = "uno\ndos\n\ntres\n\n\ncuatro"
    assert split_paragraphs(md) == ["uno\ndos", "tres", "cuatro"]


def test_split_paragraphs_fence_atomic():
    md = "intro\n\n```python\na = 1\n\nb = 2\n```\n\nfinal"
    paragraphs = split_paragraphs(md)
    assert paragraphs == ["intro", "```python\na = 1\n\nb = 2\n```", "final"]


def test_split_paragraphs_fence_without_blank_lines():
    md = "text\n```go\nx := 1\n```\nmore text"
    paragraphs = split_paragraphs(md)
    assert "```go\nx := 1\n```" in paragraphs
    assert "text" in paragraphs
    assert "more text" in paragraphs


def test_split_markdown_ids_y_metadata():
    md = "# Title\n\n" + "\n\n".join(f"paragraph {i} " + "x" * 300 for i in range(12))
    chunks = split_markdown(md, "r_abc", "Tema")
    assert len(chunks) > 1
    for i, c in enumerate(chunks):
        assert c["id"] == f"r_abc_c{i}"
        assert c["report_id"] == "r_abc"
        assert c["source_type"] == "web"
        assert c["chunk_index"] == i
        assert c["topic"] == "Tema"


def test_split_markdown_respects_chunk_size():
    md = "\n\n".join("p" * 400 for _ in range(20))
    chunks = split_markdown(md, "r", "t")
    # Each chunk may overshoot on a paragraph (cut when exceeded), but
    # never by more than one entire paragraph.
    for c in chunks:
        assert len(c["text"]) <= CHUNK_SIZE + 400 + 2


def test_split_markdown_overlap():
    paragraphs = [f"unique paragraph {i} " + "y" * 200 for i in range(20)]
    chunks = split_markdown("\n\n".join(paragraphs), "r", "t")
    assert len(chunks) >= 2
    # The last piece of chunk N reappears at the start of N+1 (overlap).
    first_tail = chunks[0]["text"].split("\n\n")[-1]
    assert chunks[1]["text"].startswith(first_tail)


def test_split_markdown_empty():
    assert split_markdown("", "r", "t") == []
    assert split_markdown("   \n\n  ", "r", "t") == []
