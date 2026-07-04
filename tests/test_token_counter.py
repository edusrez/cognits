"""Tests for agent/token_counter.py."""

from cognits.agent.token_counter import TokenCounter


def test_count_with_encoder():
    c = TokenCounter()
    result = c.count("Hello world")
    assert result > 0
    assert isinstance(result, int)


def test_count_multilingual():
    c = TokenCounter()
    spanish = c.count("Hola mundo, ¿cómo estás?")
    assert spanish > 0


def test_count_fallback():
    c = TokenCounter()
    c._encoder = None
    result = c.count("Hello world")
    assert result >= 1
    # chars//3.5 fallback: 11 chars => ~3 tokens
    assert result == max(1, int(len("Hello world") / 3.5))


def test_count_messages():
    from cognits.llm.types import Message
    c = TokenCounter()
    msgs = [
        Message(role="system", content="You are helpful"),
        Message(role="user", content="Hi"),
    ]
    total = c.count_messages(msgs)
    assert total > 0


def test_count_messages_with_tools():
    from cognits.llm.types import Message, ToolCall
    c = TokenCounter()
    m = Message(role="assistant", content="", tool_calls=[
        ToolCall(id="c1", name="search", arguments='{"query":"x"}'),
    ])
    total = c.count_messages([m])
    assert total > 0  # counts name + arguments
