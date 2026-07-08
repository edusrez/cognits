"""Tools for study plan generation and retrieval.

``PlanStudy`` (name=plan_study) is used by the study_planner subagent to
run the deterministic planner on the current skill tree / learner state,
supersede any old active plan, and persist the new one.

``GetCurrentStudyPlan`` (name=get_current_study_plan) is used by the
orchestrator to fetch the active plan with review-vs-new classification
so it can present a deterministic learning path.

All DB calls go through ``asyncio.to_thread`` per the blocking-I/O
invariant (AGENTS.md).
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from datetime import datetime, timezone

from cognits.constants import MASTERY_THRESHOLD
from cognits.learner import planner
from cognits.tools import Tool, tool_error


# ---------------------------------------------------------------------------
# Shared classification helpers (used by GetCurrentStudyPlan and chat_service)
# ---------------------------------------------------------------------------


def _parse_iso(s: str | None) -> datetime | None:
    """Parse an ISO 8601 string into a UTC-aware datetime."""
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s.rstrip().replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


def classify_item(
    skill_id: str,
    states: dict[str, object],
    now: datetime,
) -> str:
    """Classify a study plan item as 'new', 'review', or 'skip'.

    Reuses the SAME logic as GetCurrentStudyPlan._classify:
      - Seeded-known (high mastery, never studied): skip.
      - FSRS next_review due: review.
      - Studied but not due for review: new.
      - Never studied: new.

    ``states`` maps skill_id -> LearnerState (must have p_mastery, next_review,
    reps, last_review attributes).
    """
    st = states.get(skill_id)
    if st is None:
        return "new"

    # Seeded-known skill: high mastery, never actually studied
    # (no last_review from seed_mastery). Skip from plan entirely.
    if st.p_mastery and st.p_mastery >= MASTERY_THRESHOLD and not st.last_review:
        return "skip"

    # FSRS-based: is the skill due for review?
    if st.next_review:
        try:
            next_dt = _parse_iso(st.next_review)
            if next_dt and now >= next_dt:
                return "review"
        except Exception:
            pass

    # Studied but not due for review → proceed forward.
    if st.reps and st.reps > 0 and st.last_review:
        return "new"

    return "new"


class PlanStudy(Tool):
    """Generate a deterministic study plan for a given goal.

    Used by the study_planner subagent to run the planner algorithm
    (frontier detection, scoring, ranking), supersede any existing
    active plan, and persist the new ordered items.
    """

    def __init__(
        self,
        plans,
        skills,
        learner_state,
        session_id: Callable[[], str] | None = None,
        emit=None,
    ):
        self.plans = plans
        self.skills = skills
        self.learner_state = learner_state
        self.session_id = session_id
        self.emit = emit

    name = "plan_study"
    description = (
        "Generate a deterministic study plan: detect the knowledge frontier, "
        "score and rank skills by goal relevance / review urgency / "
        "difficulty / Bloom level, and persist an ordered list of learning "
        "sessions. Takes a goal (skill name), optional priority skill IDs, "
        "and optional max_items (default 7). Returns plan_id and the "
        "ordered items."
    )
    schema = {
        "type": "object",
        "properties": {
            "goal": {
                "type": "string",
                "description": "Skill name the learner ultimately wants to learn (must match an existing skill name).",
            },
            "priorities": {
                "type": "array",
                "description": "Skill IDs the user explicitly requested priority on.",
                "items": {"type": "string"},
            },
            "max_items": {
                "type": "integer",
                "description": "How many items to include (default 7, max 50).",
            },
        },
        "required": ["goal"],
    }

    async def execute(self, raw_args: str) -> str:
        try:
            args = json.loads(raw_args)
        except json.JSONDecodeError as e:
            return tool_error(f"invalid JSON: {e}")

        goal = args.get("goal", "").strip()
        if not goal:
            return tool_error("'goal' is required")

        priorities = args.get("priorities") or []
        max_items = min(int(args.get("max_items", 7)), 50)

        def _generate():
            # Load tree data.
            all_skills = self.skills.list_active()
            tree = self.skills.get_tree()
            edges = [type(all_skills[0]).__new__(type(all_skills[0])) for _ in tree["edges"]]
            # ^ dummy — get_tree returns dicts, but the planner needs
            # SkillPrereq objects. We build them from the DB instead.
            edge_rows = []
            for s in all_skills:
                prereqs = self.skills.get_prerequisites(s.id)
                edge_rows.extend(prereqs)

            states = self.learner_state.get_all()

            # Run deterministic planner.
            items = planner.generate_plan(
                skills=all_skills,
                edges=edge_rows,
                states=states,
                goal=goal,
                priorities=priorities if priorities else None,
                max_items=max_items,
            )

            # Supersede any existing active plan.
            old = self.plans.get_active()
            if old is not None:
                self.plans.supersede(old.id)

            # Create new plan.
            tree_version = self.skills.get_tree_version()
            sid = self.session_id() if self.session_id is not None else ""
            plan_id = self.plans.create(
                tree_version=tree_version,
                goal=goal,
                session_id=sid,
            )

            # Persist items.
            if items:
                self.plans.replace_items(plan_id, items)

            # Re-fetch items to get their DB-assigned IDs.
            saved_items = self.plans.get_items(plan_id)

            # Compute frontier size for the response.
            frontier = planner.compute_frontier(all_skills, edge_rows, states)

            return plan_id, saved_items, tree_version, len(frontier)

        plan_id, saved_items, tree_version, frontier_size = await asyncio.to_thread(_generate)

        return json.dumps(
            {
                "plan_id": plan_id,
                "items": [i.to_json() for i in saved_items],
                "treeVersion": tree_version,
                "frontierSize": frontier_size,
            },
            ensure_ascii=False,
        )


class GetCurrentStudyPlan(Tool):
    def __init__(
        self,
        study_plans,
        skills,
        learner_state,
        session_id: Callable[[], str] | None = None,
        emit=None,
    ):
        self.study_plans = study_plans
        self.skills = skills
        self.learner_state = learner_state
        self.session_id = session_id
        self.emit = emit

    name = "get_current_study_plan"
    description = (
        "Return the active study plan with the next recommended skills, "
        "classified as 'new' (never seen) or 'review' (previously studied, "
        "may need reinforcement). Call this when the learner asks what to "
        "learn next, before starting a learning session, or when presenting "
        "the recommended path. If no plan exists, the response includes a "
        "message suggesting to generate one via the study planner."
    )
    schema = {
        "type": "object",
        "properties": {
            "limit": {
                "type": "integer",
                "description": "How many top-priority items to return (default 8, max 20).",
            },
        },
    }

    async def execute(self, raw_args: str) -> str:
        try:
            args = json.loads(raw_args) if raw_args.strip() else {}
        except json.JSONDecodeError:
            args = {}

        if self.study_plans is None:
            return json.dumps(
                {
                    "plan": None,
                    "message": "Study plan repository unavailable.",
                },
                ensure_ascii=False,
            )

        limit = min(int(args.get("limit", 8)), 20)

        def _fetch():
            plan = self.study_plans.get_active()
            if plan is None:
                return None, [], {}, {}

            items = self.study_plans.get_items(plan.id)
            states = self.learner_state.get_all()

            # Pre-fetch skill names/domains inside the to_thread closure.
            skill_ids = {item.skill_id for item in items}
            skill_names: dict[str, tuple[str, str]] = {}
            for sid in skill_ids:
                sk = self.skills.get(sid)
                if sk is not None:
                    skill_names[sid] = (sk.name, sk.domain)
                else:
                    skill_names[sid] = (sid, "(unknown)")
            return plan, items, states, skill_names

        plan, items, states, skill_names = await asyncio.to_thread(_fetch)

        if plan is None:
            return json.dumps(
                {
                    "plan": None,
                    "message": (
                        "No study plan yet. Generate one via the study planner: "
                        "deploy the study_planner subagent to build a personalized "
                        "plan based on the skill tree and learner mastery."
                    ),
                },
                ensure_ascii=False,
            )

        now = datetime.now(timezone.utc)
        next_items = []
        review_queue = []
        total_new = 0
        total_review = 0
        total_estimated_min = 0

        for item in items[:limit]:
            name, domain = skill_names.get(item.skill_id, (item.skill_id, "(unknown)"))
            item_type = classify_item(item.skill_id, states, now)
            if item_type == "skip":
                continue
            duration = item.estimated_duration_min or 0

            entry = {
                "skill_id": item.skill_id,
                "name": name,
                "domain": domain,
                "type": item_type,
                "priority": item.order_index,
                "estimated_duration_min": duration,
                "status": item.status,
            }
            next_items.append(entry)

            if item_type == "review":
                review_queue.append(entry)
                total_review += 1
            else:
                total_new += 1

            total_estimated_min += duration

        # Build a summary sentence.
        parts = []
        if total_new:
            parts.append(f"{total_new} new skill{'s' if total_new != 1 else ''}")
        if total_review:
            parts.append(f"{total_review} review skill{'s' if total_review != 1 else ''}")
        if total_estimated_min:
            parts.append(f"~{total_estimated_min} min total")
        summary = " + ".join(parts) if parts else "empty plan"

        return json.dumps(
            {
                "plan": {
                    "id": plan.id,
                    "goal": plan.goal,
                    "status": plan.status,
                    "tree_version": plan.tree_version,
                },
                "next_items": next_items,
                "review_queue": review_queue,
                "plan_summary": summary,
                "goal": plan.goal or "(no goal set)",
            },
            ensure_ascii=False,
        )
