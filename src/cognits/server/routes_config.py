"""Port of internal/server/config.go."""

from __future__ import annotations

import asyncio
import json

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

from cognits.constants import (
    DEFAULT_FLASH_MODEL,
    DEFAULT_MODEL,
    LLM_BASE_URL,
    LLM_CONNECT_TIMEOUT,
    LLM_POOL_TIMEOUT,
    LLM_READ_TIMEOUT,
    LLM_WRITE_TIMEOUT,
    MAX_TOKENS_LIMIT,
    ORCHESTRATOR_MAX_STEPS,
    VALID_REASONING,
)
from cognits.server.exceptions import CognitsError, NotFoundError
from cognits.server.util import mask_key
from cognits.storage.files import Config, StudentProfile

VALID_MODELS = (DEFAULT_MODEL, DEFAULT_FLASH_MODEL)


def _config_response(cfg: Config) -> dict:
    resp = cfg.to_json()
    resp["llmApiKey"] = mask_key(cfg.llm_api_key)
    resp["tinyfishApiKey"] = mask_key(cfg.tinyfish_api_key)
    return resp


def register(app: FastAPI, st) -> None:
    @app.get("/api/config")
    async def get_config():
        if st.store is None:
            return JSONResponse(_config_response(Config()))

        try:
            cfg = await asyncio.to_thread(st.store.load_config)
        except Exception as e:
            raise CognitsError(str(e), "ERROR", 500)

        return JSONResponse(_config_response(cfg))

    @app.put("/api/config")
    async def put_config(request: Request):
        if st.store is None:
            raise CognitsError("store not initialized", "ERROR", 500)

        try:
            body = await request.json()
            if not isinstance(body, dict):
                raise ValueError("body")
            cfg = Config.from_json(body)
        except (json.JSONDecodeError, ValueError, TypeError, UnicodeDecodeError):
            raise CognitsError("invalid body", "ERROR", 400)

        if cfg.llm_provider and cfg.llm_provider != "deepseek":
            raise CognitsError("invalid provider", "ERROR", 400)
        if cfg.llm_model and cfg.llm_model not in VALID_MODELS:
            raise CognitsError("invalid model", "ERROR", 400)
        if cfg.llm_reasoning and cfg.llm_reasoning not in VALID_REASONING:
            raise CognitsError("invalid reasoning value", "ERROR", 400)
        if cfg.max_tokens and not (0 < cfg.max_tokens <= MAX_TOKENS_LIMIT):
            raise CognitsError("invalid maxTokens", "ERROR", 400)
        if cfg.temperature and not (0 <= cfg.temperature <= 2.0):
            raise CognitsError("invalid temperature", "ERROR", 400)
        if cfg.top_p and not (0 <= cfg.top_p <= 1.0):
            raise CognitsError("invalid topP", "ERROR", 400)
        if cfg.max_steps and not (0 <= cfg.max_steps <= ORCHESTRATOR_MAX_STEPS):
            raise CognitsError("invalid maxSteps", "ERROR", 400)

        current = st.cached_config
        if current is not None:
            if cfg.llm_api_key == mask_key(current.llm_api_key):
                cfg.llm_api_key = current.llm_api_key
            if cfg.tinyfish_api_key == mask_key(current.tinyfish_api_key):
                cfg.tinyfish_api_key = current.tinyfish_api_key

        try:
            await asyncio.to_thread(st.store.save_config, cfg)
        except Exception as e:
            raise CognitsError(str(e), "ERROR", 500)

        st.cached_config = cfg
        return Response(status_code=204)

    @app.get("/api/profile")
    async def get_profile():
        if st.store is None:
            return JSONResponse({"version": 1, "declared": {}, "inferred": {}, "meta": {}})
        try:
            profile = await asyncio.to_thread(st.store.load_profile)
        except Exception as e:
            raise CognitsError(str(e), "ERROR", 500)
        return JSONResponse(profile.to_json())

    @app.put("/api/profile")
    async def put_profile(request: Request):
        if st.store is None:
            raise CognitsError("store not initialized", "ERROR", 500)
        try:
            body = await request.json()
            if not isinstance(body, dict):
                raise ValueError("body")
            profile = StudentProfile.from_json(body)
        except (json.JSONDecodeError, ValueError, TypeError, UnicodeDecodeError):
            raise CognitsError("invalid body", "ERROR", 400)
        try:
            await asyncio.to_thread(st.store.save_profile, profile)
        except Exception as e:
            raise CognitsError(str(e), "ERROR", 500)
        return Response(status_code=204)

    @app.delete("/api/setup/state")
    async def delete_setup_state():
        if st.store is None:
            raise CognitsError("store not initialized", "ERROR", 500)
        try:
            await asyncio.to_thread(st.store.reset_setup_state)
        except Exception as e:
            raise CognitsError(str(e), "ERROR", 500)
        st.cached_config = Config()
        return Response(status_code=204)

    @app.post("/api/config/test-key")
    async def test_key(request: Request):
        try:
            body = await request.json()
            api_key = body.get("apiKey", "")
        except (json.JSONDecodeError, ValueError):
            raise CognitsError("invalid body", "ERROR", 400)
        if not api_key:
            return JSONResponse({"valid": False, "error": "No API key provided"})
        try:
            import httpx
            async with httpx.AsyncClient(timeout=httpx.Timeout(
                connect=LLM_CONNECT_TIMEOUT, read=LLM_READ_TIMEOUT,
                write=LLM_WRITE_TIMEOUT, pool=LLM_POOL_TIMEOUT,
            )) as client:
                resp = await client.post(
                    LLM_BASE_URL,
                    headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                    json={
                        "model": DEFAULT_FLASH_MODEL,
                        "messages": [{"role": "user", "content": "Hi"}],
                        "max_tokens": 1,
                        "stream": False,
                    },
                )
            if resp.status_code == 200:
                return JSONResponse({"valid": True, "error": ""})
            if resp.status_code == 401:
                return JSONResponse({"valid": False, "error": "Invalid API key"})
            if resp.status_code == 402:
                return JSONResponse({"valid": False, "error": "Insufficient balance"})
            return JSONResponse({"valid": False, "error": f"HTTP {resp.status_code}"})
        except Exception as e:
            return JSONResponse({"valid": False, "error": f"Connection error: {e}"})
