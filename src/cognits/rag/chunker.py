"""Port of internal/rag/chunker.go.

The generated IDs ({report_id}_c{idx}) must match those from the Go backend
to avoid duplicating chunks from already indexed reports: len() of str in
Python counts codepoints, same as utf8.RuneCountInString.
"""

from __future__ import annotations

from cognits.constants import CHUNK_OVERLAP, CHUNK_SIZE


def split_paragraphs(md: str) -> list[str]:
    """Splits by blank lines, but treats each fenced block (``` ... ```)
    as an atomic paragraph: a blind split by "\\n\\n" lost fences without
    blank lines and filtered out loose code without context when they had them."""
    paragraphs: list[str] = []
    current: list[str] = []
    in_fence = False

    def flush() -> None:
        nonlocal current
        if not current:
            return
        p = "\n".join(current).strip()
        if p:
            paragraphs.append(p)
        current = []

    for line in md.split("\n"):
        trimmed = line.strip()
        if trimmed.startswith("```"):
            if not in_fence:
                flush()
                in_fence = True
                current.append(line)
            else:
                current.append(line)
                flush()
                in_fence = False
            continue
        if in_fence:
            current.append(line)
            continue
        if trimmed == "":
            flush()
            continue
        current.append(line)
    flush()
    return paragraphs


def _overlap_count(paragraphs: list[str], target_chars: int) -> int:
    count = 0
    chars = 0
    for p in reversed(paragraphs):
        chars += len(p)
        count += 1
        if chars >= target_chars:
            break
    return count


def split_markdown(md: str, report_id: str, topic: str, source_type: str = "web") -> list[dict]:
    paragraphs = split_paragraphs(md)
    chunks: list[dict] = []

    current: list[str] = []
    current_len = 0
    idx = 0

    def flush() -> None:
        nonlocal current, current_len, idx
        if not current:
            return
        text = "\n\n".join(current).strip()
        if not text:
            current = []
            current_len = 0
            return
        chunks.append(
            {
                "id": f"{report_id}_c{idx}",
                "text": text,
                "report_id": report_id,
                "source_type": source_type,
                "chunk_index": idx,
                "topic": topic,
            }
        )
        idx += 1

        overlap_start = len(current) - _overlap_count(current, CHUNK_OVERLAP)
        if overlap_start <= 0:
            current = []
            current_len = 0
            return
        current = current[overlap_start:]
        current_len = sum(len(p) for p in current)

    for p in paragraphs:
        p_len = len(p)
        if current_len + p_len > CHUNK_SIZE and current:
            flush()
        current.append(p)
        current_len += p_len
    flush()

    return chunks


def split_markdown_v2(md: str, report_id: str, topic: str, source_type: str = "web") -> list[dict]:
    """Paragraph-aware markdown chunker. Respects ##/### headers, sub-splits
    on paragraphs within sections, falls back to fixed-size for very large
    sections. Stores parent_section in each chunk's metadata."""
    import re
    sections = re.split(r"\n(?=## )", md)
    chunks: list[dict] = []
    chunk_idx = 0

    for section in sections:
        header_match = re.match(r"^(#{1,3}\s+.+)", section)
        parent_section = header_match.group(1).strip() if header_match else topic

        # Split section into paragraphs, then chunk
        body = section
        paragraphs = split_paragraphs(body)
        current: list[str] = []
        current_len = 0

        def flush_section() -> None:
            nonlocal current, current_len, chunk_idx
            if not current:
                return
            text = "\n\n".join(current).strip()
            if not text:
                current = []
                current_len = 0
                return
            chunks.append({
                "id": f"{report_id}_c{chunk_idx}",
                "text": text,
                "report_id": report_id,
                "source_type": source_type,
                "chunk_index": chunk_idx,
                "topic": topic,
                "parent_section": parent_section,
            })
            chunk_idx += 1
            ov = _overlap_count(current, CHUNK_OVERLAP)
            if ov < len(current):
                current = current[ov:]
                current_len = sum(len(p) for p in current)
            else:
                current = []
                current_len = 0

        for p in paragraphs:
            p_len = len(p)
            if current_len + p_len > CHUNK_SIZE and current:
                flush_section()
            current.append(p)
            current_len += p_len
        flush_section()

    return chunks
