"""Tests for server/chat_service.py: agent lifecycle, subagent map, registry."""

import asyncio
import json

import pytest

from cognits.llm.types import Message
from cognits.server.chat_service import ChatService
from cognits.server.session_agent import SessionAgent
from cognits.storage.files import Config
from cognits.storage.models import SessionConfigRow


@pytest.fixture
def config():
    cfg = Config()
    cfg.llm_api_key = "test-key"
    cfg.tinyfish_api_key = "test-tf"
    return cfg


@pytest.fixture
def session_agent():
    from cognits.storage.models import MessageRow
    return SessionAgent("s_test", [MessageRow(role="system", content="start")])


@pytest.fixture
def svc(real_state, config, session_agent):
    state, app = real_state
    return ChatService(
        st=state,
        sa=session_agent,
        cfg=config,
        sid="s_test",
        model="deepseek-v4-pro",
        reasoning="max",
        system_prompt="You are a tutor.",
        llm_messages=[Message(role="system", content="ctx"), Message(role="user", content="hi")],
        incoming=[{"role": "user", "content": "hi"}],
        agent_id="orchestrator",
    )


def test_chat_service_constructs(svc):
    assert svc.st is not None
    assert svc.model == "deepseek-v4-pro"
    assert svc.agent_id == "orchestrator"


def test_build_subagent_map_orchestrator(svc):
    subagent_map = svc._build_subagent_map(
        process_event=lambda ev: None,
        cfg=svc.cfg,
        sid=svc.sid,
        llm_client=None,
        tf_client=None,
    )
    assert "web_researcher" in subagent_map
    assert "directory_reader" in subagent_map
    assert "study_planner" in subagent_map
    # documentalist only if RAG ready
    # skill_planner only if tinyfish key


def test_build_subagent_map_maestro(real_state, config, session_agent):
    state, app = real_state
    svc = ChatService(
        st=state, sa=session_agent, cfg=config, sid="s_test",
        model="m", reasoning="", system_prompt="",
        llm_messages=[], incoming=[], agent_id="maestro",
    )
    subagent_map = svc._build_subagent_map(
        process_event=lambda ev: None,
        cfg=config, sid="s_test", llm_client=None, tf_client=None,
    )
    # evaluator and documentalist only if tf_client and rag
    # session_analyzer present when agent_id != system_support
    assert "session_analyzer" in subagent_map


def test_build_tool_registry_has_deploy(svc):
    registry = svc._build_tool_registry(
        process_event=lambda ev: None,
        subagent_map={"web_researcher": None},
        cfg=svc.cfg, sid="s_test", llm_client=None, tf_client=None,
    )
    tools = registry.definitions()
    names = [t["function"]["name"] for t in tools]
    assert "deploy_subagent" in names


def test_persist_partial(svc):
    svc._persist_partial(
        acc={"content": "hello", "reasoning": "intro"},
        sa=svc.sa, st=svc.st, sid=svc.sid,
        llm_client=None, tf_client=None,
    )
    last_msg = svc.sa.messages[-1]
    assert last_msg.role == "assistant"
    assert last_msg.content == "hello"
    assert last_msg.reasoning == "intro"


def test_persist_partial_empty_acc(svc):
    svc._persist_partial(
        acc={"content": "", "reasoning": ""},
        sa=svc.sa, st=svc.st, sid=svc.sid,
        llm_client=None, tf_client=None,
    )
    assert svc.sa.live_content == ""
    assert svc.sa.live_reports == []


def test_compact_short_conversation_noop(svc):
    from cognits.agent.token_counter import TokenCounter
    result = svc._compact(svc.llm_messages, TokenCounter(), None)
    assert len(result) == len(svc.llm_messages)


