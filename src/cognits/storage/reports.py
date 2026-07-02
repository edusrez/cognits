"""Report repository with FTS5 search."""

from __future__ import annotations

import json

from cognits.storage.database import Database
from cognits.storage.models import (
    _SORT_SQL,
    _clamp,
    _unmarshal_sources,
    build_fts5_query,
    escape_like,
    Report,
)


class ReportRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    @staticmethod
    def _row_to_report(row: tuple) -> Report:
        return Report(
            id=row[0],
            session_id=row[1],
            title=row[2],
            content=row[3],
            summary=row[4] or "",
            sources=_unmarshal_sources(row[5]),
            subagent=row[6],
            created_at=row[7],
        )

    def save(self, r: Report) -> None:
        src_json = json.dumps(r.sources if r.sources is not None else [])
        with self.db.lock:
            self.db.conn.execute(
                """INSERT INTO reports (id, session_id, title, content, summary, sources, subagent)
                   VALUES (?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(id) DO UPDATE SET
                       session_id = excluded.session_id,
                       title      = excluded.title,
                       content    = excluded.content,
                       summary    = excluded.summary,
                       sources    = excluded.sources,
                       subagent   = excluded.subagent""",
                (r.id, r.session_id, r.title, r.content, r.summary, src_json, r.subagent),
            )

    def get(self, report_id: str) -> Report | None:
        with self.db.lock:
            row = self.db.conn.execute(
                """SELECT id, session_id, title, content, summary, sources, subagent, created_at
                   FROM reports WHERE id = ?""",
                (report_id,),
            ).fetchone()
        if row is None:
            return None
        return self._row_to_report(row)

    def search(self, page: int, limit: int, sort: str, search: str) -> dict:
        page, limit = _clamp(page, limit)
        sort_sql = _SORT_SQL.get(sort, "created_at DESC")

        where_sql = ""
        args: list = []
        if search:
            where_sql = r"WHERE title LIKE ? ESCAPE '\' OR summary LIKE ? ESCAPE '\'"
            term = f"%{escape_like(search)}%"
            args = [term, term]

        with self.db.lock:
            total = self.db.conn.execute(
                f"SELECT COUNT(*) FROM reports {where_sql}", args
            ).fetchone()[0]
            total_pages = max((total + limit - 1) // limit, 1)
            offset = (page - 1) * limit
            rows = self.db.conn.execute(
                f"""SELECT id, session_id, title, content, summary, sources, subagent, created_at
                    FROM reports {where_sql} ORDER BY {sort_sql} LIMIT ? OFFSET ?""",
                args + [limit, offset],
            ).fetchall()

        return {
            "reports": [self._row_to_report(r).to_json() for r in rows],
            "total": total,
            "page": page,
            "totalPages": total_pages,
        }

    def search_fts(self, page: int, limit: int, sort: str, search: str) -> dict:
        page, limit = _clamp(page, limit)

        fts_query = build_fts5_query(search)
        if not fts_query:
            return {"reports": [], "total": 0, "page": page, "totalPages": 1}

        sort_sql = {
            "date_asc": "r.created_at ASC",
            "title_asc": "r.title ASC",
            "title_desc": "r.title DESC",
        }.get(sort, "score")

        with self.db.lock:
            total = self.db.conn.execute(
                "SELECT COUNT(*) FROM reports_fts WHERE reports_fts MATCH ?",
                (fts_query,),
            ).fetchone()[0]
            total_pages = max((total + limit - 1) // limit, 1)
            offset = (page - 1) * limit
            rows = self.db.conn.execute(
                f"""SELECT r.id, r.session_id, r.title, r.content, r.summary, r.sources, r.subagent, r.created_at,
                           highlight(reports_fts, 0, '<mark>', '</mark>') AS title_highlighted,
                           bm25(reports_fts, 10.0, 3.0, 1.0) AS score
                    FROM reports_fts
                    JOIN reports r ON r.rowid = reports_fts.rowid
                    WHERE reports_fts MATCH ?
                    ORDER BY {sort_sql}
                    LIMIT ? OFFSET ?""",
                (fts_query, limit, offset),
            ).fetchall()

        items = []
        for row in rows:
            item = self._row_to_report(row[:8]).to_json()
            item["titleHighlighted"] = row[8]
            item["score"] = row[9]
            items.append(item)

        return {"reports": items, "total": total, "page": page, "totalPages": total_pages}

    def delete(self, report_id: str) -> None:
        with self.db.lock:
            self.db.conn.execute("DELETE FROM reports WHERE id = ?", (report_id,))
