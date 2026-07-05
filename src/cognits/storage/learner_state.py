"""Learner state repository — BKT + FSRS per-skill mastery tracking."""

from __future__ import annotations

from cognits.storage.database import Database
from cognits.storage.models import LearnerState


class LearnerStateRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    def upsert(self, st: LearnerState) -> None:
        with self.db.lock:
            self.db.conn.execute(
                """INSERT INTO learner_state
                       (skill_id, alpha, beta, p_mastery, status_enum,
                        retrievability, stability, difficulty, reps, lapses,
                        last_review, next_review, scaffolding_level)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(skill_id) DO UPDATE SET
                       alpha             = excluded.alpha,
                       beta              = excluded.beta,
                       p_mastery         = excluded.p_mastery,
                       status_enum       = excluded.status_enum,
                       retrievability    = excluded.retrievability,
                       stability         = excluded.stability,
                       difficulty        = excluded.difficulty,
                       reps              = excluded.reps,
                       lapses            = excluded.lapses,
                       last_review       = excluded.last_review,
                       next_review       = excluded.next_review,
                       scaffolding_level = excluded.scaffolding_level,
                       updated_at        = datetime('now')""",
                (
                    st.skill_id, st.alpha, st.beta, st.p_mastery, st.status_enum,
                    st.retrievability, st.stability, st.difficulty,
                    st.reps, st.lapses,
                    st.last_review, st.next_review, st.scaffolding_level,
                ),
            )

    def get(self, skill_id: str) -> LearnerState | None:
        with self.db.lock:
            row = self.db.conn.execute(
                """SELECT skill_id, alpha, beta, p_mastery, status_enum,
                          retrievability, stability, difficulty, reps, lapses,
                          last_review, next_review, scaffolding_level, updated_at
                   FROM learner_state WHERE skill_id = ?""",
                (skill_id,),
            ).fetchone()
        if row is None:
            return None
        return LearnerState(
            skill_id=row[0], alpha=row[1], beta=row[2], p_mastery=row[3],
            status_enum=row[4],
            retrievability=row[5], stability=row[6], difficulty=row[7],
            reps=row[8], lapses=row[9],
            last_review=row[10], next_review=row[11],
            scaffolding_level=row[12], updated_at=row[13],
        )

    def get_all(self) -> dict[str, LearnerState]:
        with self.db.lock:
            rows = self.db.conn.execute(
                "SELECT skill_id, alpha, beta, p_mastery, status_enum, "
                "retrievability, stability, difficulty, reps, lapses, "
                "last_review, next_review, scaffolding_level, updated_at FROM learner_state"
            ).fetchall()
        result: dict[str, LearnerState] = {}
        for row in rows:
            result[row[0]] = LearnerState(
                skill_id=row[0], alpha=row[1], beta=row[2],
                p_mastery=row[3], status_enum=row[4],
                retrievability=row[5], stability=row[6],
                difficulty=row[7], reps=row[8], lapses=row[9],
                last_review=row[10], next_review=row[11],
                scaffolding_level=row[12], updated_at=row[13],
            )
        return result
