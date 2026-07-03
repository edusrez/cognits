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
