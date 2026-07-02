"""save_pedagogical_plan tool — called by the Study Planner to persist
a stage-based teaching guide after synthesising it from web research."""

from __future__ import annotations

import asyncio
import json

from cognits.tools import Tool, tool_error


class SavePedagogicalPlan(Tool):
    def __init__(self, skills=None, pedagogy=None):
        self.skills = skills
        self.pedagogy = pedagogy

    name = "save_pedagogical_plan"
    description = (
        "Persist a pedagogical plan (stage-based teaching guide in Markdown) "
        "for a skill. Call this after synthesising a plan from web research "
        "so the Teacher can retrieve it during a learning session. "
        "Overwrites any previous plan for the same skill."
    )
    schema = {
        "type": "object",
        "properties": {
            "skill_name": {
                "type": "string",
                "description": "Name of the skill this plan is for (must match an existing skill in the tree).",
            },
            "plan_markdown": {
                "type": "string",
                "description": "The stage-based pedagogical plan as Markdown.",
            },
        },
        "required": ["skill_name", "plan_markdown"],
    }

    async def execute(self, raw_args: str) -> str:
        try:
            args = json.loads(raw_args)
            skill_name = args["skill_name"].strip()
            plan_md = args["plan_markdown"]
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            return tool_error(f"invalid args: {e}")

        if not skill_name or not plan_md.strip():
            return tool_error("skill_name and plan_markdown are required")

        skills = await asyncio.to_thread(self.skills.list_active)
        match = next((s for s in skills if s.name.lower() == skill_name.lower()), None)
        if match is None:
            return tool_error(
                f"skill '{skill_name}' not found in the skill tree. "
                "Use the exact skill name as it appears in the tree."
            )

        await asyncio.to_thread(self.store.save, match.id, plan_md)

        return json.dumps({"skill_id": match.id, "saved": True}, ensure_ascii=False)