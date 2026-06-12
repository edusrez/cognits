"""Port of internal/server/config.go."""

from __future__ import annotations

import asyncio
import json

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

from cognits.server.util import mask_key, text_error
from cognits.storage.files import Config

VALID_MODELS = ("deepseek-v4-pro", "deepseek-v4-flash")
VALID_REASONING = ("disabled", "high", "max")


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
            return text_error(str(e), 500)

        return JSONResponse(_config_response(cfg))

    @app.put("/api/config")
    async def put_config(request: Request):
        if st.store is None:
            return text_error("store not initialized", 500)

        try:
            body = await request.json()
            if not isinstance(body, dict):
                raise ValueError("body")
            cfg = Config.from_json(body)
        except (json.JSONDecodeError, ValueError, TypeError, UnicodeDecodeError):
            return text_error("invalid body", 400)

        if cfg.llm_provider and cfg.llm_provider != "deepseek":
            return text_error("invalid provider", 400)
        if cfg.llm_model and cfg.llm_model not in VALID_MODELS:
            return text_error("invalid model", 400)
        if cfg.llm_reasoning and cfg.llm_reasoning not in VALID_REASONING:
            return text_error("invalid reasoning value", 400)

        current = st.cached_config
        if current is not None:
            if cfg.llm_api_key == mask_key(current.llm_api_key):
                cfg.llm_api_key = current.llm_api_key
            if cfg.tinyfish_api_key == mask_key(current.tinyfish_api_key):
                cfg.tinyfish_api_key = current.tinyfish_api_key

        try:
            await asyncio.to_thread(st.store.save_config, cfg)
        except Exception as e:
            return text_error(str(e), 500)

        st.cached_config = cfg
        return Response(status_code=204)
