"""Data models: dataclasses, ID generators, FTS helpers, and constants.

Extracted from db.py (Phase 1 split). All data shapes and pure helpers
live here; the Database connection and per-domain repositories are
separate modules.
"""

from __future__ import annotations

import json
import secrets
from dataclasses import dataclass


@dataclass
class Report:
    id: str = ""
    session_id: str = ""
    title: str = ""
    content: str = ""
    summary: str = ""
    sources: list[str] | None = None
    subagent: str = "web_researcher"
    created_at: str = ""

    def to_json(self) -> dict:
        return {
            "id": self.id,
            "sessionId": self.session_id,
            "title": self.title,
            "content": self.content,
            "summary": self.summary,
            "sources": self.sources if self.sources is not None else [],
            "subagent": self.subagent,
            "createdAt": self.created_at,
        }


@dataclass
class MessageRow:
    id: int = 0
    session_id: str = ""
    role: str = ""
    content: str = ""
    reasoning: str = ""
    report_id: str = ""
    report_title: str = ""
    reports: str = ""
    created_at: str = ""

    def to_json(self) -> dict:
        result = {
            "id": self.id,
            "sessionId": self.session_id,
            "role": self.role,
            "content": self.content,
            "reasoning": self.reasoning,
            "createdAt": self.created_at,
        }
        if self.reports:
            try:
                result["reports"] = json.loads(self.reports)
            except (json.JSONDecodeError, TypeError):
                pass
        elif self.report_id:
            result["reports"] = [{"reportId": self.report_id, "reportTitle": self.report_title}]
        return result


@dataclass
class SessionConfigRow:
    session_id: str = ""
    provider: str = ""
    model: str = ""
    reasoning: str = ""
    agent_id: str = ""
    skill_id: str = ""

    def to_json(self) -> dict:
        return {
            "sessionId": self.session_id,
            "provider": self.provider,
            "model": self.model,
            "reasoning": self.reasoning,
            "agentId": self.agent_id,
            "skillId": self.skill_id,
        }

    @classmethod
    def from_json(cls, d: dict) -> "SessionConfigRow":
        return cls(
            session_id=d.get("sessionId") or "",
            provider=d.get("provider") or "",
            model=d.get("model") or "",
            reasoning=d.get("reasoning") or "",
            agent_id=d.get("agentId") or "",
            skill_id=d.get("skillId") or "",
        )


@dataclass
class Note:
    id: str = ""
    title: str = ""
    content: str = ""
    created_at: str = ""
    updated_at: str = ""

    def to_json(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "content": self.content,
            "createdAt": self.created_at,
            "updatedAt": self.updated_at,
        }


@dataclass
class Skill:
    id: str = ""
    domain: str = ""
    name: str = ""
    description: str = ""
    bloom_level: str = ""
    difficulty: float = 0.5
    parent_skill_id: str = ""
    status: str = "active"
    source: str = ""
    tree_version: int = 1
    superseded_by: str = ""
    created_at: str = ""
    updated_at: str = ""

    def to_json(self) -> dict:
        return {
            "id": self.id,
            "domain": self.domain,
            "name": self.name,
            "description": self.description,
            "bloomLevel": self.bloom_level,
            "difficulty": self.difficulty,
            "parentSkillId": self.parent_skill_id,
            "status": self.status,
            "source": self.source,
            "treeVersion": self.tree_version,
            "supersededBy": self.superseded_by,
            "createdAt": self.created_at,
            "updatedAt": self.updated_at,
        }


@dataclass
class SkillPrereq:
    skill_id: str = ""
    prereq_id: str = ""
    edge_type: str = "prereq"
    proof_query: str = ""
    build_id: str = ""
    created_at: str = ""

    def to_json(self) -> dict:
        return {
            "skillId": self.skill_id,
            "prereqId": self.prereq_id,
            "edgeType": self.edge_type,
            "proofQuery": self.proof_query,
            "buildId": self.build_id,
            "createdAt": self.created_at,
        }


@dataclass
class SkillBuild:
    id: str = ""
    session_id: str = ""
    trigger: str = ""
    skill_count: int = 0
    added: int = 0
    modified: int = 0
    superseded: int = 0
    started_at: str = ""
    finished_at: str = ""
    status: str = "running"
    summary: str = ""

    def to_json(self) -> dict:
        return {
            "id": self.id,
            "sessionId": self.session_id,
            "trigger": self.trigger,
            "skillCount": self.skill_count,
            "added": self.added,
            "modified": self.modified,
            "superseded": self.superseded,
            "startedAt": self.started_at,
            "finishedAt": self.finished_at,
            "status": self.status,
            "summary": self.summary,
        }


