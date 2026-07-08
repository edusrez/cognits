"""Pedagogical plan repository."""

from __future__ import annotations

import logging
import re

from cognits.storage.database import Database

logger = logging.getLogger(__name__)

# Regex to extract stage names from "### Stage N: name" headers
_STAGE_HEADER_RE = re.compile(r"^###\s+Stage\s+\d+:\s*(\S+)", re.MULTILINE)

# Canonical stage names (must match pedagogy_engine.Stage enum values)
_CANONICAL_STAGES = {
    "activate_prior_knowledge",
    "introduce_concept",
    "guided_practice",
    "assessment",
    "wrap_up",
}


class PedagogicalPlanRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    def save(self, skill_id: str, content: str) -> None:
        _warn_non_canonical_stages(content)
        with self.db.lock:
            self.db.conn.execute(
                """INSERT INTO pedagogical_plans
                   (skill_id, content, generated_at, updated_at)
                   VALUES (?, ?, datetime('now'), datetime('now'))
                   ON CONFLICT(skill_id) DO UPDATE SET content = excluded.content, updated_at = datetime('now')""",
                (skill_id, content),
            )

    def get(self, skill_id: str) -> str | None:
        with self.db.lock:
            row = self.db.conn.execute(
                "SELECT content FROM pedagogical_plans WHERE skill_id = ?",
                (skill_id,),
            ).fetchone()
        return row[0] if row else None


def _warn_non_canonical_stages(content: str) -> None:
    """Log a warning if the Markdown contains non-canonical stage names."""
    for match in _STAGE_HEADER_RE.finditer(content):
        name = match.group(1)
        if name not in _CANONICAL_STAGES:
            logger.warning(
                "pedagogical plan has non-canonical stage: '%s' "
                "— expected one of %s",
                name,
                sorted(_CANONICAL_STAGES),
            )
