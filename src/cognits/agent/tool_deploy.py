"""Port de internal/agent/tools/deploy.go: la tool deploy_subagent."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable

from cognits.agent.agent import Agent, AgentConfig, Emit
from cognits.llm.deepseek import DeepSeekClient
from cognits.llm.types import ROLE_USER, Message
from cognits.storage.db import Report, new_report_id
from cognits.tools import Tool, tool_error

log = logging.getLogger("cognits.deploy")


def extract_title(content: str, fallback: str) -> str:
    for line in content.split("\n"):
        trimmed = line.strip()
        if trimmed.startswith("# "):
            return trimmed[2:]
    if len(fallback) > 80:
        return fallback[:80] + "..."
    return fallback


def extract_summary(content: str) -> str:
    parts: list[str] = []
    total = 0
    in_content = False
    for line in content.split("\n"):
        trimmed = line.strip()
        if trimmed == "":
            if total > 0:
                break
            continue
        if trimmed.startswith("#"):
            if in_content:
                break
            in_content = True
            continue
        if in_content and not trimmed.startswith("**"):
            parts.append(trimmed + " ")
            total += len(trimmed) + 1
        if total > 200:
            break
    return "".join(parts).strip()


class DeploySubagent(Tool):
    def __init__(
        self,
        llm_client: DeepSeekClient,
        report_store,
        subagents: dict[str, AgentConfig],
        session_id: Callable[[], str] | None,
        emit: Emit | None,
        rag_engine=None,
    ):
        self.llm_client = llm_client
        self.report_store = report_store
        self.subagents = subagents
        self.session_id = session_id
        self.emit = emit
        self.rag_engine = rag_engine

    name = "deploy_subagent"
    description = (
        "Deploy a subagent to perform research or analysis. "
        "Use web_researcher for web research with sources."
    )
    schema = {
        "type": "object",
        "properties": {
            "type": {"type": "string", "enum": ["web_researcher"]},
            "query": {"type": "string", "description": "Research task description"},
        },
        "required": ["type", "query"],
    }

    async def execute(self, raw_args: str) -> str:
        try:
            parsed = json.loads(raw_args)
            subagent_type = parsed["type"]
            query = parsed["query"]
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            return tool_error(f"invalid args: {e}")

        cfg = self.subagents.get(subagent_type)
        if cfg is None:
            return tool_error(f"unknown subagent: {subagent_type}")

        sid = self.session_id() if self.session_id is not None else ""
        report_id = new_report_id()

        subagent = Agent(cfg, self.llm_client)

        def emit(ev: dict) -> None:
            if self.emit is None:
                return
            t = ev["type"]
            if t == "reasoning":
                self.emit({"type": "tool_progress", "data": {"message": "Pensando..."}})
                return
            if t == "token":
                return
            if t == "tool_start":
                data = ev.get("data")
                tool = data.get("tool", "") if isinstance(data, dict) else ""
                msg = "Buscando en la Web"
                if tool == "tinyfish_fetch_content":
                    msg = "Leyendo Resultados"
                self.emit({"type": "tool_progress", "data": {"message": msg}})
                return
            self.emit(ev)

        try:
            content = await subagent.run([Message(role=ROLE_USER, content=query)], emit)
        except asyncio.CancelledError:
            # Cancelado: sin informe, sin indexado, sin subagent_end. El run
            # padre corta limpio cuando la cancelación se propaga.
            raise
        except Exception as e:
            # Fallo real: limpiar el banner de estado y devolver el error al
            # orquestador como resultado de tool, sin crear un informe basura.
            if self.emit is not None:
                self.emit({"type": "tool_progress", "data": {"message": ""}})
            return tool_error(f"subagent failed: {e}")

        title = extract_title(content, query)
        summary = extract_summary(content)

        report = Report(
            id=report_id,
            session_id=sid,
            title=title,
            content=content,
            summary=summary,
            sources=[],
            subagent=subagent_type,
        )

        if self.report_store is not None:
            try:
                await asyncio.to_thread(self.report_store.save, report)
            except Exception as e:
                log.error("deploy: save report %s: %s", report_id, e)

        if self.rag_engine is not None and content:
            from cognits.rag.chunker import split_markdown

            chunks = split_markdown(content, report_id, title)
            if chunks:
                try:
                    n = await self.rag_engine.index(chunks)
                    log.info("deploy: indexed %d chunks for report %s", n, report_id)
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    log.error("deploy: index chunks (report %s): %s", report_id, e)

        if self.emit is not None:
            self.emit(
                {
                    "type": "subagent_end",
                    "data": {"reportId": report_id, "title": title, "summary": summary},
                }
            )

        return json.dumps(
            {
                "reportId": report_id,
                "title": title,
                "summary": summary,
                "content": content,
            },
            ensure_ascii=False,
        )
