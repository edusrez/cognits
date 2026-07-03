"""plan_study tool — called by the Study Planner subagent to generate
a study plan from the user's goal, skill tree, and learner states.

The tool wraps the deterministic ``learner.planner`` algorithm and persists
the result in ``study_plans`` / ``study_plan_items`` via ReportStore.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable

from cognits.learner import planner
from cognits.constants import STUDY_PLAN_MAX_ITEMS
from cognits.storage.models import StudyPlanItem
from cognits.tools import Tool, tool_error


def _parse_priority_list(raw) -> list[str]:
    if not isinstance(raw, list):
        return []
    return [str(v).strip() for v in raw if isinstance(v, str) and v.strip()]


class PlanStudy(Tool):
    def __init__(
        self,
        plans=None,
        skills=None,
        learner_state=None,
        session_id: Callable[[], str] | None = None,
    ):
        self.plans = plans
        self.skills = skills
        self.learner_state = learner_state
        self.session_id = session_id

    name = "plan_study"
    description = (
        "Generate or refresh a study plan for the user's learning goal. "
        "The tool computes the knowledge frontier (ALEKS outer fringe), "
        "ranks skills by spaced-repetition urgency, goal proximity, "
        "mastery gap, difficulty, and user priorities, then persists "
        "the plan as an ordered list of learning sessions. Returns the "
        "plan ID, the items, and (when a previous plan existed) a diff."
    )
    schema = {
        "type": "object",
        "properties": {
            "goal": {
                "type": "string",
                "description": "The skill name the user ultimately wants to learn (must match a skill name in the tree).",
            },
            "priorities": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Skill names the user explicitly asked to focus on. Optional.",
            },
            "max_items": {
                "type": "integer",
                "description": "How many plan items to generate (default 7).",
            },
        },
        "required": ["goal"],
    }

    async def execute(self, raw_args: str) -> str:
        try:
            args = json.loads(raw_args)
            goal = args["goal"]
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            return tool_error(f"invalid args: {e}")

        priorities = _parse_priority_list(args.get("priorities", []))
        max_items = int(args.get("max_items", planner.MAX_PLAN_ITEMS))
        if max_items < 1:
            max_items = 1
        if max_items > STUDY_PLAN_MAX_ITEMS:
            max_items = STUDY_PLAN_MAX_ITEMS

        sid = self.session_id() if self.session_id is not None else ""

        try:
            # 1. Load FULL skill tree + all learner states.
            tree = await asyncio.to_thread(self.skills.get_tree)
            skills_raw = tree.get("skills", [])
            edges_raw = tree.get("edges", [])
            tree_version = tree.get("treeVersion", 1)

            # Turn dicts into dataclasses locally.
            from cognits.storage.models import Skill, SkillPrereq, LearnerState

            skill_map: dict[str, Skill] = {}
            for d in skills_raw:
                s = Skill(
                    id=d["id"],
                    domain=d.get("domain", ""),
                    name=d.get("name", ""),
                    description=d.get("description", ""),
                    bloom_level=d.get("bloomLevel", ""),
                    difficulty=float(d.get("difficulty", 0.5)),
                )
                skill_map[s.id] = s
            skills = list(skill_map.values())

            edges = [
                SkillPrereq(
                    skill_id=e["skillId"],
                    prereq_id=e["prereqId"],
                    edge_type=e.get("edgeType", "prereq"),
                )
                for e in edges_raw
            ]

            states: dict[str, LearnerState] = {}
            for sid_key in skill_map:
                st = await asyncio.to_thread(self.learner_state.get, sid_key)
                if st is not None:
                    states[sid_key] = st
                else:
                    states[sid_key] = LearnerState(skill_id=sid_key)

            # 2. Generate plan.
            now_iso = None  # use server wall-clock
            items = planner.generate_plan(
                skills=skills, edges=edges, states=states,
                goal=goal, priorities=priorities, max_items=max_items,
                now_iso=now_iso,
            )

            # 3. Diff if an old active plan exists.
            old_plan = await asyncio.to_thread(self.plans.get_active)
            diff: dict | None = None
            if old_plan is not None:
                old_items = await asyncio.to_thread(
                    self.plans.get_items, old_plan.id
                )
                old_goal = old_plan.goal
                diff = planner.diff_plans(
                    old_items=old_items,
                    old_goal=old_goal,
                    new_goal=goal,
                    skills=skills, edges=edges, states=states,
                )

            # 4. Persist: supersede old, create new, replace items.
            if old_plan is not None:
                await asyncio.to_thread(
                    getattr(self.plans, "supersede_plan", self.plans.supersede),
                    old_plan.id)
                # Mark removed items as goal_removed.
                if diff:
                    for ri in diff.get("removed", []):
                        await asyncio.to_thread(
                            self.plans.update_item,
                            ri["id"], status="goal_removed",
                        )

            plan_id = await asyncio.to_thread(
                self.plans.create, tree_version, goal, sid
            )
            await asyncio.to_thread(self.plans.replace_items, plan_id, items)

            # 5. Reload to get timestamps + returned item IDs.
            items_reloaded = await asyncio.to_thread(
                self.plans.get_items, plan_id
            )

            result = {
                "plan_id": plan_id,
                "items": [i.to_json() for i in items_reloaded],
                "treeVersion": tree_version,
                "frontierSize": len(planner.compute_frontier(skills, edges, states)),
            }
            if diff is not None:
                result["diff"] = diff

            return json.dumps(result, ensure_ascii=False)

        except Exception as e:
            return tool_error(str(e))