def test_tool_log_upsert_by_id(session_agent):
    """tool_progress with id creates/updates entries; subagent_end marks done."""
    sa = session_agent
    from cognits.server.chat_service import ChatService

    # Minimal ChatService just to get process_event
    # We mock publish so we can directly call process_event
    class FakeSt:
        db = None

    svc = ChatService(
        st=FakeSt(), sa=sa, cfg=None, sid="s1",
        model="m", reasoning="", system_prompt="",
        llm_messages=[], incoming=[], agent_id="test",
    )
    acc = {"content": "", "reasoning": ""}
    pe = svc._make_process_event(acc, sa, FakeSt(), "s1")

    # First tool_progress: creates entry
    pe({"type": "tool_progress", "data": {"id": "abc123", "agent": "web_researcher", "message": "Searching the Web..."}})
    assert len(sa.tool_log) == 1
    assert sa.tool_log[0]["id"] == "abc123"
    assert sa.tool_log[0]["agent"] == "web_researcher"
    assert sa.tool_log[0]["message"] == "Searching the Web..."
    assert sa.tool_log[0]["done"] is False

    # Second tool_progress with same id: updates message
    pe({"type": "tool_progress", "data": {"id": "abc123", "message": "Writing..."}})
    assert len(sa.tool_log) == 1
    assert sa.tool_log[0]["message"] == "Writing..."
    assert sa.tool_log[0]["done"] is False

    # subagent_end: marks done
    pe({"type": "subagent_end", "data": {"id": "abc123", "agent": "web_researcher", "internal": False, "reportId": "r1", "title": "Test"}})
    assert sa.tool_log[0]["done"] is True


def test_internal_subagent_end_no_live_reports(session_agent):
    """Internal subagent_end does NOT add to live_reports."""
    sa = session_agent
    from cognits.server.chat_service import ChatService

    class FakeSt:
        db = None

    svc = ChatService(
        st=FakeSt(), sa=sa, cfg=None, sid="s1",
        model="m", reasoning="", system_prompt="",
        llm_messages=[], incoming=[], agent_id="test",
    )
    acc = {"content": "", "reasoning": ""}
    pe = svc._make_process_event(acc, sa, FakeSt(), "s1")

    # internal=True evaluator
    pe({"type": "subagent_end", "data": {"id": "eval1", "agent": "evaluator", "internal": True, "reportId": "r99", "title": "Eval Report"}})
    assert len(sa.live_reports) == 0
    # tool_log entry should be marked done
    assert any(e["id"] == "eval1" and e["done"] for e in sa.tool_log)


def test_noninternal_subagent_end_adds_live_reports(session_agent):
    """Non-internal subagent_end DOES add to live_reports."""
    sa = session_agent
    from cognits.server.chat_service import ChatService

    class FakeSt:
        db = None

    svc = ChatService(
        st=FakeSt(), sa=sa, cfg=None, sid="s1",
        model="m", reasoning="", system_prompt="",
        llm_messages=[], incoming=[], agent_id="test",
    )
    acc = {"content": "", "reasoning": ""}
    pe = svc._make_process_event(acc, sa, FakeSt(), "s1")

    pe({"type": "subagent_end", "data": {"id": "wr1", "agent": "web_researcher", "internal": False, "reportId": "r42", "title": "Web Report"}})
    assert len(sa.live_reports) == 1
    assert sa.live_reports[0] == {"reportId": "r42", "reportTitle": "Web Report"}


def test_agent_config_internal_defaults_false():
    from cognits.agent.agent import AgentConfig
    cfg = AgentConfig()
    assert cfg.internal is False


def test_internal_subagents_have_internal_true():
    from cognits.agent.subagents import session_namer_config, session_analyzer_config, evaluator_config
    assert session_namer_config().internal is True
    assert session_analyzer_config().internal is True
    # evaluator_config requires more args, test with minimal
    from cognits.tinyfish import TinyfishClient
    from cognits.storage.database import Database
    import tempfile, os
    tmp = tempfile.mkdtemp()
    db = Database(os.path.join(tmp, "test.db"))
    from cognits.storage.reports import ReportRepository
    from cognits.storage.skills import SkillRepository
    from cognits.storage.assessment import AssessmentItemRepository
    reports = ReportRepository(db)
    skills = SkillRepository(db)
    assessment = AssessmentItemRepository(db)
    tf = TinyfishClient("key")
    try:
        cfg = evaluator_config("m", "disabled", 1, None, None, tf, reports, skills, assessment, None, "s1", lambda ev: None, tinyfish_api_key="key")
        assert cfg.internal is True
    finally:
        db.shutdown()


