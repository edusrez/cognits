"""Port of internal/agent/tools/deploy.go: the deploy_subagent tool."""

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

# Display labels for subagent types, used when the outer deploy wrapper
# translates a tool_start(deploy_subagent) into a "Deploying <label>..."
# tool_progress message.
SUBAGENT_LABELS: dict[str, str] = {
    "web_researcher": "Web Researcher",
    "directory_reader": "Directory Reader",
    "skill_planner": "Skill Planner",
    "study_planner": "Study Planner",
    "evaluator": "Evaluator",
    "teacher": "Teacher",
    "session_analyzer": "Session Analyzer",
}


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
        tinyfish_api_key: str = "",
        suspended_subagents: dict[str, list] | None = None,
    ):
        self.llm_client = llm_client
        self.report_store = report_store
        self.subagents = subagents
        self.session_id = session_id
        self.emit = emit
        self.rag_engine = rag_engine
        self.tinyfish_api_key = tinyfish_api_key
        self.suspended_subagents = suspended_subagents if suspended_subagents is not None else {}

    name = "deploy_subagent"
    description = (
        "Deploy a subagent to perform research or analysis. "
        "Use web_researcher for web research with sources, "
        "directory_reader to inspect the project folder, "
        "skill_planner to build or refresh the learner's skill tree "
        "by iterating with web_researcher, "
        "study_planner to generate a study plan from the skill tree."
    )
    schema = {
        "type": "object",
        "properties": {
            "type": {"type": "string", "enum": ["web_researcher", "directory_reader", "documentalist", "session_analyzer", "skill_planner", "study_planner", "evaluator"]},
            "query": {"type": "string", "description": "Task description for the subagent"},
            "thoroughness": {
                "type": "string",
                "enum": ["quick", "high", "max"],
                "description": "Effort calibration for directory_reader. quick=surface, high=thorough, max=exhaustive (uses Pro model). Default: high.",
            },
            "resume_token": {
                "type": "string",
                "description": "Token from a previous deploy_subagent call to resume the same subagent session. Pass this to continue a paused conversation (e.g. Phase 2 of evaluation).",
            },
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

        if subagent_type == "directory_reader":
            thoroughness = parsed.get("thoroughness", "high")
            if thoroughness == "max":
                import dataclasses
                cfg = dataclasses.replace(cfg, model="deepseek-v4-pro", reasoning="max")

        if subagent_type == "skill_planner":
            # The planner iterates with web_researcher and needs the Pro
            # model + max reasoning for deep recursive decomposition. The
            # config normally already carries these values, but overriding
            # here protects against caller-supplied overrides that would
            # cripple it (e.g. a flash default).
            import dataclasses
            cfg = dataclasses.replace(cfg, model="deepseek-v4-pro", reasoning="max")

        if subagent_type in ("web_researcher", "skill_planner") and not self.tinyfish_api_key:
            return tool_error(
                "TinyFish API key not configured. Please configure it in Settings."
            )

        sid = self.session_id() if self.session_id is not None else ""
        report_id = new_report_id()

        resume_token = parsed.get("resume_token") or ""
        if resume_token and self.suspended_subagents:
            # Resume: pop the saved messages, append the new query, and
            # create a fresh Agent with the combined history.  The saved
            # messages already include the system prompt from Phase 1, so
            # Agent.run() won't prepend it again (it only prepends when
            # cfg.system_prompt is set AND the first message isn't system).
            # We strip the old system before saving, so we prepend here.
            saved = self.suspended_subagents.pop(resume_token, None)
            if saved is None:
                return tool_error(f"unknown or expired resume_token: {resume_token}")
            import copy
            messages = copy.deepcopy(list(saved))
            messages.append(Message(role=ROLE_USER, content=query))
        else:
            messages = [Message(role=ROLE_USER, content=query)]

        subagent = Agent(cfg, self.llm_client)

        emitted_first = False
        deploy_count = 0

        def emit(ev: dict) -> None:
            nonlocal emitted_first
            nonlocal deploy_count
            if self.emit is None:
                return
            t = ev["type"]
            if t == "reasoning":
                emitted_first = False
                deploy_count = 0
                self.emit({"type": "tool_progress", "data": {"message": "Thinking...", "agent": cfg.name}})
                return
            if t == "token":
                if not emitted_first:
                    emitted_first = True
                    self.emit({"type": "tool_progress", "data": {"message": "Writing...", "agent": cfg.name}})
                return
            if t == "tool_start":
                emitted_first = False
                data = ev.get("data")
                tool = data.get("tool", "") if isinstance(data, dict) else ""
                if tool == "deploy_subagent":
                    deploy_count += 1
                    raw_args = data.get("args", "{}") if isinstance(data, dict) else "{}"
                    try:
                        sub_type = json.loads(raw_args).get("type", "") if isinstance(data, dict) else ""
                    except Exception:
                        sub_type = ""
                    label = SUBAGENT_LABELS.get(sub_type, sub_type or "subagent")
                    suffix = f" (x{deploy_count})" if deploy_count > 1 else ""
                    msg = f"Deploying {label}{suffix}..."
                    agent = data.get("agent", cfg.name) if isinstance(data, dict) else cfg.name
                    self.emit({"type": "tool_progress", "data": {"message": msg, "agent": agent}})
                    return

                deploy_count = 0
                msg = "Searching the Web..."
                if tool == "tinyfish_fetch_content":
                    msg = "Reading Results..."
                elif tool == "read_file":
                    msg = "Reading file..."
                elif tool == "list_dir":
                    msg = "Listing directory..."
                elif tool == "grep_code":
                    msg = "Searching code..."
                elif tool == "glob_files":
                    msg = "Finding files..."
                agent = data.get("agent", cfg.name) if isinstance(data, dict) else cfg.name
                self.emit({"type": "tool_progress", "data": {"message": msg, "agent": agent}})
                return
            if t == "tool_progress":
                data = ev.get("data")
                if isinstance(data, dict) and "agent" not in data:
                    data["agent"] = cfg.name
                self.emit(ev)
                return
            if ev.get("type") == "usage" and isinstance(ev.get("data"), dict):
                ev["data"]["source"] = "subagent"
            self.emit(ev)

        if cfg.tools is not None:
            cfg.tools.set_emit(emit)

        try:
            content = await subagent.run(messages, emit)
        except asyncio.CancelledError:
            # Cancelled: no report, no indexing, no subagent_end. The parent
            # run stops cleanly when the cancellation propagates.
            raise
        except Exception as e:
            # Real failure: clear the status banner and return the error to the
            # orchestrator as a tool result, without creating a junk report.
            if self.emit is not None:
                self.emit({"type": "tool_progress", "data": {"message": "", "agent": ""}})
            return tool_error(f"subagent failed: {e}")

        title = extract_title(content, query)
        summary = extract_summary(content)

        # Save accumulated messages for future resume if the subagent
        # didn't already use a resume_token (Phase 1 → save for Phase 2).
        # Resume messages are stripped of the leading system prompt so a
        # fresh Agent.run() can prepend it again without duplication.
        new_resume_token = ""
        if not resume_token and subagent.last_messages and self.suspended_subagents is not None:
            saved = subagent.last_messages
            if saved and saved[0].role == "system":
                saved = saved[1:]
            new_resume_token = "resume_" + __import__("secrets").token_hex(8)
            self.suspended_subagents[new_resume_token] = saved

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
                    del chunks
                    import gc; gc.collect()
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

        result = {
            "reportId": report_id,
            "title": title,
            "summary": summary,
            "content": content,
        }
        if new_resume_token:
            result["resume_token"] = new_resume_token
        return json.dumps(result, ensure_ascii=False)
