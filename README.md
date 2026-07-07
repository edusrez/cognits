# Cognits

**C**ontext-**O**riented **G**uidance and **N**eural **I**ntelligent **T**utoring **S**ystem.

Cognits is a multi-agent learning system. It anchors itself to your project
folder — whether you're building a game, creating a web app, learning a new
language, studying a university subject, or even working on Cognits itself —
and orchestrates specialized subagents that research your domain, build a
skill tree, and guide you through Socratic learning sessions.

## How it works

1. **Onboarding interview** — Cognits interviews you to understand your
   background, project, experience, and learning preferences. It builds a
   skill tree of prerequisites automatically, researching your domain on the
   web in parallel.

2. **Learning sessions** — A Socratic Teacher agent guides you through one
   skill at a time: concepts, hands-on exercises, exploration, and assessment.
   It adapts to your responses in real time, asking you to predict, reflect,
   and articulate what you've learned.

3. **Assessment & mastery tracking** — An independent Evaluator agent
   asynchronously reviews the teacher's responses after each turn, updates
   your mastery level per skill (BKT + FSRS), and flags Socratic violations
   for the next session — without interrupting the conversation flow.

4. **Session analysis** — After each session, an analyzer reviews the full
   transcript and updates your learner profile — inferred preferences,
   difficulties, effective analogies — so future sessions are personalized.

## Architecture

Cognits is a multi-agent system with a local web interface:

- **Orchestrator** — plans your learning path, coordinates subagents
- **Teacher (Maestro)** — Socratic tutor for guided learning sessions
- **Evaluator** — independent examiner with rubric-based grading
- **Skill Planner** — auto-generates a skill tree from your domain
- **Study Planner** — creates stage-based pedagogical plans per skill
- **Documentalist** — searches an internal knowledge base (local RAG)
- **Web Researcher** — fetches up-to-date information from the web
- **Session Analyzer** — post-session profile learning

All data stays local: sessions, reports, skill tree, learner state, and
RAG index live in `./.cognits/` inside your project folder. API keys are
encrypted at rest. No data is sent anywhere except the LLM API you configure.

## Installation

Requires **Python 3.11–3.13**.

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

### WSL2 note

On WSL2 with the project folder on a Windows drive (`/mnt/c/...`), Cognits
automatically detects the 9p/DrvFs filesystem and:
- Uses `journal_mode=MEMORY` for SQLite (WAL and DELETE are unreliable on 9p).
- Redirects the RAG model cache to `/tmp/fastembed_cache` (ONNX Runtime
  can't mmap model files from 9p).

No manual configuration needed. The first launch still downloads BGE-M3
(~2.3 GB) to `/tmp`; on WSL restart the download repeats (tmpfs is
RAM-backed). For persistence across WSL restarts, set
`FASTEMBED_CACHE_DIR` to a path on the WSL ext4 filesystem (e.g.
`~/.local/share/fastembed`).

### Disable RAG (faster startup, smaller footprint)

Set `COGNITS_DISABLE_RAG=1` to skip loading the BGE-M3 embedding model
(~2.3 GB download). RAG-dependent features (knowledge base search) will
be unavailable but the tutor still works.

> The installation includes the local RAG engine (onnxruntime + sqlite-vec, ~600 MB).
> On first launch, the BGE-M3 embeddings model is downloaded (~2.3 GB).

### Environment variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `PORT` | `5173` | Server port |
| `COGNITS_HOST` | `127.0.0.1` | Bind address |
| `ENV` | — | `dev` proxies to Vite (HMR) |
| `COGNITS_DISABLE_RAG` | — | `1` skips BGE-M3 model load |
| `COGNITS_JOURNAL_MODE` | auto | `wal`/`delete`/`truncate`/`persist`/`memory` |
| `FASTEMBED_CACHE_DIR` | `~/.cache/fastembed` | RAG model cache path |

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
