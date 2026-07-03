"""Tests for the Evaluator subagent: update_mastery tool, prompt checks,
static wiring, and resume_token in DeploySubagent."""

import asyncio
import json

import pytest

from cognits.learner import record_review
from _legacy import LegacyStore
from cognits.storage.models import LearnerState, Skill, new_skill_id
from cognits.tools import Registry


# --- helpers ---------------------------------------------------------

def _skill(name="Test", domain="d"):
    return Skill(id=new_skill_id(), domain=domain, name=name, source="test")


@pytest.fixture
def store(tmp_path):
    rs = LegacyStore(tmp_path / "test.db")
    yield rs
    rs.close()


# --- update_mastery tool ---------------------------------------------

def test_update_mastery_first_review(store):
    from cognits.agent.tool_mastery import UpdateMastery

    s = _skill("Variables"); store.upsert_skill(s)
    tool = UpdateMastery(learner_state=store)
    args = json.dumps({"skill_id": s.id, "correctness": 0.95, "rating": 3})
    result = asyncio.run(tool.execute(args))
    data = json.loads(result)
    assert data["p_mastery_before"] == 0.5
    assert data["p_mastery_after"] > 0.5
    assert data["status_enum"] != "not_seen"
    assert data["next_review"] is not None
    # Verify state persisted in store.
    st = store.get_learner_state(s.id)
    assert st is not None and st.reps == 1
    assert st.p_mastery > 0.5


def test_update_mastery_failure_drops_mastery(store):
    from cognits.agent.tool_mastery import UpdateMastery

    s = _skill("FailSkill"); store.upsert_skill(s)
    # First boost mastery.
    tool = UpdateMastery(learner_state=store)
    asyncio.run(tool.execute(json.dumps({"skill_id": s.id, "correctness": 0.95, "rating": 3})))
    before = store.get_learner_state(s.id)
    # Then fail.
    args = json.dumps({"skill_id": s.id, "correctness": 0.1, "rating": 1})
    result = asyncio.run(tool.execute(args))
    data = json.loads(result)
    assert data["p_mastery_after"] < before.p_mastery
    after = store.get_learner_state(s.id)
    assert after.lapses == 1


def test_update_mastery_returns_before_after(store):
    from cognits.agent.tool_mastery import UpdateMastery

    s = _skill("BeforeAfter"); store.upsert_skill(s)
    tool = UpdateMastery(learner_state=store)
    result = asyncio.run(tool.execute(json.dumps({"skill_id": s.id, "correctness": 0.8, "rating": 2})))
    data = json.loads(result)
    assert data["p_mastery_before"] == 0.5
    assert data["p_mastery_after"] >= data["p_mastery_before"]
    assert "skill_id" in data
    assert "status_enum" in data


def test_update_mastery_unknown_skill(store):
    from cognits.agent.tool_mastery import UpdateMastery

    tool = UpdateMastery(learner_state=store)
    result = asyncio.run(tool.execute(json.dumps({"skill_id": "k_nonexistent", "correctness": 0.5, "rating": 3})))
    assert "error" in json.loads(result)


def test_update_mastery_invalid_rating(store):
    from cognits.agent.tool_mastery import UpdateMastery

    s = _skill(); store.upsert_skill(s)
    tool = UpdateMastery(learner_state=store)
    result = asyncio.run(tool.execute(json.dumps({"skill_id": s.id, "correctness": 0.5, "rating": 5})))
    assert "error" in json.loads(result)


# --- evaluator prompt checks -----------------------------------------

def test_evaluator_prompt_describes_two_phases():
    from cognits.agent.prompts import EVALUATOR_SYSTEM_PROMPT
    assert "Phase 1" in EVALUATOR_SYSTEM_PROMPT
    assert "Phase 2" in EVALUATOR_SYSTEM_PROMPT
    assert "update_mastery" in EVALUATOR_SYSTEM_PROMPT


def test_evaluator_prompt_requires_source_citation():
    from cognits.agent.prompts import EVALUATOR_SYSTEM_PROMPT
    assert "source" in EVALUATOR_SYSTEM_PROMPT.lower()
    assert "low_confidence" in EVALUATOR_SYSTEM_PROMPT


def test_evaluator_prompt_describes_rating_scale():
    from cognits.agent.prompts import EVALUATOR_SYSTEM_PROMPT
    assert "Again" in EVALUATOR_SYSTEM_PROMPT
    assert "Hard" in EVALUATOR_SYSTEM_PROMPT
    assert "Good" in EVALUATOR_SYSTEM_PROMPT
    assert "Easy" in EVALUATOR_SYSTEM_PROMPT


# --- agent: last_messages --------------------------------------------

class _ScriptedLLM:
    """Replays scripted streams: each element is one chat_completion_stream."""

    def __init__(self, streams):
        self.streams = list(streams)

    async def chat_completion_stream(self, messages, tools, model, reasoning, on_chunk, **kw):
        for chunk in self.streams.pop(0):
            on_chunk(chunk)


