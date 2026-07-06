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

    @staticmethod
    def _levenshtein(a: str, b: str) -> int:
        if len(a) < len(b):
            a, b = b, a
        if len(b) == 0:
            return len(a)
        prev = list(range(len(b) + 1))
        for i, ca in enumerate(a, 1):
            curr = [i]
            for j, cb in enumerate(b, 1):
                curr.append(min(
                    curr[j - 1] + 1,
                    prev[j] + 1,
                    prev[j - 1] + (0 if ca == cb else 1),
                ))
            prev = curr
        return prev[-1]

    @staticmethod
    def _fuzzy_match_skills(skills, query: str):
        q = " ".join(query.lower().strip().split())
        for s in skills:
            sn = " ".join(s.name.lower().strip().split())
            if q in sn or sn in q:
                return s
        best = None
        best_dist = 3
        for s in skills:
            sn = " ".join(s.name.lower().strip().split())
            d = SavePedagogicalPlan._levenshtein(q, sn)
            if d < best_dist:
                best = s
                best_dist = d
        return best if best_dist <= 2 else None

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
            match = self._fuzzy_match_skills(skills, skill_name)
        if match is None:
            return tool_error(
                f"skill '{skill_name}' not found in the skill tree. "
                "Use the list_skills or search_skills tool to find the exact name."
            )

        await asyncio.to_thread(
            self.pedagogy.save,
            match.id, plan_md)

        return json.dumps({"skill_id": match.id, "saved": True}, ensure_ascii=False)