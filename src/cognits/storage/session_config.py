"""Session configuration repository."""

from __future__ import annotations

import json

from cognits.storage.database import Database
from cognits.storage.models import SessionConfigRow


class SessionConfigRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    def save(self, cfg: SessionConfigRow) -> None:
        with self.db.lock:
            self.db.conn.execute(
                """INSERT OR REPLACE INTO session_config
                   (session_id, provider, model, reasoning, agent_id, skill_id)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (cfg.session_id, cfg.provider, cfg.model, cfg.reasoning, cfg.agent_id, cfg.skill_id),
            )

    def load(self, session_id: str) -> SessionConfigRow | None:
        with self.db.lock:
            row = self.db.conn.execute(
                "SELECT session_id, provider, model, reasoning, agent_id, skill_id"
                " FROM session_config WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        if row is None:
            return None
        return SessionConfigRow(
            session_id=row[0],
            provider=row[1],
            model=row[2],
            reasoning=row[3],
            agent_id=row[4],
            skill_id=row[5],
        )

    def delete(self, session_id: str) -> None:
        with self.db.lock:
            self.db.conn.execute(
                "DELETE FROM session_config WHERE session_id = ?",
                (session_id,),
            )