def _delta(content=None, tool_calls=None, finish=None):
    d = {}
    if content is not None:
        d["content"] = content
    if tool_calls is not None:
        d["tool_calls"] = tool_calls
    return {"choices": [{"delta": d, "finish_reason": finish}]}


def test_agent_last_messages_saved_after_run():
    from cognits.agent.agent import Agent, AgentConfig

    streams = [
        [_delta(content="Hello world", finish="stop")],
    ]
    llm = _ScriptedLLM(streams)
    cfg = AgentConfig(name="test", model="m", system_prompt="sys")
    ag = Agent(cfg, llm)
    result = asyncio.run(ag.run([], lambda e: None))
    assert result == "Hello world"
    assert ag.last_messages is not None
    assert len(ag.last_messages) >= 2  # system + assistant


# --- resume_token in DeploySubagent ----------------------------------

class _FakeLLM:
    def __init__(self, responses=None):
        self.responses = list(responses or [])
        self.calls = []

    async def chat_completion_stream(self, messages, tools, model, reasoning, on_chunk, **kw):
        self.calls.append(list(messages))
        resp = self.responses.pop(0) if self.responses else "ok"
        on_chunk({"choices": [{"delta": {"content": resp}}]})
        on_chunk({"choices": [{"delta": {}, "finish_reason": "stop"}]})


class _FakeTF:
    async def aclose(self): pass


def test_deploy_resume_phase2(tmp_path):
    """Test the resume_token mechanism at the DeploySubagent level
    using a simple echo subagent, not the full evaluator stack."""
    from cognits.agent.tool_deploy import DeploySubagent
    from cognits.agent.agent import AgentConfig

    store = LegacyStore(tmp_path / "db2.db")
    s = _skill("ResumeTest"); store.upsert_skill(s)

    # Build a minimal subagent that echoes its query back.
    echo_cfg = AgentConfig(
        name="echo",
        model="m",
        system_prompt="You are an echo. Repeat the user's query followed by the word DONE.",
        tools=Registry(),
    )

    class _EchoLLM:
        def __init__(self):
            self.calls = []

        async def chat_completion_stream(self, messages, tools, model, reasoning, on_chunk, **kw):
            self.calls.append(list(messages))
            # Echo the last user message.
            last_user = next((m for m in reversed(messages) if m.role == "user"), None)
            reply = (last_user.content + " DONE") if last_user else "DONE"
            on_chunk({"choices": [{"delta": {"content": reply}}]})
            on_chunk({"choices": [{"delta": {}, "finish_reason": "stop"}]})

    echo_llm = _EchoLLM()

    suspended: dict = {}
    tool = DeploySubagent(
        llm_client=echo_llm,
        reports=store,
        subagents={"echo": echo_cfg},
        session_id=lambda: "s_test",
        emit=None,
        rag_engine=None,
        suspended_subagents=suspended,
    )

    # Phase 1: fresh deployment.
    r1 = asyncio.run(tool.execute(json.dumps({"type": "echo", "query": "Phase 1: hello"})))
    d1 = json.loads(r1)
    assert d1["content"] == "Phase 1: hello DONE"
    resume_token = d1.get("resume_token")
    assert resume_token is not None and resume_token.startswith("resume_")
    assert resume_token in suspended

    # Phase 2: resume.
    r2 = asyncio.run(tool.execute(json.dumps({
        "type": "echo", "query": "Phase 2: world",
        "resume_token": resume_token,
    })))
    d2 = json.loads(r2)
    assert d2["content"] == "Phase 2: world DONE"
    # Token consumed.
    assert resume_token not in suspended


# --- static checks ---------------------------------------------------

def test_deploy_enum_includes_evaluator():
    from cognits.agent.tool_deploy import DeploySubagent
    assert "evaluator" in DeploySubagent.schema["properties"]["type"]["enum"]


def test_evaluator_in_default_agents():
    from cognits.agent.prompts import DEFAULT_AGENTS
    ids = [a["id"] for a in DEFAULT_AGENTS]
    assert "evaluator" in ids


def test_evaluator_config_builds(store):
    from cognits.agent.subagents import evaluator_config

    class FakeLLM:
        async def aclose(self): pass
        async def chat_completion_stream(self, *a, **kw): pass

    class FakeTF:
        async def aclose(self): pass

    cfg = evaluator_config(
        model="m", reasoning="", max_steps=10,
        llm_client=FakeLLM(), rag_engine=None, tf_client=FakeTF(),
        reports=store, learner_state=store, session_id=lambda: "s_test",
        emit=lambda e: None,
    )
    assert cfg.name == "evaluator"
    tool_names = set(cfg.tools._tools.keys())
    assert "update_mastery" in tool_names
    assert "web_researcher" in cfg.subagents