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

from cognits.storage.assessment import AssessmentItemRepository
from cognits.storage.models import (
    EDGE_TYPES,
    AssessmentItem,
    LearnerState,
    Skill,
    new_assessment_item_id,
    new_skill_id,
)
from cognits.tools import Tool, tool_error


class SkillTreeSave(Tool):
    def __init__(
        self,
        skills,
        assessment: AssessmentItemRepository,
        session_id: Callable[[], str] | None = None,
        emit=None,
    ):
        self.skills = skills
        self.assessment = assessment
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
                "enum": ["start_build", "upsert_skill", "add_edge", "finish_build", "save_assessment_items", "list_assessment_items"],
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
                "description": "add_edge: 'prereq' (AND, all must be mastered), 'alt_prereq' (OR, any one in same group_id satisfies — requires group_id), 'coreq' (taken together), 'related' (loose link), 'soft_prereq' (bonus, never blocks).",
            },
            "group_id": {
                "type": "string",
                "description": "add_edge: REQUIRED for edge_type='alt_prereq'. Shared identifier for OR-alternatives — edges with the same group_id form an OR-set.",
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
            "items": {
                "type": "array",
                "description": "save_assessment_items: array of item objects. Each must have: question, expected_answer, rubric, question_type, blooms_level, difficulty, generation_model. Optional: rubric_criteria.",
                "items": {"type": "object"},
            },
            "include_all": {
                "type": "boolean",
                "description": "list_assessment_items (optional): include inactive items too (default false).",
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
        if action == "save_assessment_items":
            return await self._save_assessment_items(args)
        if action == "list_assessment_items":
            return await self._list_assessment_items(args)
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
        group_id = args.get("group_id", "")
        # Validate alt_prereq requires group_id (redundant with repo-side
        # check, but gives the LLM a friendlier tool_error).
        if edge_type == "alt_prereq" and not group_id:
            return tool_error("alt_prereq requires group_id")
        try:
            await asyncio.to_thread(
                self.skills.add_edge,
                skill_id,
                prereq_id,
                edge_type,
                proof_query,
                build_id,
                group_id,
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

        # Count how many active skills have < 3 assessment items (best-effort).
        try:
            all_skills = await asyncio.to_thread(self.skills.list_active)
            if all_skills:
                skill_ids = [s.id for s in all_skills]
                items = await asyncio.to_thread(self.assessment.list_for_skills, skill_ids, True)
                counts: dict[str, int] = {}
                for it in items:
                    counts[it.skill_id] = counts.get(it.skill_id, 0) + 1
                n_underitemed = sum(1 for sid in skill_ids if counts.get(sid, 0) < 3)
                summary += f" | {n_underitemed}/{len(skill_ids)} skills have <3 assessment items"
        except Exception:
            pass

        await asyncio.to_thread(
            self.skills.finish_build, build_id, summary, status
        )
        return json.dumps({"ok": True}, ensure_ascii=False)

    async def _save_assessment_items(self, args: dict) -> str:
        skill_id = args.get("skill_id")
        items = args.get("items")
        if not skill_id:
            return tool_error("save_assessment_items requires 'skill_id'")
        if not isinstance(items, list) or len(items) == 0:
            return tool_error("save_assessment_items requires non-empty 'items' array")

        existing = await asyncio.to_thread(self.skills.get, skill_id)
        if existing is None:
            return tool_error(f"skill_id '{skill_id}' does not exist")

        warning = None
        if len(items) < 3:
            warning = "fewer than 3 items — BKT reliability may suffer"

        saved_ids = []
        for it in items:
            item_id = it.get("id") or new_assessment_item_id()
            rubric_criteria = it.get("rubric_criteria")
            rc_json = None
            if isinstance(rubric_criteria, list):
                rc_json = rubric_criteria
            ai = AssessmentItem(
                id=item_id,
                skill_id=skill_id,
                skill_ids=[skill_id],
                question=it.get("question", ""),
                question_type=it.get("question_type", "open"),
                expected_answer=it.get("expected_answer", ""),
                rubric=it.get("rubric", ""),
                rubric_criteria=rc_json,
                rubric_type=it.get("rubric_type", "analytic"),
                blooms_level=it.get("blooms_level", ""),
                difficulty=float(it.get("difficulty", 0.5)),
                irt_model=it.get("irt_model", "heuristic"),
                generation_model=it.get("generation_model", ""),
                generation_prompt_hash=it.get("generation_prompt_hash", ""),
                source=it.get("source", ""),
                seed_version=int(it.get("seed_version", 1)),
                times_presented=int(it.get("times_presented", 0)),
                times_correct=int(it.get("times_correct", 0)),
                status=it.get("status", "active"),
            )
            await asyncio.to_thread(self.assessment.save, ai)
            saved_ids.append(item_id)

        response = {"saved": len(saved_ids), "item_ids": saved_ids}
        if warning:
            response["warning"] = warning
        return json.dumps(response, ensure_ascii=False)

    async def _list_assessment_items(self, args: dict) -> str:
        skill_id = args.get("skill_id")
        if not skill_id:
            return tool_error("list_assessment_items requires 'skill_id'")
        include_all = bool(args.get("include_all", False))
        items = await asyncio.to_thread(
            self.assessment.list_for_skill, skill_id, include_all
        )
        item_dicts = []
        for ai in items:
            item_dicts.append({
                "id": ai.id,
                "skill_id": ai.skill_id,
                "skill_ids": ai.skill_ids,
                "question": ai.question,
                "question_type": ai.question_type,
                "expected_answer": ai.expected_answer,
                "rubric": ai.rubric,
                "rubric_criteria": ai.rubric_criteria,
                "rubric_type": ai.rubric_type,
                "blooms_level": ai.blooms_level,
                "difficulty": ai.difficulty,
                "p_value": ai.p_value,
                "irt_a": ai.irt_a,
                "irt_b": ai.irt_b,
                "irt_c": ai.irt_c,
                "irt_model": ai.irt_model,
                "generation_model": ai.generation_model,
                "generation_prompt_hash": ai.generation_prompt_hash,
                "template_id": ai.template_id,
                "source": ai.source,
                "seed_version": ai.seed_version,
                "times_presented": ai.times_presented,
                "times_correct": ai.times_correct,
                "avg_response_time_ms": ai.avg_response_time_ms,
                "status": ai.status,
                "reviewed_by": ai.reviewed_by,
                "created_at": ai.created_at,
                "updated_at": ai.updated_at,
            })
        return json.dumps({"items": item_dicts}, ensure_ascii=False)