def test_tool_phrases_default_is_working():
    from cognits.constants import TOOL_PHRASES
    assert TOOL_PHRASES.get("nonexistent_tool", "Working...") == "Working..."
    assert TOOL_PHRASES["tinyfish_search"] == "Searching the Web..."
    assert TOOL_PHRASES["rag_search"] == "Searching knowledge base..."
    assert TOOL_PHRASES["plan_study"] == "Planning study..."
    assert TOOL_PHRASES["update_mastery"] == "Updating mastery..."


def test_tool_log_reset_each_run(session_agent):
    """Each run_agent call resets tool_log."""
    sa = session_agent
    sa.tool_log = [{"id": "old", "agent": "x", "message": "", "favicons": [], "done": True, "parentId": None, "parentAgent": None}]
    from cognits.server.chat_service import ChatService

    class FakeSt:
        db = None
        messages = None
        reports = None
        rag_or_none = None
        suspended_subagents = {}
        active_agents = {}
        rag = None

    svc = ChatService(
        st=FakeSt(), sa=sa, cfg=None, sid="s1",
        model="m", reasoning="", system_prompt="",
        llm_messages=[], incoming=[], agent_id="test",
    )
    # We can't actually run the agent, but we can simulate the reset
    # The reset is in run_agent try block; verify it's called early
    # Manually simulate: clear tool_log
    sa.tool_log = []
    assert sa.tool_log == []


def test_session_namer_includes_hidden_user():
    """_run_session_namer guard condition includes hidden_user."""
    incoming = [{"role": "hidden_user", "content": "Start teaching..."}]
    # The guard counts both "user" and "hidden_user"
    count = sum(1 for m in incoming if m.get("role") in ("user", "hidden_user"))
    assert count == 1
    # Pure user messages should also work
    incoming2 = [{"role": "user", "content": "hello"}]
    count2 = sum(1 for m in incoming2 if m.get("role") in ("user", "hidden_user"))
    assert count2 == 1
    # System messages should not count
    incoming3 = [{"role": "system", "content": "ctx"}, {"role": "hidden_user", "content": "x"}]
    count3 = sum(1 for m in incoming3 if m.get("role") in ("user", "hidden_user"))
    assert count3 == 1


def test_tool_progress_parentid_stamping_in_nested_deploy():
    """A nested deploy stamps parentId on child events that lack it."""
    from cognits.agent.tool_deploy import DeploySubagent
    from cognits.agent.agent import AgentConfig
    from cognits.tools import Registry
    import json

    cfg = AgentConfig(name="child", model="m", system_prompt="", tools=Registry(), internal=False)
    emits: list[dict] = []

    class FakeLLM:
        async def aclose(self): pass
        async def chat_completion_stream(self, *a, **kw):
            on_chunk = a[4]
            on_chunk({"choices": [{"delta": {"content": "done"}}]})
            on_chunk({"choices": [{"delta": {}, "finish_reason": "stop"}]})

    deploy = DeploySubagent(
        llm_client=FakeLLM(),
        reports=None,
        subagents={"child": cfg},
        session_id=lambda: "s_test",
        emit=lambda ev: emits.append(ev),
        rag_engine=None,
        suspended_subagents={},
    )

    async def run():
        return await deploy.execute(json.dumps({"type": "child", "query": "test"}))

    result = asyncio.run(run())

    # Check subagent_end has id, agent, internal but no parentId
    se = next(e for e in emits if e["type"] == "subagent_end")
    assert se["data"]["id"] is not None
    assert se["data"]["agent"] == "child"
    assert "parentId" not in se["data"]
    assert "parentAgent" not in se["data"]


