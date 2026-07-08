"""check_branch_floor tool — per-branch floor re-check + expand-on-approach.

The maestro calls this before starting a new learning branch. It re-evaluates
whether the learner really masters that branch's prerequisites using the
mastery_judge subagent. Prerequisites that are not mastered get expanded
deeper via skill_branch_builder.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone

from cognits.agent.agent import AgentConfig, Emit
from cognits.agent.agent_loader import load_agent_prompt
from cognits.constants import BRANCH_BUILDER_MAX_STEPS, DEFAULT_MODEL, MASTERY_JUDGE_MAX_STEPS
from cognits.tools import Tool, tool_error

log = logging.getLogger("cognits.floor")


# ---------------------------------------------------------------------------
# CheckBranchFloor
# ---------------------------------------------------------------------------


class CheckBranchFloor(Tool):
    """Verify the learner's floor for a branch before teaching it.

    Re-assesses prerequisite mastery from the learner's profile + chat
    history; expands the tree deeper if a prerequisite is not mastered.
    """

    def __init__(
        self,
        skills,
        learner_state,
        messages,
        llm_client,
        rag_engine,
        tf_client,
        reports,
        assessment,
        session_id,
        emit: Emit | None = None,
        tinyfish_api_key: str = "",
    ):
        self.skills = skills
        self.learner_state = learner_state
        self.messages = messages
        self.llm_client = llm_client
        self.rag_engine = rag_engine
        self.tf_client = tf_client
        self.reports = reports
        self.assessment = assessment
        self.session_id = session_id
        self.emit = emit
        self.tinyfish_api_key = tinyfish_api_key

        from cognits.agent.tool_deploy import DeploySubagent

        mastery_cfg = AgentConfig(
            name="mastery_judge",
            model=DEFAULT_MODEL,
            reasoning="max",
            max_steps=MASTERY_JUDGE_MAX_STEPS,
            temperature=0.0,
            system_prompt=load_agent_prompt("mastery_judge"),
            tools=None,
            internal=True,
        )

        from cognits.agent.subagents import skill_branch_builder_config

        bb_cfg = skill_branch_builder_config(
            model=DEFAULT_MODEL,
            reasoning="max",
            max_steps=BRANCH_BUILDER_MAX_STEPS,
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
            subagents={
                "mastery_judge": mastery_cfg,
                "skill_branch_builder": bb_cfg,
            },
            session_id=session_id,
            emit=emit,
            rag_engine=rag_engine,
            tinyfish_api_key=tinyfish_api_key,
        )

    name = "check_branch_floor"
    description = (
        "Verify the learner's floor for a branch before teaching it. "
        "Re-assesses prerequisite mastery from the learner's profile + "
        "chat history; expands the tree deeper if a prerequisite is not "
        "mastered. Call this before starting a new topic or sub-tree."
    )
    schema = {
        "type": "object",
        "properties": {
            "skill_id": {
                "type": "string",
                "description": "The branch root skill ID to check.",
            }
        },
        "required": ["skill_id"],
    }

    # ------------------------------------------------------------------

    async def execute(self, raw_args: str) -> str:
        try:
            args = json.loads(raw_args)
            skill_id = args["skill_id"]
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            return tool_error(f"invalid args: {e}")

        # Emit tool_start for visibility.
        if self.emit is not None:
            self.emit({
                "type": "tool_start",
                "data": {"tool": self.name, "args": json.dumps(args)},
            })

        # 1. Get branch root skill + immediate prereqs.
        branch_root = await asyncio.to_thread(self.skills.get, skill_id)
        if branch_root is None:
            return tool_error(f"unknown skill_id: {skill_id}")

        prereqs = await asyncio.to_thread(self.skills.get_prerequisites, skill_id)

        # 2. No prereqs → the branch root IS the floor.
        if not prereqs:
            result = json.dumps(
                {
                    "branch_root": skill_id,
                    "prereqs_checked": [],
                    "floor_confirmed": True,
                    "expanded_skills": [],
                    "expanded_count": 0,
                    "pruned_skills": [],
                    "pruned_count": 0,
                },
                ensure_ascii=False,
            )
            if self.emit is not None:
                self.emit({"type": "tool_end", "data": {"tool": self.name, "result": result}})
            return result

        # 3. Load chat history summary.
        history_summary = await self._load_history_summary()

        # 4. Build learner profile string.
        profile_str = await self._build_profile_str()

        # 5. Check each prereq.
        prereqs_checked = []
        not_mastered = []

        for pr in prereqs:
            prereq_skill = await asyncio.to_thread(self.skills.get, pr.prereq_id)
            if prereq_skill is None:
                prereqs_checked.append({
                    "skill_id": pr.prereq_id,
                    "name": "",
                    "mastery": "not_mastered",
                    "confidence": 100,
                })
                not_mastered.append(pr.prereq_id)
                continue

            # B2: Load BKT state for hybrid auto-gates.
            prereq_state = None
            if self.learner_state is not None:
                try:
                    prereq_state = await asyncio.to_thread(self.learner_state.get, prereq_skill.id)
                except Exception:
                    pass

            # Auto-mastered: BKT says mastered with high confidence -> skip LLM.
            if (prereq_state is not None
                    and prereq_state.p_mastery >= 0.95
                    and (prereq_state.alpha + prereq_state.beta) >= 12
                    and prereq_state.reps >= 3):
                prereqs_checked.append({
                    "skill_id": pr.prereq_id,
                    "name": prereq_skill.name,
                    "mastery": "mastered",
                    "confidence": 100,
                })
                log.info("floor: auto-mastered %s via BKT (p=%.2f, conf=%.1f, reps=%d)",
                         prereq_skill.id, prereq_state.p_mastery,
                         prereq_state.alpha + prereq_state.beta, prereq_state.reps)
                continue

            # Auto-not-mastered: no evidence at all -> skip LLM.
            if (prereq_state is None
                    or (prereq_state.reps == 0 and prereq_state.status_enum == "not_seen")):
                prereqs_checked.append({
                    "skill_id": pr.prereq_id,
                    "name": prereq_skill.name,
                    "mastery": "not_mastered",
                    "confidence": 100,
                })
                not_mastered.append(pr.prereq_id)
                log.info("floor: auto-not-mastered %s (no evidence)", prereq_skill.id)
                continue

            # LLM path: pass BKT state for informed judgment.
            bkt_str = ""
            if prereq_state is not None:
                bkt_str = (f" | bkt_state: p_mastery={prereq_state.p_mastery:.2f}, "
                           f"confidence={prereq_state.alpha + prereq_state.beta:.1f}, "
                           f"reps={prereq_state.reps}, "
                           f"stability={prereq_state.stability or 'N/A'}, "
                           f"retrievability={prereq_state.retrievability or 'N/A'}, "
                           f"status={prereq_state.status_enum}")

            query = (
                f"{prereq_skill.id} | {prereq_skill.name} | "
                f"{prereq_skill.description or 'no description'} | "
                f"profile: {profile_str}"
                f"{bkt_str} | "
                f"chat_history: {history_summary}"
            )

            judgment = await self._deploy_mastery_judge(query)
            prereqs_checked.append({
                "skill_id": pr.prereq_id,
                "name": prereq_skill.name,
                "mastery": judgment.get("mastery", "not_mastered"),
                "confidence": judgment.get("confidence", 100),
            })

            if judgment.get("mastery", "not_mastered") in ("not_mastered", "uncertain"):
                not_mastered.append(pr.prereq_id)

        # 6. For not_mastered prereqs, expand the tree via branch_builder.
        expanded_skills = []
        if not_mastered:
            existing_before = {s.id for s in await asyncio.to_thread(self.skills.list_active)}

            for nm_id in not_mastered:
                nm_skill = await asyncio.to_thread(self.skills.get, nm_id)
                if nm_skill is None:
                    continue

                bb_query = (
                    f"branch_root_skill_id: {nm_id} | "
                    f"goal_context: the learner is starting a branch but "
                    f"doesn't master '{nm_skill.name}' — decompose it "
                    f"top-down to their floor | "
                    f"learner_profile: {profile_str} | "
                    f"chat_history: {history_summary}"
                )

                try:
                    result_raw = await self._deploy.execute(
                        json.dumps({"type": "skill_branch_builder", "query": bb_query})
                    )
                    result_data = json.loads(result_raw)
                    if "error" in result_data:
                        log.warning("floor: branch_builder for %s failed: %s", nm_id, result_data["error"])
                except Exception as e:
                    log.error("floor: branch_builder for %s error: %s", nm_id, e)

            # Collect newly-added skills.
            existing_after = {s.id for s in await asyncio.to_thread(self.skills.list_active)}
            for sid in existing_after - existing_before:
                s = await asyncio.to_thread(self.skills.get, sid)
                if s:
                    expanded_skills.append({"skill_id": s.id, "name": s.name, "domain": s.domain})

        # 7. SHRINK: prune over-decomposed sub-trees for mastered prereqs.
        # If a prereq is mastered (confidence>=70) AND has its own prereqs
        # (a sub-tree decomposition), the learner doesn't need those deeper
        # decompositions — the mastered prereq becomes a floor leaf.
        pruned_skills = []
        for pc in prereqs_checked:
            if pc["mastery"] == "mastered" and pc["confidence"] >= 70:
                sub_tree_ids: set[str] = set()
                queue: list[str] = [pc["skill_id"]]
                while queue:
                    current = queue.pop(0)
                    current_prereqs = await asyncio.to_thread(
                        self.skills.get_prerequisites, current
                    )
                    for sp in current_prereqs:
                        if sp.prereq_id not in sub_tree_ids:
                            sub_tree_ids.add(sp.prereq_id)
                            queue.append(sp.prereq_id)
                for sid in sorted(sub_tree_ids):
                    await asyncio.to_thread(self.skills.delete_skill, sid)
                    pruned_skills.append({"skill_id": sid, "mastered_prereq": pc["skill_id"]})

        floor_confirmed = len(expanded_skills) == 0

        result = json.dumps(
            {
                "branch_root": skill_id,
                "prereqs_checked": prereqs_checked,
                "floor_confirmed": floor_confirmed,
                "expanded_skills": expanded_skills,
                "expanded_count": len(expanded_skills),
                "pruned_skills": pruned_skills,
                "pruned_count": len(pruned_skills),
            },
            ensure_ascii=False,
        )

        if self.emit is not None:
            self.emit({"type": "tool_end", "data": {"tool": self.name, "result": result}})

        return result

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    async def _load_history_summary(self) -> str:
        sid = self.session_id() if callable(self.session_id) else self.session_id
        if not sid:
            return "(no chat history)"
        try:
            rows = await asyncio.to_thread(self.messages.load, sid)
        except Exception:
            return "(chat history unavailable)"

        user_content = []
        for r in rows[-20:]:
            if r.role in ("user", "hidden_user", "assistant"):
                user_content.append(f"[{r.role}]: {r.content[:200]}")

        summary = "\n".join(user_content)
        if len(summary) > 2000:
            summary = summary[:1997] + "..."
        return summary or "(no chat history)"

    async def _build_profile_str(self) -> str:
        try:
            all_states = await asyncio.to_thread(self.learner_state.get_all)
        except Exception:
            return "(no learner profile)"
        if not all_states:
            return "(no learner profile)"
        # get_all returns dict[str, LearnerState].
        states_list = list(all_states.values())
        sorted_states = sorted(states_list, key=lambda ls: ls.p_mastery or 0.0, reverse=True)
        top = sorted_states[:10]
        parts = [f"{ls.skill_id}: p={ls.p_mastery:.2f} status={ls.status_enum}" for ls in top]
        profile = "Known skills (top 10 by mastery): " + " | ".join(parts)
        if len(sorted_states) > 10:
            profile += f" | ... ({len(sorted_states)} total)"
        return profile

    async def _deploy_mastery_judge(self, query: str) -> dict:
        try:
            raw = await self._deploy.execute(
                json.dumps({"type": "mastery_judge", "query": query})
            )
            data = json.loads(raw)
            if "error" in data:
                log.warning("floor: mastery_judge error: %s", data["error"])
                return {"mastery": "not_mastered", "confidence": 100, "reasoning": "judgment failed"}
            # The deploy returns {reportId, title, summary, content} — we need
            # to parse the JSON from the content.
            content = data.get("content", "")
            if not content:
                return {"mastery": "not_mastered", "confidence": 100, "reasoning": "empty response"}
            # Try to parse JSON from the content.
            try:
                return json.loads(content)
            except json.JSONDecodeError:
                # Maybe the content has surrounding text — try to find JSON in it.
                return json.loads(content)
        except Exception as e:
            log.error("floor: mastery_judge deploy failed: %s", e)
            return {"mastery": "not_mastered", "confidence": 100, "reasoning": f"error: {e}"}
