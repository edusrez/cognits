"""update_mastery tool — called by the Evaluator subagent to persist
a review of the learner's skill state using the BKT + FSRS-6 learner model.

The tool wraps ``learner.record_review()`` (from learner/model.py), which
runs the FSRS step first (stability / difficulty / next_review), then the
BKT soft-evidence update (alpha / beta / p_mastery), and finally recomputes
the discrete mastery level. The result is persisted through ReportStore.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone

from cognits.tools import Tool, tool_error


class UpdateMastery(Tool):
    def __init__(self, learner_state):
        self.learner_state = learner_state

    name = "update_mastery"
    description = (
        "Update the learner's mastery state for a skill after an assessment. "
        "Call this when the evaluator has graded the user's answers and "
        "determined the correctness and FSRS rating. The tool persists the "
        "new BKT alpha/beta, FSRS stability/difficulty/next_review, and "
        "discrete mastery level. Returns the before-and-after snapshot."
    )
    schema = {
        "type": "object",
        "properties": {
            "skill_id": {
                "type": "string",
                "description": "The skill's ID (k_...).",
            },
            "correctness": {
                "type": "number",
                "description": "Continuous correctness ∈ [0, 1] of the user's performance across all answers.",
            },
            "rating": {
                "type": "integer",
                "enum": [1, 2, 3, 4],
                "description": "FSRS rating: 1=Again (failure), 2=Hard, 3=Good, 4=Easy.",
            },
            "hints_used": {
                "type": "integer",
                "description": "Number of hints the user needed during assessment (default 0).",
            },
        },
        "required": ["skill_id", "correctness", "rating"],
    }

    async def execute(self, raw_args: str) -> str:
        try:
            args = json.loads(raw_args)
            skill_id = args["skill_id"]
            correctness = float(args["correctness"])
            rating = int(args["rating"])
            hints_used = int(args.get("hints_used", 0))
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as e:
            return tool_error(f"invalid args: {e}")

        if rating < 1 or rating > 4:
            return tool_error(f"rating must be 1..4, got {rating}")
        if correctness < 0.0 or correctness > 1.0:
            return tool_error(f"correctness must be 0..1, got {correctness}")

        state = await asyncio.to_thread(
            self.learner_state.get, skill_id)
        if state is None:
            return tool_error(f"skill '{skill_id}' not found or no learner state")

        p_before = state.p_mastery

        now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        from cognits.learner import record_review

        record_review(
            state,
            correctness=correctness,
            rating=rating,
            now_iso=now_iso,
            hints_used=hints_used,
        )

        await asyncio.to_thread(
            self.learner_state.upsert, state)

        return json.dumps(
            {
                "skill_id": skill_id,
                "p_mastery_before": p_before,
                "p_mastery_after": state.p_mastery,
                "status_enum": state.status_enum,
                "next_review": state.next_review,
            },
            ensure_ascii=False,
        )