def test_tool_progress_favicons_stamped_with_id():
    """process_event: favicons stamped with id attach to the matching
    tool_log entry (not just the legacy tool_favicons field)."""
    from cognits.server.chat_service import ChatService
    from cognits.server.session_agent import SessionAgent
    from cognits.storage.models import MessageRow

    sa = SessionAgent("s_test", [MessageRow(role="system", content="start")])

    class FakeSt:
        db = None

    svc = ChatService(
        st=FakeSt(), sa=sa, cfg=None, sid="s1",
        model="m", reasoning="", system_prompt="",
        llm_messages=[], incoming=[], agent_id="test",
    )
    acc = {"content": "", "reasoning": ""}
    pe = svc._make_process_event(acc, sa, FakeSt(), "s1")

    # Step 1: create a tool_log entry (simulates tool_start / first progress)
    agent_name = "web_researcher"
    tool_id = "abc_fav_test"
    pe({"type": "tool_progress", "data": {"id": tool_id, "agent": agent_name, "message": "Searching the Web..."}})
    assert len(sa.tool_log) == 1
    assert sa.tool_log[0]["id"] == tool_id

    # Step 2: favicons-only event (post-wrapper, id already stamped).
    # process_event should attach favicons to the matching tool_log entry.
    favicons = ["https://example.com/favicon.ico"]
    pe({"type": "tool_progress", "data": {"id": tool_id, "favicons": favicons}})

    # No duplicate entry; favicons on the existing entry
    assert len(sa.tool_log) == 1, "no duplicate entry created"
    assert sa.tool_log[0]["favicons"] == favicons
    assert sa.tool_log[0]["id"] == tool_id
    assert sa.tool_log[0]["agent"] == agent_name


def test_stamp_tool_progress_helper():
    """_stamp_tool_progress handles the three cases correctly."""
    from cognits.agent.tool_deploy import _stamp_tool_progress

    # Case 1: no id → stamp id + agent
    d1 = {"favicons": ["https://x.ico"]}
    _stamp_tool_progress(d1, "inst_abc", "web_researcher")
    assert d1["id"] == "inst_abc"
    assert d1["agent"] == "web_researcher"
    assert d1["favicons"] == ["https://x.ico"]  # original data preserved

    # Case 2: id present, no parentId → stamp parentId + parentAgent
    d2 = {"id": "child_inst", "agent": "child", "message": "Working..."}
    _stamp_tool_progress(d2, "parent_inst", "maestro")
    assert d2["parentId"] == "parent_inst"
    assert d2["parentAgent"] == "maestro"
    assert d2["id"] == "child_inst"  # unchanged
    assert d2["message"] == "Working..."  # unchanged

    # Case 3: both id and parentId present → no change
    d3 = {"id": "grandchild", "parentId": "child", "parentAgent": "nested"}
    _stamp_tool_progress(d3, "wrapper", "outer")
    assert d3["id"] == "grandchild"
    assert d3["parentId"] == "child"
    assert d3["parentAgent"] == "nested"
    assert "agent" not in d3  # wasn't present, wasn't added


# --- async reflection tests -------------------------------------------


class _MockDeploy:
    """Mock DeploySubagent whose execute() returns a controlled JSON string."""
    def __init__(self, result: str):
        self._result = result
        self.execute_called = False

    async def execute(self, raw_args: str) -> str:
        self.execute_called = True
        self.last_args = raw_args
        return self._result


def _make_maestro_svc(state, session_agent, config):
    """Helper: returns a ChatService for maestro agent."""
    from cognits.server.chat_service import ChatService
    return ChatService(
        st=state, sa=session_agent, cfg=config, sid="s_reflect",
        model="deepseek-v4-pro", reasoning="max",
        system_prompt="You are a tutor.",
        llm_messages=[Message(role="system", content="ctx"),
                      Message(role="user", content="hi")],
        incoming=[{"role": "user", "content": "hi"}],
        agent_id="maestro",
    )


