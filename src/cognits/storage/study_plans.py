"""Study plan repository — plans, items, lifecycle."""

from __future__ import annotations

from cognits.storage.database import Database
from cognits.storage.models import (
    StudyPlan,
    StudyPlanItem,
    new_plan_id,
    new_plan_item_id,
)


class StudyPlanRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    @staticmethod
    def _row_to_plan(row: tuple) -> StudyPlan:
        return StudyPlan(
            id=row[0], session_id=row[1] or "", tree_version=row[2],
            goal=row[3] or "", status=row[4], created_at=row[5], updated_at=row[6],
        )

    @staticmethod
    def _row_to_plan_item(row: tuple) -> StudyPlanItem:
        return StudyPlanItem(
            id=row[0], plan_id=row[1], skill_id=row[2], mode=row[3],
            status=row[4], order_index=row[5],
            estimated_duration_min=row[6],
            actual_duration_min=row[7],
            learning_session_id=row[8], created_at=row[9], updated_at=row[10],
        )

    def create(
        self, tree_version: int, goal: str = "", session_id: str = ""
    ) -> str:
        plan_id = new_plan_id()
        with self.db.lock:
            self.db.conn.execute(
                "INSERT INTO study_plans (id, session_id, tree_version, goal) "
                "VALUES (?, ?, ?, ?)",
                (plan_id, session_id, tree_version, goal),
            )
        return plan_id

    def supersede(self, plan_id: str) -> None:
        with self.db.lock:
            self.db.conn.execute(
                "UPDATE study_plans SET status = 'superseded', "
                "updated_at = datetime('now') WHERE id = ?",
                (plan_id,),
            )

    def get_active(self) -> StudyPlan | None:
        with self.db.lock:
            row = self.db.conn.execute(
                "SELECT id, session_id, tree_version, goal, status, "
                "created_at, updated_at FROM study_plans "
                "WHERE status = 'active' ORDER BY created_at DESC, rowid DESC LIMIT 1"
            ).fetchone()
        return self._row_to_plan(row) if row else None

    def add_item(
        self,
        plan_id: str,
        skill_id: str,
        mode: str = "socratic",
        order_index: int = 0,
        estimated_duration_min: int | None = None,
    ) -> str:
        item_id = new_plan_item_id()
        with self.db.lock:
            self.db.conn.execute(
                "INSERT INTO study_plan_items "
                "(id, plan_id, skill_id, mode, order_index, estimated_duration_min) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (item_id, plan_id, skill_id, mode, order_index, estimated_duration_min),
            )
        return item_id

    def replace_items(self, plan_id: str, items: list[StudyPlanItem]) -> None:
        with self.db.lock:
            self.db.conn.execute(
                "DELETE FROM study_plan_items WHERE plan_id = ?", (plan_id,)
            )
            self.db.conn.executemany(
                "INSERT INTO study_plan_items "
                "(id, plan_id, skill_id, mode, status, order_index, "
                "estimated_duration_min, actual_duration_min, learning_session_id) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        item.id or new_plan_item_id(),
                        plan_id,
                        item.skill_id,
                        item.mode,
                        item.status,
                        item.order_index,
                        item.estimated_duration_min,
                        item.actual_duration_min,
                        item.learning_session_id,
                    )
                    for item in items
                ],
            )

    def update_item(
        self,
        item_id: str,
        status: str | None = None,
        learning_session_id: str | None = None,
        actual_duration_min: int | None = None,
    ) -> None:
        sets = ["updated_at = datetime('now')"]
        args: list = []
        for col, val in (
            ("status", status),
            ("learning_session_id", learning_session_id),
            ("actual_duration_min", actual_duration_min),
        ):
            if val is not None:
                sets.append(f"{col} = ?")
                args.append(val)
        if len(args) == 0:
            return
        args.append(item_id)
        with self.db.lock:
            self.db.conn.execute(
                f"UPDATE study_plan_items SET {', '.join(sets)} WHERE id = ?",
                args,
            )

    def get_items(self, plan_id: str) -> list[StudyPlanItem]:
        with self.db.lock:
            rows = self.db.conn.execute(
                "SELECT id, plan_id, skill_id, mode, status, order_index, "
                "estimated_duration_min, actual_duration_min, learning_session_id, "
                "created_at, updated_at FROM study_plan_items "
                "WHERE plan_id = ? ORDER BY order_index, created_at",
                (plan_id,),
            ).fetchall()
        return [self._row_to_plan_item(r) for r in rows]

    def get_with_items(
        self, plan_id: str
    ) -> tuple[StudyPlan | None, list[StudyPlanItem]]:
        with self.db.lock:
            row = self.db.conn.execute(
                "SELECT id, session_id, tree_version, goal, status, "
                "created_at, updated_at FROM study_plans WHERE id = ?",
                (plan_id,),
            ).fetchone()
            plan = self._row_to_plan(row) if row else None
            items = self.get_items(plan_id)
        return plan, items
