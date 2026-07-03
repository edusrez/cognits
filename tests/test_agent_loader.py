"""Tests for agent/agent_loader.py: YAML frontmatter parsing."""

import pytest

from cognits.agent.agent_loader import (
    AGENTS_DIR,
    _parse_frontmatter,
    load_agent_config,
    load_agent_prompt,
)


def test_parse_frontmatter_valid():
    fm, body = _parse_frontmatter(AGENTS_DIR / "web_researcher.md")
    assert fm["name"] == "web_researcher"
    assert "model" in fm
    assert isinstance(body, str)
    assert len(body) > 100


def test_load_agent_config():
    cfg = load_agent_config("web_researcher")
    assert cfg.name == "web_researcher"
    assert "deepseek-v4-pro" in cfg.model
    assert cfg.max_steps == 50
    assert len(cfg.system_prompt) > 100


def test_load_agent_prompt():
    prompt = load_agent_prompt("web_researcher")
    assert "Web Researcher" in prompt
    assert "research" in prompt.lower()


def test_all_nine_agents_load():
    for name in [
        "web_researcher", "documentalist", "directory_reader",
        "session_namer", "session_analyzer", "skill_planner",
        "study_planner", "evaluator", "maestro",
    ]:
        cfg = load_agent_config(name)
        assert cfg.name == name
        assert cfg.system_prompt, f"{name}: empty prompt"


def test_missing_file():
    with pytest.raises(FileNotFoundError):
        load_agent_config("nonexistent_agent")


def test_no_frontmatter(tmp_path):
    p = tmp_path / "no_fm.md"
    p.write_text("Just a body without frontmatter")
    with pytest.raises(ValueError, match="No YAML"):
        _parse_frontmatter(p)


def test_malformed_frontmatter(tmp_path):
    p = tmp_path / "bad.md"
    p.write_text("---\nname: x\n---\nbody")
    fm, body = _parse_frontmatter(p)
    assert fm["name"] == "x"
    assert body == "body"


def test_empty_frontmatter_defaults(tmp_path):
    p = tmp_path / "empty.md"
    p.write_text("---\n---\njust a body")
    fm, body = _parse_frontmatter(p)
    assert fm == {}
    assert body == "just a body"
