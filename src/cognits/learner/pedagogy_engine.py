"""Pedagogical plan stage management.

Transitions between teaching stages are managed externally (not by the LLM)
to prevent the ~30% non-compliance rate observed when LLMs self-manage stage
transitions (Springer 2025 systematic review).

The engine tracks: current stage, interaction count, last mastery snapshot,
and triggers stage advances based on BKT mastery + minimum interaction count.

IMPORTANT: The Stage enum values below MUST match the stage names used in
the study_planner agent's pedagogical plan Markdown template
(src/cognits/agent/agents/study_planner.md). Any divergence between the
template and the enum will cause stage detection to fail silently.
"""

from __future__ import annotations

from enum import Enum

from cognits.constants import MASTERY_THRESHOLD


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
# ASSESS gate (advancing FROM guided_practice TO assessment): moderate bar (0.60)
# — assessment measures true mastery, does not gate on it.
# WRAP_UP gate (advancing FROM assessment TO wrap_up): requires demonstrated mastery.
ADVANCE_THRESHOLD = {
    Stage.ACTIVATE: None,
    Stage.INTRODUCE: 0.30,
    Stage.GUIDED: 0.60,
    Stage.ASSESS: MASTERY_THRESHOLD,
    Stage.WRAP_UP: MASTERY_THRESHOLD,
}

# Absolute drop in p_mastery that triggers a stage retreat
RETREAT_MASTERY_DROP: float = 0.10

# Canonical stage names (for validation against study_planner.md template)
STAGE_NAMES = [s.value for s in STAGE_ORDER]


class PedagogyEngine:
    def __init__(self):
        self.stage = Stage.ACTIVATE
        self.interactions = 0

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

    def current_stage(self) -> str:
        return self.stage.value

    def retreat(self) -> str | None:
        """Move back one stage if possible (regress on mastery drop).
        Returns the new stage name, or None if already at the first stage."""
        idx = STAGE_ORDER.index(self.stage)
        if idx > 0:
            self.stage = STAGE_ORDER[idx - 1]
            self.interactions = 0
            return self.current_stage()
        return None

    def record_interaction(self):
        self.interactions += 1

    def load_from_scaffolding_level(self, level: int) -> None:
        idx = max(0, min(level - 1, len(STAGE_ORDER) - 1))
        self.stage = STAGE_ORDER[idx]
        self.interactions = 0

    def to_scaffolding_level(self) -> int:
        return STAGE_ORDER.index(self.stage) + 1

    def prompt_context(self) -> str:
        return f"You are currently in stage: {self.stage.value}. "
