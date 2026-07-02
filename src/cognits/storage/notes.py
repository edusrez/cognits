"""Note repository."""

from __future__ import annotations

from cognits.storage.database import Database
from cognits.storage.models import Note, new_note_id


class NoteRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    def create(self, title: str) -> Note:
        note = Note(
            id=new_note_id(),
            title=title,
            content="",
            created_at="",
            updated_at="",
        )
        with self.db.lock:
            self.db.conn.execute(
                "INSERT INTO notes (id, title) VALUES (?, ?)",
                (note.id, note.title),
            )
            row = self.db.conn.execute(
                "SELECT id, title, content, created_at, updated_at FROM notes WHERE id = ?",
                (note.id,),
            ).fetchone()
        return Note(*row)

    def list_all(self) -> list[Note]:
        with self.db.lock:
            rows = self.db.conn.execute(
                "SELECT id, title, content, created_at, updated_at FROM notes ORDER BY sort_order, created_at DESC"
            ).fetchall()
        return [Note(*row) for row in rows]

    def get(self, note_id: str) -> Note | None:
        with self.db.lock:
            row = self.db.conn.execute(
                "SELECT id, title, content, created_at, updated_at FROM notes WHERE id = ?",
                (note_id,),
            ).fetchone()
        return Note(*row) if row else None

    def rename(self, note_id: str, title: str) -> None:
        with self.db.lock:
            self.db.conn.execute(
                "UPDATE notes SET title = ?, updated_at = datetime('now') WHERE id = ?",
                (title, note_id),
            )

    def delete(self, note_id: str) -> None:
        with self.db.lock:
            self.db.conn.execute("DELETE FROM notes WHERE id = ?", (note_id,))

    def save_content(self, note_id: str, content: str) -> None:
        with self.db.lock:
            self.db.conn.execute(
                "UPDATE notes SET content = ?, updated_at = datetime('now') WHERE id = ?",
                (content, note_id),
            )

    def reorder(self, ordered_ids: list[str]) -> None:
        with self.db.transaction():
            for i, nid in enumerate(ordered_ids):
                self.db.conn.execute(
                    "UPDATE notes SET sort_order = ? WHERE id = ?",
                    (float(i), nid),
                )
