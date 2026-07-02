"""Message repository — CRUD for chat messages."""

from __future__ import annotations

from cognits.storage.database import Database
from cognits.storage.models import MessageRow


class MessageRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    def save(self, session_id: str, msgs: list[MessageRow]) -> None:
        with self.db.lock:
            cur = self.db.conn.cursor()
            cur.execute("BEGIN")
            try:
                cur.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
                cur.executemany(
                    """INSERT INTO messages (session_id, role, content, reasoning, report_id, report_title, reports)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    [
                        (session_id, m.role, m.content, m.reasoning, m.report_id, m.report_title, m.reports)
                        for m in msgs
                    ],
                )
                cur.execute("COMMIT")
            except BaseException:
                cur.execute("ROLLBACK")
                raise

    def append(self, session_id: str, m: MessageRow) -> None:
        with self.db.lock:
            self.db.conn.execute(
                """INSERT INTO messages (session_id, role, content, reasoning, report_id, report_title, reports)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (session_id, m.role, m.content, m.reasoning, m.report_id, m.report_title, m.reports),
            )

    def load(self, session_id: str) -> list[MessageRow]:
        with self.db.lock:
            rows = self.db.conn.execute(
                """SELECT id, session_id, role, content, COALESCE(reasoning,''),
                          COALESCE(report_id,''), COALESCE(report_title,''),
                          COALESCE(reports,''), created_at
                   FROM messages WHERE session_id = ? ORDER BY id ASC""",
                (session_id,),
            ).fetchall()
        return [MessageRow(*row) for row in rows]

    def delete_by_session(self, session_id: str) -> None:
        with self.db.lock:
            self.db.conn.execute(
                "DELETE FROM messages WHERE session_id = ?", (session_id,)
            )
