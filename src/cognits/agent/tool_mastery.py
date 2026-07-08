""""update_mastery" and "seed_mastery" tools for the learner model.

update_mastery — called by the Evaluator subagent to persist a review of
the learner's skill state using the BKT + FSRS-6 learner model. The tool
wraps ``learner.record_review()`` (from learner/model.py), which runs the
FSRS step first (stability / difficulty / next_review), then the BKT
soft-evidence update (alpha / beta / p_mastery), and finally recomputes
the discrete mastery level.

seed_mastery — called by the Skill Planner during onboarding to seed a
Bayesian Beta prior for skills the learner already knows. Instead of
simulating a fake review, it sets alpha/beta directly from a self-reported
or diagnosed prior with a confidence parameter that controls how strongly
the prior is held against future evidence. The result is persisted and
respects BKT conjugacy for future updates.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone

from cognits.learner.model import mastery_level
from cognits.storage.models import LearnerState
from cognits.tools import Tool, tool_error

log = logging.getLogger("cognits.mastery")


class UpdateMastery(Tool):
    def __init__(self, learner_state, skills=None):
        self.learner_state = learner_state
        self.skills = skills  # optional — FIRe credit needs skill encompassing edges

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

        # --- FIRe implicit repetition credit ---
        if rating >= 2:  # not a complete failure (rating 1 = Again)
            try:
                if self.skills is not None:
                    encompassings = await asyncio.to_thread(
                        self.skills.get_encompassings, skill_id
                    )
                    if encompassings:
                        for enc in encompassings:
                            try:
                                enc_state = await asyncio.to_thread(
                                    self.learner_state.get, enc.encompasses_skill_id
                                )
                                if enc_state is not None:
                                    from cognits.learner.model import apply_implicit_credit
                                    apply_implicit_credit(enc_state, enc.weight)
                                    await asyncio.to_thread(
                                        self.learner_state.upsert, enc_state
                                    )
                            except Exception as enc_e:
                                log.debug("FIRe credit propagation failed for %s: %s",
                                          enc.encompasses_skill_id, enc_e)
            except Exception as fire_e:
                log.debug("FIRe encompassing query failed: %s", fire_e)

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


class SeedMastery(Tool):
    def __init__(self, learner_state, skills):
        self.learner_state = learner_state
        self.skills = skills

    name = "seed_mastery"
    description = (
        "Seed a skill's mastery state using a Bayesian Beta prior. "
        "This sets alpha and beta directly (alpha = prior × C, "
        "beta = (1-prior) × C) where C is the confidence level "
        "(5 for self_report, 10 for diagnostic). Use this during "
        "onboarding to mark skills the learner already knows. "
        "update_mastery is for real reviews during learning; "
        "seed_mastery is for initial priors before any review data."
    )
    schema = {
        "type": "object",
        "properties": {
            "skill_id": {
                "type": "string",
                "description": "The skill's ID (k_...).",
            },
            "prior": {
                "type": "number",
                "description": "Self-reported/diagnosed probability the learner has already mastered this skill, ∈ [0,1].",
            },
            "confidence": {
                "type": "string",
                "enum": ["self_report", "diagnostic"],
                "description": "Confidence level in the prior. self_report=C5 (weak, easily overridden by reviews), diagnostic=C10 (strong, from an assessment). Default self_report.",
            },
        },
        "required": ["skill_id", "prior"],
    }

    async def execute(self, raw_args: str) -> str:
        try:
            args = json.loads(raw_args)
            skill_id = args["skill_id"]
            prior = float(args["prior"])
            confidence = args.get("confidence", "self_report")
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as e:
            return tool_error(f"invalid args: {e}")

        if prior < 0.0 or prior > 1.0:
            return tool_error(f"prior must be 0..1, got {prior}")

        if confidence not in ("self_report", "diagnostic"):
            return tool_error(
                f"confidence must be 'self_report' or 'diagnostic', got {confidence}"
            )

        C = 5 if confidence == "self_report" else 10

        skill = await asyncio.to_thread(self.skills.get, skill_id)
        if skill is None:
            return tool_error(f"unknown skill_id: {skill_id}")

        alpha = prior * C
        beta = (1.0 - prior) * C

        state = await asyncio.to_thread(self.learner_state.get, skill_id)
        if state is None:
            state = LearnerState(skill_id=skill_id)

        now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        state.alpha = alpha
        state.beta = beta
        state.p_mastery = alpha / (alpha + beta)
        state.reps = max(state.reps, 1)

        state.status_enum = mastery_level(state, now_iso)

        # Initialize FSRS stability conservatively based on the seeded prior.
        # This ensures step_review uses a non-trivial stability when the
        # skill enters the review pipeline (not first-review init).
        if prior >= 0.95:
            state.stability = 21.0   # 3 weeks — stable knowledge
        elif prior >= 0.80:
            state.stability = 7.0    # 1 week — moderately stable
        elif prior >= 0.60:
            state.stability = 3.0    # 3 days — some exposure
        else:
            state.stability = 1.0    # 1 day — barely stable

        state.difficulty = 5.0  # midpoint, neutral
        state.retrievability = None  # computed on first real review
        # Do NOT set last_review or next_review — seeding is not a study event.

        state.updated_at = now_iso

        await asyncio.to_thread(self.learner_state.upsert, state)

        return json.dumps(
            {
                "skill_id": skill_id,
                "p_mastery": state.p_mastery,
                "alpha": state.alpha,
                "beta": state.beta,
                "confidence": C,
                "status": state.status_enum,
            },
            ensure_ascii=False,
        )