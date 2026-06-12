# Cognits

**C**ontext-**O**riented **G**eneration for **N**eural **I**ntelligent **T**utoring **S**ystems.

Multi-agent AI personal tutor: a Socratic orchestrator coordinates subagents
(documentalist with local RAG, web researcher) to guide your learning from a
local web interface, anchored to the project folder you're learning about.

## Installation

```bash
uv tool install cognits
```

> The installation includes the local RAG engine (onnxruntime + ChromaDB, ~600 MB).
> On first launch, the BGE-M3 embeddings model is downloaded (~2.3 GB).

## Usage

```bash
cd my-learning-project
cognits
```

Starts a local server (port 5173 by default, `PORT` env var) and opens the
interface in your browser. State lives in `./.cognits/` (sessions, reports,
encrypted configuration, RAG index).

## Development

```bash
scripts/dev.sh    # Vite (HMR) + uvicorn --reload
scripts/build.sh  # frontend build + wheel
uv run pytest
```

The frontend is a SolidJS SPA in `frontend/`; the backend is Python (FastAPI)
in `src/cognits/`.
