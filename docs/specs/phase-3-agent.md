# Phase 3 — Agent core and orchestration

**Version:** 0.0.7  
**Date:** 2026-07-04  
**Status:** in-progress  
**Decisions locked:** Markdown+YAML agent format, reflection loop included, full test coverage

## Current state

`agent/subagents.py` is 1361 lines with 9 config builder functions and ~1000
lines of inline system prompt strings. 8 `getattr` compat shims bridge
`LegacyStore` (used by 7 test files) vs real repos. Blocking I/O on the event
loop in `tool_ui.py` and `tool_files.py`. Many hardcoded values (LLM timeouts,
max_steps defaults, truncation limits). No observability or context compaction.

## Design

### Agent file format: Markdown + YAML frontmatter

Each agent gets one file: `src/cognits/agent/agents/{name}.md`

```markdown
---
name: web_researcher
description: Autonomous web researcher. Searches the web and internal KB.
model: deepseek/deepseek-v4-pro
reasoning: enabled
max_steps: 50
temperature: 0.0
tool_registry: researcher
---
# Web Researcher — Cognits Subagent

You are an autonomous web researcher within Cognits...
```

This aligns with the ecosystem standard (OpenCode CLI, Claude Code, Anthropic
Skills). YAML frontmatter holds config; Markdown body is the system prompt.

### agent_loader.py

```python
def load_agent_config(name: str) -> AgentConfig:
    """Read {name}.md, parse YAML frontmatter, return AgentConfig."""
    fm, prompt = _parse_frontmatter(AGENTS_DIR / f"{name}.md")
    return AgentConfig(
        name=fm.get("name", name),
        model=fm.get("model", ""),
        reasoning=fm.get("reasoning", ""),
        max_steps=fm.get("max_steps", 0),
        system_prompt=prompt,
        tools=None,           # wired later by builder
        subagents={},         # wired later by builder
        max_tokens=fm.get("max_tokens"),
        temperature=fm.get("temperature"),
        top_p=fm.get("top_p"),
    )
```

### subagents.py refactored to ~150 lines

Each config builder calls `load_agent_config(name)` for the static config,
then wires runtime tools (SearchTool, RagSearch, etc.) with concrete clients.
The prompt text lives in the `.md` file, not in Python strings.

### Observability: JSONL traces

`agent/tracer.py` emits structured events to `.cognits/traces/{session_id}.jsonl`:
```json
{"ts":"...","span_id":"sp1","parent_id":"root","agent":"web_researcher",
 "event":"tool_call","tool":"search","duration_ms":1200,"ok":true}
```

Per-subagent token tracking via usage events from DeepSeek.

### Context compaction

When orchestrator context exceeds ~60% of the model's window (~40K tokens),
compaction triggers: preserve system prompt + last 3 turns + all tool
call/result pairs; compress older turns via an LLM summary call.

### Reflection loop

Teacher generates → evaluator critiques in `critique_mode` → teacher revises.
Cap 2 iterations. Triggered conditionally (learner confusion, high-stakes topics).

## Task breakdown

### T1 — Spec (this file)

### T2 — Extract prompts to agent/agents/*.md
- Create `agent/agents/` directory
- Create 9 `.md` files with YAML frontmatter + prompt body
- Create `agent/agent_loader.py` with `_parse_frontmatter`, `load_agent_config`
- Refactor `subagents.py`: each config builder calls `load_agent_config()`
- Remove inline prompt strings from `subagents.py`
- Add `pyyaml` to deps if not present

### T3 — Eliminate compat shims
- Migrate 7 test files from LegacyStore to real repos (conftest fixtures)
- Remove 8 `getattr` compat shims in production code
- Delete `tests/_legacy.py`

### T4 — Fix blocking I/O
- `tool_ui.py`: wrap `save_profile`/`load_profile` in `asyncio.to_thread`
- `tool_files.py`: wrap `read_bytes` in `asyncio.to_thread`

### T5 — Centralize hardcoded values
- Add to `constants.py`: `LLM_CONNECT_TIMEOUT`, `LLM_READ_TIMEOUT`, `LLM_WRITE_TIMEOUT`, `LLM_POOL_TIMEOUT`, `LLM_BASE_URL`, `DOCUMENTALIST_MAX_STEPS`, `EVALUATOR_MAX_STEPS`, `STUDY_PLANNER_DEFAULT_STEPS`, `MASTERY_THRESHOLD`
- Update: `deepseek.py`, `subagents.py`, `chat_service.py`, `tool_files.py`, `planner.py`, `model.py`

### T6 — De-homogenizations
- Remove 5 no-op emit wrappers in subagent configs
- Unify `DEFAULT_AGENTS[].name` with `AGENT_LABELS`
- Standardize tool constructor param names
- Create `server/dependencies.py` with `get_app_state` wrapper

### T7 — Resolve circular import
- Move `_run_session_namer` from `routes_chat.py` to `chat_service.py`

### T8 — Observability (JSONL traces)
- Create `agent/tracer.py`
- Integrate in `agent.py` loop + `chat_service.py`

### T9 — Context compaction
- Add compaction logic to `chat_service.py` before building `llm_messages`
- Trigger at 60% context window (~40K tokens)

### T10 — Reflection loop
- Add `critique_mode` to evaluator frontmatter
- Add reflection logic to `chat_service.py` (generate→critique→revise)

### T11 — Tests
- `test_chat_service.py`, `test_exceptions.py`, `test_agent_loader.py`
- `test_tool_rag.py`, `test_tool_files.py`, `test_deepseek.py`

### T12 — AGENTS.md update
