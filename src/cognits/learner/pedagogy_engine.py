"""Pedagogical plan stage management.

Transitions between teaching stages are managed externally (not by the LLM)
to prevent the ~30% non-compliance rate observed when LLMs self-manage stage
transitions (Springer 2025 systematic review).

The engine tracks: current stage, interaction count, last mastery snapshot,
and triggers stage advances based on BKT mastery + minimum interaction count.
"""

from __future__ import annotations

from enum import Enum

from cognits.constants import MASTERY_PROFICIENT_P, MASTERY_THRESHOLD


class Stage(str, Enum):
    ACTIVATE = "activate_prior_knowledge"
    INTRODUCE = "introduce_concept"
    GUIDED = "guided_practice"
    ASSESS = "assessment"
    WRAP_UP = "wrap_up"


STAGE_ORDER = (
    Stage.ACTIVATE,
    Stage.INTRODUCE,
    Stage.GUIDED,
    Stage.ASSESS,
    Stage.WRAP_UP,
)

# Minimum interactions before advancing from each stage
MIN_INTERACTIONS = {
    Stage.ACTIVATE: 1,
    Stage.INTRODUCE: 2,
    Stage.GUIDED: 3,
    Stage.ASSESS: 1,    # one formal assessment
    Stage.WRAP_UP: 1,
}

# Mastery threshold to advance from each stage (None = no mastery gate)
ADVANCE_THRESHOLD = {
    Stage.ACTIVATE: None,
    Stage.INTRODUCE: 0.30,
    Stage.GUIDED: MASTERY_PROFICIENT_P,
    Stage.ASSESS: MASTERY_PROFICIENT_P,
    Stage.WRAP_UP: MASTERY_THRESHOLD,
}


class PedagogyEngine:
    def __init__(self, skill_id: str):
        self.skill_id = skill_id
        self.stage = Stage.ACTIVATE
        self.interactions = 0
        self.initial_mastery: float | None = None

    def should_advance(self, p_mastery: float) -> bool:
        threshold = ADVANCE_THRESHOLD.get(self.stage)
        if threshold is not None and p_mastery < threshold:
            return False
        return self.interactions >= MIN_INTERACTIONS.get(self.stage, 2)

    def advance(self) -> Stage | None:
        idx = STAGE_ORDER.index(self.stage)
        if idx >= len(STAGE_ORDER) - 1:
            return None
        self.stage = STAGE_ORDER[idx + 1]
        self.interactions = 0
        return self.stage

    def record_interaction(self):
        self.interactions += 1

    def prompt_context(self) -> str:
        return f"You are currently in stage: {self.stage.value}. "
