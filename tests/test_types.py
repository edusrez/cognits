"""Tests for llm/types.py: Message, ToolCall dataclasses and payload serialization."""

from cognits.llm.types import ROLE_SYSTEM, ROLE_USER, Message, ToolCall


def test_message_to_payload_system():
    m = Message(role=ROLE_SYSTEM, content="Hello")
    p = m.to_payload()
    assert p == {"role": "system", "content": "Hello"}


def test_message_to_payload_user():
    m = Message(role=ROLE_USER, content="Hi")
    p = m.to_payload()
    assert p == {"role": "user", "content": "Hi"}


def test_message_to_payload_empty_content_omitted():
    m = Message(role="assistant")
    p = m.to_payload()
    assert "content" not in p
    assert p == {"role": "assistant"}


def test_message_to_payload_with_tool_calls():
    tc = ToolCall(id="c1", name="search", arguments='{"q":"x"}')
    m = Message(role="assistant", content="", tool_calls=[tc])
    p = m.to_payload()
    assert "tool_calls" in p
    assert p["tool_calls"][0]["id"] == "c1"


def test_message_to_payload_tool_role():
    m = Message(role="tool", content="result", tool_call_id="c1")
    p = m.to_payload()
    assert p["role"] == "tool"
    assert p["tool_call_id"] == "c1"
    assert "content" in p


def test_tool_call_to_payload():
    tc = ToolCall(id="tc1", name="deploy", arguments='{"type":"web"}')
    p = tc.to_payload()
    assert p["id"] == "tc1"
    assert p["type"] == "function"
    assert p["function"]["name"] == "deploy"


def test_omitempty_content():
    assert Message(role="a", content="").to_payload() == {"role": "a"}
    assert Message(role="a").to_payload() == {"role": "a"}