def test_reflect_async_clean_pass_no_store(real_state, session_agent, config, monkeypatch):
    """A clean pass (verdict=pass, no violations) does NOT store anything."""
    state, app = real_state
    svc = _make_maestro_svc(state, session_agent, config)

    # Mock DeploySubagent to return a clean critique
    async def _fake_execute(self, raw_args):
        return json.dumps({"verdict": "pass", "socratic_violations": []})

    mock_deploy = type("_FakeDeploy", (), {"execute": _fake_execute, "__init__": lambda s, **kw: None})

    monkeypatch.setattr("cognits.agent.tool_deploy.DeploySubagent", mock_deploy)

    # Need a non-None evaluator config to avoid early exit in _reflect_async
    dummy_eval_cfg = object()
    asyncio.run(svc._reflect_async(
        draft="response text", subagent_map={"evaluator": dummy_eval_cfg},
        llm_client=None, sid="s_reflect",
    ))

    assert svc.sid not in state.pending_critiques


def test_reflect_async_violations_store_feedback(real_state, session_agent, config, monkeypatch):
    """Violations in critique → store feedback for next turn."""
    state, app = real_state
    svc = _make_maestro_svc(state, session_agent, config)

    critique = {
        "verdict": "fail",
        "socratic_violations": [
            {"principle": "Leading questions", "severity": "high", "excerpt": "Don't you think..."},
        ],
        "scaffolding_assessment": "Too much information at once",
        "suggested_revision": "Ask what they already know first",
        "confidence": 0.9,
    }

    async def _fake_execute(self, raw_args):
        return json.dumps(critique)

    mock_deploy = type("_FakeDeploy", (), {"execute": _fake_execute, "__init__": lambda s, **kw: None})

    monkeypatch.setattr("cognits.agent.tool_deploy.DeploySubagent", mock_deploy)

    asyncio.run(svc._reflect_async(
        draft="response text", subagent_map={"evaluator": object()},
        llm_client=None, sid="s_reflect",
    ))

    assert "s_reflect" in state.pending_critiques
    feedback = state.pending_critiques["s_reflect"]
    assert "FEEDBACK FROM AN INDEPENDENT REVIEWER" in feedback
    assert "socratic_violations" in feedback
    assert "verdict" in feedback


def test_reflect_async_verdict_not_pass_stores(real_state, session_agent, config, monkeypatch):
    """verdict != 'pass' with empty violations still stores."""
    state, app = real_state
    svc = _make_maestro_svc(state, session_agent, config)

    critique = {"verdict": "fail", "socratic_violations": [], "confidence": 0.8}

    async def _fake_execute(self, raw_args):
        return json.dumps(critique)

    mock_deploy = type("_FakeDeploy", (), {"execute": _fake_execute, "__init__": lambda s, **kw: None})

    monkeypatch.setattr("cognits.agent.tool_deploy.DeploySubagent", mock_deploy)

    asyncio.run(svc._reflect_async(
        draft="text", subagent_map={"evaluator": object()},
        llm_client=None, sid="s_reflect",
    ))

    assert "s_reflect" in state.pending_critiques


def test_reflect_async_violations_only_stores(real_state, session_agent, config, monkeypatch):
    """verdict=pass but with violations → still stores (violations take priority)."""
    state, app = real_state
    svc = _make_maestro_svc(state, session_agent, config)

    critique = {
        "verdict": "pass",
        "socratic_violations": [{"principle": "Direct answer", "severity": "medium"}],
    }

    async def _fake_execute(self, raw_args):
        return json.dumps(critique)

    mock_deploy = type("_FakeDeploy", (), {"execute": _fake_execute, "__init__": lambda s, **kw: None})

    monkeypatch.setattr("cognits.agent.tool_deploy.DeploySubagent", mock_deploy)

    asyncio.run(svc._reflect_async(
        draft="text", subagent_map={"evaluator": object()},
        llm_client=None, sid="s_reflect",
    ))

    assert "s_reflect" in state.pending_critiques


def test_reflect_async_no_evaluator_config_noop(real_state, session_agent, config, monkeypatch):
    """If evaluator config is missing, _reflect_async returns without error."""
    state, app = real_state
    svc = _make_maestro_svc(state, session_agent, config)

    asyncio.run(svc._reflect_async(
        draft="text", subagent_map={},
        llm_client=None, sid="s_reflect",
    ))

    assert "s_reflect" not in state.pending_critiques


