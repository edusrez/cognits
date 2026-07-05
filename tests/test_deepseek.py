"""Tests for llm/deepseek.py: streaming, SSE, errors, tool call deltas."""

import asyncio
import json
import re

import httpx
import pytest
import respx

from cognits.llm.deepseek import DeepSeekClient, DeepSeekError
from cognits.constants import LLM_BASE_URL


@pytest.fixture
def client():
    return DeepSeekClient("fake-key")


def _chunk(*content: str) -> str:
    joined = "\n".join(f"data: {c}" for c in content)
    return f"{joined}\n\ndata: [DONE]\n\n"


def _resp(chunks: str, status=200):
    return httpx.Response(status, content=chunks.encode())


@pytest.mark.asyncio
async def test_stream_tokens(client):
    chunks = _chunk(
        '{"choices":[{"delta":{"content":"Hello"}}]}',
        '{"choices":[{"delta":{"content":" world"}}]}',
    )
    with respx.mock(assert_all_mocked=False) as m:
        m.post(LLM_BASE_URL).mock(return_value=_resp(chunks))
        acc = []
        await client.chat_completion_stream(
            messages=[], tools=None, model="m", reasoning="disabled",
            on_chunk=lambda c: acc.append(c["choices"][0]["delta"].get("content", "")))
        assert "".join(acc) == "Hello world"


@pytest.mark.asyncio
async def test_stream_non_200(client):
    body = json.dumps({"error": {"message": "Unauthorized"}})
    with respx.mock(assert_all_mocked=False) as m:
        m.post(LLM_BASE_URL).mock(return_value=httpx.Response(401, content=body.encode()))
        with pytest.raises(DeepSeekError, match=r"(?i)unauthorized"):
            await client.chat_completion_stream(
                messages=[], tools=None, model="m", reasoning="disabled",
                on_chunk=lambda c: None)


@pytest.mark.asyncio
async def test_stream_skips_non_data_lines(client):
    chunks = "event: ping\ndata: {\"choices\":[{\"delta\":{\"content\":\"X\"}}]}\n\ndata: [DONE]\n\n"
    with respx.mock(assert_all_mocked=False) as m:
        m.post(LLM_BASE_URL).mock(return_value=_resp(chunks))
        acc = []
        await client.chat_completion_stream(
            messages=[], tools=None, model="m", reasoning="disabled",
            on_chunk=lambda c: acc.append(c))
        assert len(acc) == 1


@pytest.mark.asyncio
async def test_stream_skip_malformed_json(client):
    chunks = "data: not json\n\ndata: {\"choices\":[{\"delta\":{\"content\":\"ok\"}}]}\n\ndata: [DONE]\n\n"
    with respx.mock(assert_all_mocked=False) as m:
        m.post(LLM_BASE_URL).mock(return_value=_resp(chunks))
        acc = []
        await client.chat_completion_stream(
            messages=[], tools=None, model="m", reasoning="disabled",
            on_chunk=lambda c: acc.append(c))
        assert len(acc) == 1


@pytest.mark.asyncio
async def test_stream_read_timeout(client):
    with respx.mock(assert_all_mocked=False) as m:
        m.post(LLM_BASE_URL).mock(side_effect=httpx.ReadTimeout("timeout"))
        with pytest.raises(DeepSeekError, match="idle"):
            await client.chat_completion_stream(
                messages=[], tools=None, model="m", reasoning="disabled",
                on_chunk=lambda c: None)


@pytest.mark.asyncio
async def test_stream_http_error(client):
    with respx.mock(assert_all_mocked=False) as m:
        m.post(LLM_BASE_URL).mock(side_effect=httpx.HTTPError("boom"))
        with pytest.raises(DeepSeekError, match="request"):
            await client.chat_completion_stream(
                messages=[], tools=None, model="m", reasoning="disabled",
                on_chunk=lambda c: None)


@pytest.mark.asyncio
async def test_reasoning_mode_with_tools_omits_thinking(client):
    with respx.mock(assert_all_mocked=False) as m:
        route = m.post(LLM_BASE_URL).mock(return_value=_resp(_chunk()))
        await client.chat_completion_stream(
            messages=[], tools=[{"type": "function"}], model="m",
            reasoning="max", on_chunk=lambda c: None)
        req_body = json.loads(route.calls.last.request.content)
        assert "thinking" not in req_body


@pytest.mark.asyncio
async def test_max_tokens_temperature_sent(client):
    with respx.mock(assert_all_mocked=False) as m:
        route = m.post(LLM_BASE_URL).mock(return_value=_resp(_chunk()))
        await client.chat_completion_stream(
            messages=[], tools=None, model="m", reasoning="disabled",
            max_tokens=100, temperature=0.7, top_p=0.9,
            on_chunk=lambda c: None)
        req_body = json.loads(route.calls.last.request.content)
        assert req_body["max_tokens"] == 100
        assert req_body["temperature"] == 0.7
        assert req_body["top_p"] == 0.9


# --- multi-provider architecture tests ---

from cognits.constants import (
    MODEL_CONTEXT_WINDOW,
    parse_model,
    get_context_window,
)


def test_parse_model_with_provider():
    assert parse_model("deepseek/deepseek-v4-pro") == ("deepseek", "deepseek-v4-pro")


def test_parse_model_bare_id():
    assert parse_model("deepseek-v4-pro") == ("deepseek", "deepseek-v4-pro")


def test_deepseek_client_accepts_base_url():
    client = DeepSeekClient("key", base_url="https://custom.url")
    assert client.base_url == "https://custom.url"


def test_deepseek_client_default_base_url():
    client = DeepSeekClient("key")
    assert client.base_url == LLM_BASE_URL


def test_get_context_window_known_model():
    assert get_context_window("deepseek-v4-pro") == 1_048_576


def test_get_context_window_unknown_model_fallback():
    assert get_context_window("unknown-model") == MODEL_CONTEXT_WINDOW
