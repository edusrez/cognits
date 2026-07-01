# Cognits

**C**ontext-**O**riented **G**eneration for **N**eural **I**ntelligent **T**utoring **S**ystems.

Multi-agent AI personal tutor: a Socratic orchestrator coordinates subagents
(documentalist with local RAG, web researcher) to guide your learning from a
local web interface, anchored to the project folder you're learning about.

## Installation

Requires **Python 3.12** (ChromaDB is not yet compatible with 3.13).

### macOS / Linux / Windows (WSL2)

```bash
# Install uv (if you don't have it)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Install Cognits
uv tool install cognits
```

For Windows users, **WSL2** is the recommended environment. Native Windows
support is limited (the TUI framework requires a modern terminal, and the
ONNX Runtime has known instability outside WSL).

### macOS Intel note

`onnxruntime` 1.27 does not ship a wheel for macOS x86_64. If `uv tool install`
fails on an Intel Mac, install onnxruntime separately via conda-forge first,
then retry:

```bash
conda install -c conda-forge onnxruntime
uv tool install cognits
```

### Disable RAG (faster startup, smaller footprint)

Set `COGNITS_DISABLE_RAG=1` to skip loading the BGE-M3 embedding model
(~2.3 GB download). RAG-dependent features (knowledge base search) will
be unavailable but the tutor still works.

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