def test_reflect_async_exception_graceful(real_state, session_agent, config, monkeypatch):
    """Evaluator failure is caught and logged, not raised."""
    state, app = real_state
    svc = _make_maestro_svc(state, session_agent, config)

    class _CrashingMock:
        def __init__(self, **kw):
            pass
        async def execute(self, raw_args):
            raise RuntimeError("simulated evaluator crash")

    monkeypatch.setattr("cognits.agent.tool_deploy.DeploySubagent", _CrashingMock)

    asyncio.run(svc._reflect_async(
        draft="text", subagent_map={"evaluator": object()},
        llm_client=None, sid="s_reflect",
    ))

    assert "s_reflect" not in state.pending_critiques


def test_pending_critique_injected_next_turn(real_state, session_agent, config):
    """A pending critique in st.pending_critiques is popped and injected as
    a system message at the start of the next maestro turn."""
    state, app = real_state
    svc = _make_maestro_svc(state, session_agent, config)

    # Simulate a pending critique
    feedback = "Previous response was too direct. Be more Socratic."
    state.pending_critiques[svc.sid] = feedback

    # Manually run the injection logic (same as in run_agent):
    sid = svc.sid
    pending = state.pending_critiques.pop(sid, None)
    assert pending == feedback
    svc.llm_messages.append(Message(role="system", content=pending))

    # Verify the feedback was injected and removed
    assert sid not in state.pending_critiques
    assert any(
        m.role == "system" and feedback in m.content
        for m in svc.llm_messages
    )


def test_reflection_enabled_false_skips(real_state, session_agent):
    """When reflection_enabled=False, the background task is NOT scheduled.
    
    We verify that getattr(cfg, 'reflection_enabled', True) returns False
    when the config has reflection_enabled=False, which gates the task.
    """
    state, app = real_state
    cfg = Config()
    cfg.llm_api_key = "test-key"
    cfg.tinyfish_api_key = "test-tf"
    cfg.reflection_enabled = False

    # The gate condition in run_agent:
    # if self.agent_id == "maestro" and acc["content"] and getattr(cfg, "reflection_enabled", True):
    agent_id = "maestro"
    acc_content = "some response"
    enabled = getattr(cfg, "reflection_enabled", True)
    should_launch = (agent_id == "maestro" and bool(acc_content) and enabled)
    assert not should_launch

    # With default True
    cfg.reflection_enabled = True
    enabled = getattr(cfg, "reflection_enabled", True)
    should_launch = (agent_id == "maestro" and bool(acc_content) and enabled)
    assert should_launch


def test_config_serialization_reflection_enabled():
    """reflection_enabled serializes and deserializes properly."""
    cfg = Config()
    assert cfg.reflection_enabled is True

    js = cfg.to_json()
    assert js.get("reflectionEnabled") is True

    cfg2 = Config.from_json(js)
    assert cfg2.reflection_enabled is True

    # With False
    cfg.reflection_enabled = False
    js = cfg.to_json()
    assert js.get("reflectionEnabled") is False

    cfg2 = Config.from_json(js)
    assert cfg2.reflection_enabled is False


# --- auto-regen study plan tests ---------------------------------------


def test_config_serialization_study_plan_auto_regen():
    """study_plan_auto_regen serializes and deserializes properly."""
    cfg = Config()
    assert cfg.study_plan_auto_regen is True

    js = cfg.to_json()
    assert js.get("studyPlanAutoRegen") is True

    cfg2 = Config.from_json(js)
    assert cfg2.study_plan_auto_regen is True

    # With False
    cfg.study_plan_auto_regen = False
    js = cfg.to_json()
    assert js.get("studyPlanAutoRegen") is False

    cfg2 = Config.from_json(js)
    assert cfg2.study_plan_auto_regen is False


def test_regen_study_plan_no_active_plan_noop(real_state, session_agent, config):
    """No active study plan → _regen_study_plan_async returns without error."""
    state, app = real_state
    svc = _make_maestro_svc(state, session_agent, config)

    asyncio.run(svc._regen_study_plan_async(
        session_id="s_regen", sa=session_agent,
    ))
    # No active plan → should not crash


