"""Tool used by the skill_planner subagent to persist a learner's skill
tree node-by-node and edge-by-edge during an iterative build pass.

A single tool with an ``action`` enum keeps the prompt compact (one function
definition vs four) and preserves DeepSeek's prefix-cache ordering
invariant (tools.definitions() is sorted by name).

All persistence goes through ``ReportStore`` (the same handle used by
reports/notes/etc.) which carries its own thread lock. We wrap the sync
calls with ``asyncio.to_thread`` to keep the event loop free, mirroring
``tool_deploy.py``.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable

from cognits.storage.models import (
    EDGE_TYPES,
    LearnerState,
    Skill,
    new_skill_id,
)
from cognits.tools import Tool, tool_error


class SkillTreeSave(Tool):
    def __init__(
        self,
        skills,
        session_id: Callable[[], str] | None = None,
        emit=None,
    ):
        self.skills = skills
        self.session_id = session_id
        self.emit = emit

    name = "skill_tree_save"
    description = (
        "Persist a piece of the learner's skill tree atomically. Call "
        "repeatedly while building the tree: open a build pass, upsert "
        "nodes, add typed prerequisite edges, then close the build. Each "
        "call commits to durable storage so partial progress survives "
        "cancellation."
    )
    schema = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["start_build", "upsert_skill", "add_edge", "finish_build"],
                "description": "Which tree mutation to perform.",
            },
            "trigger": {
                "type": "string",
                "description": "start_build: short label for what triggered the pass (e.g. 'onboarding').",
            },
            "build_id": {
                "type": "string",
                "description": "add_edge/finish_build: build id returned by start_build.",
            },
            "domain": {
                "type": "string",
                "description": "upsert_skill: coarse domain the skill belongs to (e.g. 'python', 'algebra').",
            },
            "name": {
                "type": "string",
                "description": "upsert_skill: human-readable skill name.",
            },
            "description": {
                "type": "string",
                "description": "upsert_skill: 1-2 sentence description of what the skill entails.",
            },
            "bloom_level": {
                "type": "string",
                "description": "upsert_skill (optional): Bloom's level (remember/understand/apply/analyze/evaluate/create).",
            },
            "difficulty": {
                "type": "number",
                "description": "upsert_skill (optional): 0.0-1.0 estimate of how hard the skill is for a beginner.",
            },
            "parent_skill_id": {
                "type": "string",
                "description": "upsert_skill (optional): id of the parent skill in the tree (for hierarchical grouping).",
            },
            "skill_id": {
                "type": "string",
                "description": "add_edge: id of the skill that has the prerequisite.",
            },
            "prereq_id": {
                "type": "string",
                "description": "add_edge: id of the skill that is the prerequisite.",
            },
            "edge_type": {
                "type": "string",
                "enum": list(EDGE_TYPES),
                "description": "add_edge: 'prereq' (must learn first), 'coreq' (taken together), 'related' (loose link).",
            },
            "proof_query": {
                "type": "string",
                "description": "add_edge (optional): web search query that justified this prerequisite relationship.",
            },
            "summary": {
                "type": "string",
                "description": "finish_build: human-readable synthesis of what the pass produced (domains, counts, depth).",
            },
            "status": {
                "type": "string",
                "description": "finish_build (optional): 'done' (default) or 'partial' if the pass ended early.",
            },
        },
        "required": ["action"],
    }

    async def execute(self, raw_args: str) -> str:
        try:
            args = json.loads(raw_args)
            action = args["action"]
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            return tool_error(f"invalid args: {e}")

        if action == "start_build":
            return await self._start_build(args)
        if action == "upsert_skill":
            return await self._upsert_skill(args)
        if action == "add_edge":
            return await self._add_edge(args)
        if action == "finish_build":
            return await self._finish_build(args)
        return tool_error(f"unknown action: {action}")

    async def _start_build(self, args: dict) -> str:
        trigger = args.get("trigger", "")
        sid = self.session_id() if self.session_id is not None else ""
        build_id = await asyncio.to_thread(self.skills.start_build, sid, trigger)
        return json.dumps({"build_id": build_id}, ensure_ascii=False)

    async def _upsert_skill(self, args: dict) -> str:
        name = args.get("name")
        domain = args.get("domain")
        if not name or not domain:
            return tool_error("upsert_skill requires 'name' and 'domain'")
        skill_id = new_skill_id()
        skill = Skill(
            id=skill_id,
            domain=domain,
            name=name,
            description=args.get("description", ""),
            bloom_level=args.get("bloom_level", ""),
            difficulty=float(args.get("difficulty", 0.5)),
            parent_skill_id=args.get("parent_skill_id", "") or "",
            source="skill_planner",
        )
        await asyncio.to_thread(self.skills.upsert, skill)
        return json.dumps({"skill_id": skill_id}, ensure_ascii=False)

    async def _add_edge(self, args: dict) -> str:
        skill_id = args.get("skill_id")
        prereq_id = args.get("prereq_id")
        if not skill_id or not prereq_id:
            return tool_error("add_edge requires 'skill_id' and 'prereq_id'")
        edge_type = args.get("edge_type", "prereq")
        proof_query = args.get("proof_query", "")
        build_id = args.get("build_id", "")
        try:
            await asyncio.to_thread(
                self.skills.add_edge,
                skill_id,
                prereq_id,
                edge_type,
                proof_query,
                build_id,
            )
        except ValueError as e:
            return tool_error(str(e))
        return json.dumps({"ok": True}, ensure_ascii=False)

    async def _finish_build(self, args: dict) -> str:
        build_id = args.get("build_id")
        if not build_id:
            return tool_error("finish_build requires 'build_id'")
        summary = args.get("summary", "")
        status = args.get("status", "done")
        await asyncio.to_thread(
            self.skills.finish_build, build_id, summary, status
        )
        return json.dumps({"ok": True}, ensure_ascii=False)