"""Assessment item repository — save, list, search, record responses."""

from __future__ import annotations

import json

from cognits.storage.database import Database
from cognits.storage.models import AssessmentItem, build_fts5_query, new_assessment_item_id


class AssessmentItemRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    @staticmethod
    def _row_to_item(row: tuple) -> AssessmentItem:
        skill_ids_raw = row[2] or "[]"
        rubric_criteria_raw = row[7] or "[]"
        try:
            skill_ids = json.loads(skill_ids_raw)
        except (json.JSONDecodeError, TypeError):
            skill_ids = []
        try:
            rubric_criteria = json.loads(rubric_criteria_raw)
        except (json.JSONDecodeError, TypeError):
            rubric_criteria = []
        return AssessmentItem(
            id=row[0],
            skill_id=row[1],
            skill_ids=skill_ids,
            question=row[3],
            question_type=row[4],
            expected_answer=row[5] or "",
            rubric=row[6] or "",
            rubric_criteria=rubric_criteria,
            rubric_type=row[8],
            blooms_level=row[9] or "",
            difficulty=row[10],
            p_value=row[11],
            irt_a=row[12],
            irt_b=row[13],
            irt_c=row[14],
            irt_model=row[15],
            generation_model=row[16] or "",
            generation_prompt_hash=row[17] or "",
            template_id=row[18] or "",
            source=row[19] or "",
            seed_version=row[20],
            times_presented=row[21],
            times_correct=row[22],
            avg_response_time_ms=row[23],
            status=row[24],
            reviewed_by=row[25] or "",
            created_at=row[26],
            updated_at=row[27],
        )

    def save(self, item: AssessmentItem) -> None:
        skill_ids_json = json.dumps(item.skill_ids or [])
        rubric_criteria_json = json.dumps(item.rubric_criteria or [])
        with self.db.lock:
            self.db.conn.execute(
                """INSERT INTO skill_assessment_items
                   (id, skill_id, skill_ids, question, question_type,
                    expected_answer, rubric, rubric_criteria, rubric_type,
                    blooms_level, difficulty, p_value, irt_a, irt_b, irt_c,
                    irt_model, generation_model, generation_prompt_hash,
                    template_id, source, seed_version, times_presented,
                    times_correct, avg_response_time_ms, status, reviewed_by)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(id) DO UPDATE SET
                       skill_id                = excluded.skill_id,
                       skill_ids               = excluded.skill_ids,
                       question                = excluded.question,
                       question_type           = excluded.question_type,
                       expected_answer         = excluded.expected_answer,
                       rubric                  = excluded.rubric,
                       rubric_criteria         = excluded.rubric_criteria,
                       rubric_type             = excluded.rubric_type,
                       blooms_level            = excluded.blooms_level,
                       difficulty              = excluded.difficulty,
                       p_value                 = excluded.p_value,
                       irt_a                   = excluded.irt_a,
                       irt_b                   = excluded.irt_b,
                       irt_c                   = excluded.irt_c,
                       irt_model               = excluded.irt_model,
                       generation_model        = excluded.generation_model,
                       generation_prompt_hash  = excluded.generation_prompt_hash,
                       template_id             = excluded.template_id,
                       source                  = excluded.source,
                       seed_version            = excluded.seed_version,
                       times_presented         = excluded.times_presented,
                       times_correct           = excluded.times_correct,
                       avg_response_time_ms    = excluded.avg_response_time_ms,
                       status                  = excluded.status,
                       reviewed_by             = excluded.reviewed_by,
                       updated_at              = datetime('now')""",
                (
                    item.id, item.skill_id, skill_ids_json, item.question, item.question_type,
                    item.expected_answer, item.rubric, rubric_criteria_json, item.rubric_type,
                    item.blooms_level, item.difficulty, item.p_value, item.irt_a, item.irt_b, item.irt_c,
                    item.irt_model, item.generation_model, item.generation_prompt_hash,
                    item.template_id, item.source, item.seed_version, item.times_presented,
                    item.times_correct, item.avg_response_time_ms, item.status, item.reviewed_by,
                ),
            )

    def get(self, item_id: str) -> AssessmentItem | None:
        with self.db.lock:
            row = self.db.conn.execute(
                """SELECT id, skill_id, skill_ids, question, question_type,
                          expected_answer, rubric, rubric_criteria, rubric_type,
                          blooms_level, difficulty, p_value, irt_a, irt_b, irt_c,
                          irt_model, generation_model, generation_prompt_hash,
                          template_id, source, seed_version, times_presented,
                          times_correct, avg_response_time_ms, status, reviewed_by,
                          created_at, updated_at
                   FROM skill_assessment_items WHERE id = ?""",
                (item_id,),
            ).fetchone()
        return self._row_to_item(row) if row else None

    def list_for_skill(self, skill_id: str, include_all: bool = False) -> list[AssessmentItem]:
        sql = """SELECT id, skill_id, skill_ids, question, question_type,
                        expected_answer, rubric, rubric_criteria, rubric_type,
                        blooms_level, difficulty, p_value, irt_a, irt_b, irt_c,
                        irt_model, generation_model, generation_prompt_hash,
                        template_id, source, seed_version, times_presented,
                        times_correct, avg_response_time_ms, status, reviewed_by,
                        created_at, updated_at
                 FROM skill_assessment_items WHERE skill_id = ?"""
        if not include_all:
            sql += " AND status = 'active'"
        sql += " ORDER BY created_at DESC"
        with self.db.lock:
            rows = self.db.conn.execute(sql, (skill_id,)).fetchall()
        return [self._row_to_item(r) for r in rows]

    def list_for_skills(self, skill_ids: list[str], include_all: bool = False) -> list[AssessmentItem]:
        if not skill_ids:
            return []
        placeholders = ",".join("?" for _ in skill_ids)
        sql = f"""SELECT id, skill_id, skill_ids, question, question_type,
                         expected_answer, rubric, rubric_criteria, rubric_type,
                         blooms_level, difficulty, p_value, irt_a, irt_b, irt_c,
                         irt_model, generation_model, generation_prompt_hash,
                         template_id, source, seed_version, times_presented,
                         times_correct, avg_response_time_ms, status, reviewed_by,
                         created_at, updated_at
                  FROM skill_assessment_items WHERE skill_id IN ({placeholders})"""
        if not include_all:
            sql += " AND status = 'active'"
        sql += " ORDER BY created_at DESC"
        with self.db.lock:
            rows = self.db.conn.execute(sql, skill_ids).fetchall()
        return [self._row_to_item(r) for r in rows]

    def list_all(self, include_inactive: bool = False) -> list[AssessmentItem]:
        sql = """SELECT id, skill_id, skill_ids, question, question_type,
                        expected_answer, rubric, rubric_criteria, rubric_type,
                        blooms_level, difficulty, p_value, irt_a, irt_b, irt_c,
                        irt_model, generation_model, generation_prompt_hash,
                        template_id, source, seed_version, times_presented,
                        times_correct, avg_response_time_ms, status, reviewed_by,
                        created_at, updated_at
                 FROM skill_assessment_items"""
        if not include_inactive:
            sql += " WHERE status = 'active'"
        sql += " ORDER BY created_at DESC"
        with self.db.lock:
            rows = self.db.conn.execute(sql).fetchall()
        return [self._row_to_item(r) for r in rows]

    def search_fts(self, search: str, limit: int = 50) -> list[AssessmentItem]:
        fts_query = build_fts5_query(search)
        if not fts_query:
            return []
        if limit < 1 or limit > 100:
            limit = 50
        with self.db.lock:
            rows = self.db.conn.execute(
                f"""SELECT ai.id, ai.skill_id, ai.skill_ids, ai.question, ai.question_type,
                           ai.expected_answer, ai.rubric, ai.rubric_criteria, ai.rubric_type,
                           ai.blooms_level, ai.difficulty, ai.p_value, ai.irt_a, ai.irt_b,
                           ai.irt_c, ai.irt_model, ai.generation_model, ai.generation_prompt_hash,
                           ai.template_id, ai.source, ai.seed_version, ai.times_presented,
                           ai.times_correct, ai.avg_response_time_ms, ai.status, ai.reviewed_by,
                           ai.created_at, ai.updated_at,
                           bm25(skill_assessment_items_fts, 10.0, 1.0) AS score
                    FROM skill_assessment_items_fts
                    JOIN skill_assessment_items ai ON ai.rowid = skill_assessment_items_fts.rowid
                    WHERE skill_assessment_items_fts MATCH ?
                    ORDER BY score
                    LIMIT ?""",
                (fts_query, limit),
            ).fetchall()
        return [self._row_to_item(r[:28]) for r in rows]

    def delete(self, item_id: str) -> None:
        with self.db.lock:
            self.db.conn.execute(
                "DELETE FROM skill_assessment_items WHERE id = ?",
                (item_id,),
            )

    def record_response(
        self,
        item_id: str,
        correctness: float,
        response_time_ms: float | None = None,
    ) -> None:
        """Update per-item statistics after a learner response.

        - times_presented is incremented by 1.
        - times_correct is incremented by 1 if correctness >= 0.6 (binary pass/fail).
        - p_value is recomputed as times_correct / times_presented.
        - avg_response_time_ms is updated as a running mean if response_time_ms is provided.
        - updated_at is set to now.
        """
        with self.db.lock:
            row = self.db.conn.execute(
                "SELECT times_presented, times_correct, avg_response_time_ms FROM skill_assessment_items WHERE id = ?",
                (item_id,),
            ).fetchone()
            if not row:
                return
            old_presented, old_correct, old_avg = row
            new_presented = old_presented + 1
            new_correct = old_correct + (1 if correctness >= 0.6 else 0)
            new_p_value = new_correct / new_presented if new_presented > 0 else None

            new_avg = old_avg
            if response_time_ms is not None:
                if old_avg is not None and old_presented > 0:
                    new_avg = (old_avg * old_presented + response_time_ms) / (old_presented + 1)
                else:
                    new_avg = response_time_ms

            self.db.conn.execute(
                """UPDATE skill_assessment_items
                   SET times_presented = ?,
                       times_correct = ?,
                       p_value = ?,
                       avg_response_time_ms = ?,
                       updated_at = datetime('now')
                   WHERE id = ?""",
                (new_presented, new_correct, new_p_value, new_avg, item_id),
            )