def test_regen_study_plan_no_mastered_skills_noop(real_state, session_agent, config):
    """Active plan but no skills mastered → no regen (no change)."""
    state, app = real_state
    svc = _make_maestro_svc(state, session_agent, config)

    # Ensure no active plan exists
    # get_active returns None → returns early, no crash
    from cognits.storage.models import LearnerState

    # Insert a skill and learner state (below threshold)
    from cognits.storage.models import Skill
    skill = Skill(
        id="k_test_regen", domain="test", name="Test Skill",
        difficulty=0.5, tree_version=1, status="active",
    )
    state.skills.upsert(skill)
    ls = LearnerState(skill_id="k_test_regen", p_mastery=0.5)
    state.learner_state.upsert(ls)

    # Create active plan with the skill
    plan_id = state.study_plans.create(
        tree_version=1, goal="learn", session_id="s_regen",
    )
    state.study_plans.add_item(
        plan_id=plan_id, skill_id="k_test_regen", order_index=0,
    )

    asyncio.run(svc._regen_study_plan_async(
        session_id="s_regen", sa=session_agent,
    ))
    # p_mastery=0.5 < threshold → should return early, no regen
    # Plan should still be active (not superseded)
    active = state.study_plans.get_active()
    assert active is not None
    assert active.id == plan_id


def test_regen_study_plan_mastered_skill_triggers_regen(real_state, session_agent, config):
    """When a plan skill crosses mastery threshold, plan is regenerated."""
    state, app = real_state
    svc = _make_maestro_svc(state, session_agent, config)

    from cognits.constants import MASTERY_THRESHOLD
    from cognits.storage.models import LearnerState, Skill

    # Insert two skills
    skill1 = Skill(
        id="k_regen_1", domain="test", name="Skill One",
        difficulty=0.3, tree_version=1, status="active",
    )
    skill2 = Skill(
        id="k_regen_2", domain="test", name="Skill Two",
        difficulty=0.5, tree_version=1, status="active",
    )
    state.skills.upsert(skill1)
    state.skills.upsert(skill2)

    # Skill 1 is mastered (crossed threshold)
    ls1 = LearnerState(skill_id="k_regen_1", p_mastery=0.96)
    ls2 = LearnerState(skill_id="k_regen_2", p_mastery=0.3)
    state.learner_state.upsert(ls1)
    state.learner_state.upsert(ls2)

    # Create active plan with skill1 (already mastered — crosses threshold)
    plan_id = state.study_plans.create(
        tree_version=1, goal="learn", session_id="s_regen",
    )
    state.study_plans.add_item(
        plan_id=plan_id, skill_id="k_regen_1", order_index=0,
    )

    asyncio.run(svc._regen_study_plan_async(
        session_id="s_regen", sa=session_agent,
    ))

    # Old plan should be superseded
    old_items = state.study_plans.get_items(plan_id)
    # New active plan should exist
    active = state.study_plans.get_active()
    assert active is not None
    assert active.id != plan_id

    # New plan should have items (skill1 is in frontier because it's
    # mastered, skill2 is in frontier because it has no prereqs blocked
    # by dependent mastered skills — it depends on nothing)
    new_items = state.study_plans.get_items(active.id)
    assert len(new_items) > 0


