"""Pedagogical plan repository."""

from __future__ import annotations

from cognits.storage.database import Database


class PedagogicalPlanRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    def save(self, skill_id: str, content: str) -> None:
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
