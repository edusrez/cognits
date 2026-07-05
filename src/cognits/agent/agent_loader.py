"""Load agent definitions from Markdown files with YAML frontmatter.

Each agent is a .md file in agent/agents/{name}.md with:
  --- (YAML frontmatter: name, model, reasoning, max_steps, etc.)
  ---
  (Markdown body: system prompt)

The file name (without .md) becomes the agent name.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from cognits.agent.agent import AgentConfig
from cognits.constants import parse_model

AGENTS_DIR = Path(__file__).parent / "agents"


def _parse_frontmatter(path: Path) -> tuple[dict, str]:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        raise ValueError(f"No YAML frontmatter in {path}")

    parts = text.split("---", 2)
    if len(parts) < 3:
        raise ValueError(f"Malformed frontmatter in {path}")

    fm = yaml.safe_load(parts[1]) or {}
    body = parts[2].strip()
    return fm, body


def load_agent_config(name: str) -> AgentConfig:
    path = AGENTS_DIR / f"{name}.md"
    if not path.exists():
        raise FileNotFoundError(f"Agent file not found: {path}")

    fm, prompt = _parse_frontmatter(path)

    raw_model = fm.get("model", "")
    _, model_id = parse_model(raw_model) if raw_model else ("", "")

    return AgentConfig(
        name=fm.get("name", name),
        model=model_id,
        reasoning=fm.get("reasoning", "") or "",
        max_steps=fm.get("max_steps", 0),
        system_prompt=prompt,
        max_tokens=fm.get("max_tokens"),
        temperature=fm.get("temperature"),
        top_p=fm.get("top_p"),
        critique_mode=fm.get("critique_mode", False),
        tool_registry=fm.get("tool_registry", ""),
        tools=None,
        subagents={},
    )


def load_agent_prompt(name: str) -> str:
    path = AGENTS_DIR / f"{name}.md"
    if not path.exists():
        raise FileNotFoundError(f"Agent file not found: {path}")
    _, prompt = _parse_frontmatter(path)
    return prompt