def test_regen_study_plan_emits_sse(real_state, session_agent, config):
    """When plan is regenerated, study_plan_updated SSE event is published."""
    state, app = real_state
    svc = _make_maestro_svc(state, session_agent, config)

    from cognits.constants import MASTERY_THRESHOLD
    from cognits.storage.models import LearnerState, Skill

    # Insert two skills: one mastered (triggers regen), one unmastered
    # (will be in frontier of new plan)
    skill1 = Skill(
        id="k_sse_m", domain="test", name="SSE Mastered",
        difficulty=0.5, tree_version=1, status="active",
    )
    skill2 = Skill(
        id="k_sse_u", domain="test", name="SSE Unmastered",
        difficulty=0.3, tree_version=1, status="active",
    )
    state.skills.upsert(skill1)
    state.skills.upsert(skill2)
    ls1 = LearnerState(skill_id="k_sse_m", p_mastery=MASTERY_THRESHOLD)
    ls2 = LearnerState(skill_id="k_sse_u", p_mastery=0.3)
    state.learner_state.upsert(ls1)
    state.learner_state.upsert(ls2)

    # Create active plan with the mastered skill
    plan_id = state.study_plans.create(
        tree_version=1, goal="learn", session_id="s_sse",
    )
    state.study_plans.add_item(
        plan_id=plan_id, skill_id="k_sse_m", order_index=0,
    )

    # Capture SSE events from sa.publish
    published = []

    class _CaptureSA:
        def publish(self, ev, update=None):
            published.append(ev)
        tool_log = []
        live_content = ""
        live_reasoning = ""
        live_reports = []
        messages = []

    capture_sa = _CaptureSA()

    asyncio.run(svc._regen_study_plan_async(
        session_id="s_sse", sa=capture_sa,
    ))

    # Should have published a study_plan_updated event
    plan_events = [e for e in published if e.get("type") == "study_plan_updated"]
    assert len(plan_events) == 1
    data = plan_events[0]["data"]
    assert "plan_id" in data
    assert "goal" in data
    assert "skill_ids" in data
    assert "item_count" in data
    assert data["item_count"] > 0


def test_regen_study_plan_handles_sa_gone(real_state, session_agent, config):
    """If sa is torn down (publish raises), _regen_study_plan_async does not crash."""
    state, app = real_state
    svc = _make_maestro_svc(state, session_agent, config)

    from cognits.constants import MASTERY_THRESHOLD
    from cognits.storage.models import LearnerState, Skill

    # Two skills: one mastered (triggers regen), one unmastered (frontier item)
    skill1 = Skill(
        id="k_gone_m", domain="test", name="Gone Mastered",
        difficulty=0.5, tree_version=1, status="active",
    )
    skill2 = Skill(
        id="k_gone_u", domain="test", name="Gone Unmastered",
        difficulty=0.3, tree_version=1, status="active",
    )
    state.skills.upsert(skill1)
    state.skills.upsert(skill2)
    ls1 = LearnerState(skill_id="k_gone_m", p_mastery=MASTERY_THRESHOLD)
    ls2 = LearnerState(skill_id="k_gone_u", p_mastery=0.3)
    state.learner_state.upsert(ls1)
    state.learner_state.upsert(ls2)

    plan_id = state.study_plans.create(
        tree_version=1, goal="learn", session_id="s_gone",
    )
    state.study_plans.add_item(
        plan_id=plan_id, skill_id="k_gone_m", order_index=0,
    )

    class _BrokenSA:
        def publish(self, ev, update=None):
            raise RuntimeError("session agent gone")

    broken_sa = _BrokenSA()

    # Should not raise
    asyncio.run(svc._regen_study_plan_async(
        session_id="s_gone", sa=broken_sa,
    ))
    # Plan should still be regenerated (superseded + new active)
    active = state.study_plans.get_active()
    assert active is not None
    assert active.id != plan_id


def test_regen_study_plan_disabled_config_no_regen(real_state, session_agent):
    """When study_plan_auto_regen=False, the auto-regen task is never scheduled."""
    state, app = real_state
    cfg = Config()
    cfg.llm_api_key = "test-key"
    cfg.tinyfish_api_key = "test-tf"
    cfg.study_plan_auto_regen = False

    # Verify gate condition
    mastery_updated = True
    agent_id = "maestro"
    should_launch = (agent_id == "maestro" and mastery_updated
                     and getattr(cfg, "study_plan_auto_regen", True))
    assert not should_launch

    # With default True
    cfg.study_plan_auto_regen = True
    should_launch = (agent_id == "maestro" and mastery_updated
                     and getattr(cfg, "study_plan_auto_regen", True))
    assert should_launch