@dataclass
class LearnerState:
    skill_id: str = ""
    alpha: float = 1.0
    beta: float = 1.0
    p_mastery: float = 0.5
    status_enum: str = "not_seen"
    retrievability: float | None = None
    stability: float | None = None
    difficulty: float | None = None
    reps: int = 0
    lapses: int = 0
    last_review: str | None = None
    next_review: str | None = None
    scaffolding_level: int = 1
    updated_at: str = ""

    def to_json(self) -> dict:
        return {
            "skillId": self.skill_id,
            "alpha": self.alpha,
            "beta": self.beta,
            "pMastery": self.p_mastery,
            "statusEnum": self.status_enum,
            "retrievability": self.retrievability,
            "stability": self.stability,
            "reps": self.reps,
            "lapses": self.lapses,
            "lastReview": self.last_review,
            "nextReview": self.next_review,
            "scaffoldingLevel": self.scaffolding_level,
            "updatedAt": self.updated_at,
        }


@dataclass
class StudyPlan:
    id: str = ""
    session_id: str = ""
    tree_version: int = 0
    goal: str = ""
    status: str = "active"
    created_at: str = ""
    updated_at: str = ""

    def to_json(self) -> dict:
        return {
            "id": self.id,
            "sessionId": self.session_id,
            "treeVersion": self.tree_version,
            "goal": self.goal,
            "status": self.status,
            "createdAt": self.created_at,
            "updatedAt": self.updated_at,
        }


@dataclass
class StudyPlanItem:
    id: str = ""
    plan_id: str = ""
    skill_id: str = ""
    mode: str = "socratic"
    status: str = "pending"
    order_index: int = 0
    estimated_duration_min: int | None = None
    actual_duration_min: int | None = None
    learning_session_id: str | None = None
    created_at: str = ""
    updated_at: str = ""

    def to_json(self) -> dict:
        return {
            "id": self.id,
            "planId": self.plan_id,
            "skillId": self.skill_id,
            "mode": self.mode,
            "status": self.status,
            "orderIndex": self.order_index,
            "estimatedDurationMin": self.estimated_duration_min,
            "actualDurationMin": self.actual_duration_min,
            "learningSessionId": self.learning_session_id,
            "createdAt": self.created_at,
            "updatedAt": self.updated_at,
        }


@dataclass
class AssessmentItem:
    id: str = ""
    skill_id: str = ""
    skill_ids: list[str] | None = None
    question: str = ""
    question_type: str = "open"
    expected_answer: str = ""
    rubric: str = ""
    rubric_criteria: list[dict] | None = None
    rubric_type: str = "analytic"
    blooms_level: str = ""
    difficulty: float = 0.5
    p_value: float | None = None
    irt_a: float | None = None
    irt_b: float | None = None
    irt_c: float | None = None
    irt_model: str = "heuristic"
    generation_model: str = ""
    generation_prompt_hash: str = ""
    template_id: str = ""
    source: str = ""
    seed_version: int = 1
    times_presented: int = 0
    times_correct: int = 0
    avg_response_time_ms: float | None = None
    status: str = "active"
    reviewed_by: str = ""
    created_at: str = ""
    updated_at: str = ""


# --- ID generators ---

def new_report_id() -> str:
    return "r_" + secrets.token_hex(8)


def new_note_id() -> str:
    return "n_" + secrets.token_hex(8)


def new_skill_id() -> str:
    return "k_" + secrets.token_hex(8)


def new_build_id() -> str:
    return "b_" + secrets.token_hex(8)


def new_plan_id() -> str:
    return "p_" + secrets.token_hex(8)


def new_plan_item_id() -> str:
    return "pi_" + secrets.token_hex(8)


def new_assessment_item_id() -> str:
    return "ai_" + secrets.token_hex(8)


# --- Status enums ---

EDGE_TYPES = ("prereq", "coreq", "related", "soft_prereq")
PLAN_STATUS = ("active", "superseded")
PLAN_ITEM_STATUS = ("pending", "in_progress", "done", "skipped", "goal_removed")
PLAN_ITEM_MODE = ("socratic", "exercise", "project")
SKILL_STATUS = ("not_seen", "exploring", "practicing", "proficient", "mastered", "decaying")


# --- FTS helpers ---

def escape_like(s: str) -> str:
    return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def build_fts5_query(raw: str) -> str:
    raw = raw.strip()
    if not raw:
        return ""
    processed = []
    for w in raw.split():
        w = w.strip("()*")
        w = w.replace('"', '""')
        if not w:
            continue
        processed.append(f'"{w}"*')
    return " ".join(processed)


def _clamp(page: int, limit: int) -> tuple[int, int]:
    if page < 1:
        page = 1
    if limit < 1 or limit > 50:
        limit = 10
    return page, limit


_SORT_SQL = {
    "date_asc": "created_at ASC",
    "title_asc": "title ASC",
    "title_desc": "title DESC",
}


def _unmarshal_sources(raw: str | None) -> list[str]:
    try:
        sources = json.loads(raw or "[]")
    except json.JSONDecodeError:
        return []
    return sources if isinstance(sources, list) else []
