"""refocus_tree tool — re-decompose the skill tree on goal change.

The maestro calls this when the learner changes their goal or re-focuses.
It deploys the goal_decomposer (skill_planner) which handles pruning obsolete
branches and adding new ones for the new goal/focus.
"""

from __future__ import annotations

import json
import logging

from cognits.agent.agent import AgentConfig, Emit
from cognits.agent.agent_loader import load_agent_prompt
from cognits.constants import (
    BRANCH_BUILDER_MAX_STEPS,
    DEFAULT_MODEL,
    RESEARCHER_MAX_STEPS,
)
from cognits.tools import Tool, tool_error

log = logging.getLogger("cognits.refocus")


class RefocusTree(Tool):
    """Re-decompose the skill tree when the learner changes their goal.

    Deploys the skill_planner (goal_decomposer) with the new goal + focus
    + existing tree context. The planner handles pruning obsolete branches
    and adding new ones.
    """

    def __init__(
        self,
        skills,
        learner_state,
        assessment,
        llm_client,
        rag_engine,
        tf_client,
        reports,
        session_id,
        emit: Emit | None = None,
        tinyfish_api_key: str = "",
    ):
        self.skills = skills
        self.learner_state = learner_state
        self.llm_client = llm_client
        self.rag_engine = rag_engine
        self.tf_client = tf_client
        self.reports = reports
        self.session_id = session_id
        self.emit = emit
        self.tinyfish_api_key = tinyfish_api_key

        from cognits.agent.tool_deploy import DeploySubagent
        from cognits.agent.subagents import (
            skill_planner_config,
            skill_branch_builder_config,
        )
        from cognits.agent.subagents import new_researcher_tools

        # Build skill_planner (goal_decomposer) config inline.
        planner_cfg = skill_planner_config(
            model=DEFAULT_MODEL,
            reasoning="max",
            max_steps=100,
            llm_client=llm_client,
            rag_engine=rag_engine,
            tf_client=tf_client,
            reports=reports,
            skills=skills,
            assessment=assessment,
            learner_state=learner_state,
            session_id=session_id,
            emit=emit,
            tinyfish_api_key=tinyfish_api_key,
        )

        self._deploy = DeploySubagent(
            llm_client=llm_client,
            reports=reports,
            subagents={"skill_planner": planner_cfg},
            session_id=session_id,
            emit=emit,
            rag_engine=rag_engine,
            tinyfish_api_key=tinyfish_api_key,
        )

    name = "refocus_tree"
    description = (
        "Re-decompose the skill tree when the learner changes their goal "
        "or re-focuses. Prunes obsolete branches + adds new ones for the "
        "new goal/focus. Use when the learner expresses a goal change or "
        "a major re-focus (e.g. 'actually I want to focus on X' or 'I "
        "changed my goal to Y')."
    )
    schema = {
        "type": "object",
        "properties": {
            "new_goal": {
                "type": "string",
                "description": "The new/updated learning goal.",
            },
            "focus": {
                "type": "string",
                "description": "A specific area to focus on, if not a full goal change.",
            },
            "learner_profile": {
                "type": "string",
                "description": "The learner's profile summary, to re-assess the floor.",
            },
        },
        "required": ["new_goal", "learner_profile"],
    }

    # ------------------------------------------------------------------

    async def execute(self, raw_args: str) -> str:
        try:
            args = json.loads(raw_args)
            new_goal = args["new_goal"]
            focus = args.get("focus", "")
            profile = args["learner_profile"]
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            return tool_error(f"invalid args: {e}")

        if self.emit is not None:
            self.emit({
                "type": "tool_start",
                "data": {"tool": self.name, "args": json.dumps(args)},
            })

        # Summarize the current tree's top-level branches for context.
        active = await self._skills_list_active()
        top_level = [s for s in active if self._is_top_level(await self._get_prereqs(s.id))]
        tree_summary = "\n".join(
            f"- {s.id} | {s.domain} | {s.name} | {s.bloom_level or 'none'}"
            for s in top_level[:20]
        ) or "(empty tree)"

        query = (
            f"RE-FOCUS: new goal: {new_goal} | "
            + (f"focus: {focus} | " if focus else "")
            + f"learner_profile: {profile} | "
            f"existing_tree: {tree_summary} | "
            f"task: re-decompose for the new goal — identify which existing "
            f"branches are still relevant (keep), which are obsolete "
            f"(call delete_skill to prune), which are new "
            f"(upsert_skill + add_edge + decompose via branch_builders). "
            f"The tree MUTATES to the new goal."
        )

        try:
            result_raw = await self._deploy.execute(
                json.dumps({"type": "skill_planner", "query": query})
            )
            result_data = json.loads(result_raw)
            if "error" in result_data:
                log.warning("refocus: skill_planner deploy failed: %s", result_data["error"])
                return json.dumps({
                    "refocused": False,
                    "error": result_data["error"],
                    "new_goal": new_goal,
                }, ensure_ascii=False)

            summary = result_data.get("summary", "")
            content = result_data.get("content", "")

            # Count active skills after the re-decomposition.
            active_after = await self._skills_list_active()

            result_final = json.dumps({
                "refocused": True,
                "new_goal": new_goal,
                "skill_count": len(active_after),
                "summary": summary or content[:500],
            }, ensure_ascii=False)

            if self.emit is not None:
                self.emit({"type": "tool_end", "data": {"tool": self.name, "result": result_final}})

            return result_final

        except Exception as e:
            log.error("refocus: deploy failed: %s", e)
            return json.dumps({
                "refocused": False,
                "error": str(e),
                "new_goal": new_goal,
            }, ensure_ascii=False)

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    async def _skills_list_active(self):
        import asyncio
        return await asyncio.to_thread(self.skills.list_active)

    async def _get_prereqs(self, skill_id: str):
        import asyncio
        return await asyncio.to_thread(self.skills.get_prerequisites, skill_id)

    @staticmethod
    def _is_top_level(prereqs) -> bool:
        """A skill is top-level if it has no prereqs (it's a root)."""
        return len(prereqs) == 0
