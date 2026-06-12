"""Port de internal/rag/chunker.go.

Los IDs generados ({report_id}_c{idx}) deben coincidir con los del backend Go
para no duplicar chunks de informes ya indexados: len() de str en Python
cuenta codepoints, igual que utf8.RuneCountInString.
"""

from __future__ import annotations

CHUNK_SIZE = 1600
CHUNK_OVERLAP = 160


def split_paragraphs(md: str) -> list[str]:
    """Separa por líneas en blanco, pero trata cada bloque fenced (``` ... ```)
    como un párrafo atómico: el split ciego por "\\n\\n" perdía los fences sin
    líneas en blanco y filtraba código suelto sin contexto cuando las tenían."""
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


def split_markdown(md: str, report_id: str, topic: str) -> list[dict]:
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
                "source_type": "web",
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
