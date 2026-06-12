"""Port de internal/storage/db.go: SQLite con FTS5 de contenido externo.

Una única conexión serializada con un lock de hilos: con un solo usuario
local no hay contención real y evita los problemas de pool. Los métodos son
síncronos; el código async los invoca vía asyncio.to_thread.
"""

from __future__ import annotations

import json
import os
import secrets
import sqlite3
import threading
from dataclasses import dataclass
from pathlib import Path

SCHEMA_VERSION = 1

# baseSchema es idempotente (CREATE IF NOT EXISTS). reports_fts es una tabla
# FTS5 de contenido externo: el texto vive solo en reports y los triggers
# mantienen el índice sincronizado, sin duplicar datos.
BASE_SCHEMA = """
    CREATE TABLE IF NOT EXISTS reports (
        id TEXT PRIMARY KEY,
        session_id TEXT NOT NULL,
        title TEXT NOT NULL,
        content TEXT NOT NULL,
        summary TEXT,
        sources TEXT NOT NULL DEFAULT '[]',
        subagent TEXT NOT NULL DEFAULT 'web_researcher',
        created_at TEXT NOT NULL DEFAULT (datetime('now'))
    );
    CREATE INDEX IF NOT EXISTS idx_reports_session
        ON reports(session_id, created_at);

    CREATE TABLE IF NOT EXISTS messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id TEXT NOT NULL,
        role TEXT NOT NULL CHECK (role IN ('user','assistant','system','tool')),
        content TEXT NOT NULL,
        reasoning TEXT,
        report_id TEXT,
        report_title TEXT,
        created_at TEXT NOT NULL DEFAULT (datetime('now'))
    );
    CREATE INDEX IF NOT EXISTS idx_messages_session
        ON messages(session_id, created_at);

    CREATE TABLE IF NOT EXISTS session_config (
        session_id TEXT PRIMARY KEY,
        provider TEXT NOT NULL DEFAULT 'deepseek',
        model TEXT NOT NULL DEFAULT 'deepseek-v4-pro',
        reasoning TEXT NOT NULL DEFAULT 'max',
        agent_id TEXT NOT NULL DEFAULT 'orquestador'
    );

    CREATE VIRTUAL TABLE IF NOT EXISTS reports_fts USING fts5(
        title, summary, content,
        content='reports',
        content_rowid='rowid',
        tokenize='unicode61'
    );

    CREATE TRIGGER IF NOT EXISTS reports_fts_ai AFTER INSERT ON reports BEGIN
        INSERT INTO reports_fts(rowid, title, summary, content)
        VALUES (new.rowid, new.title, new.summary, new.content);
    END;
    CREATE TRIGGER IF NOT EXISTS reports_fts_ad AFTER DELETE ON reports BEGIN
        INSERT INTO reports_fts(reports_fts, rowid, title, summary, content)
        VALUES ('delete', old.rowid, old.title, old.summary, old.content);
    END;
    CREATE TRIGGER IF NOT EXISTS reports_fts_au AFTER UPDATE ON reports BEGIN
        INSERT INTO reports_fts(reports_fts, rowid, title, summary, content)
        VALUES ('delete', old.rowid, old.title, old.summary, old.content);
        INSERT INTO reports_fts(rowid, title, summary, content)
        VALUES (new.rowid, new.title, new.summary, new.content);
    END;
"""


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
    created_at: str = ""

    def to_json(self) -> dict:
        return {
            "id": self.id,
            "sessionId": self.session_id,
            "role": self.role,
            "content": self.content,
            "reasoning": self.reasoning,
            "reportId": self.report_id,
            "reportTitle": self.report_title,
            "createdAt": self.created_at,
        }


@dataclass
class SessionConfigRow:
    session_id: str = ""
    provider: str = ""
    model: str = ""
    reasoning: str = ""
    agent_id: str = ""

    def to_json(self) -> dict:
        return {
            "sessionId": self.session_id,
            "provider": self.provider,
            "model": self.model,
            "reasoning": self.reasoning,
            "agentId": self.agent_id,
        }

    @classmethod
    def from_json(cls, d: dict) -> "SessionConfigRow":
        return cls(
            session_id=d.get("sessionId") or "",
            provider=d.get("provider") or "",
            model=d.get("model") or "",
            reasoning=d.get("reasoning") or "",
            agent_id=d.get("agentId") or "",
        )


def new_report_id() -> str:
    return "r_" + secrets.token_hex(8)


def escape_like(s: str) -> str:
    # Neutraliza los comodines de LIKE; las cláusulas que lo usan llevan ESCAPE '\'.
    return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def build_fts5_query(raw: str) -> str:
    raw = raw.strip()
    if not raw:
        return ""
    processed = []
    for w in raw.split():
        # Dentro de una cadena FTS5 solo la comilla doble es especial: se
        # escapa doblándola. Trim no bastaba — una comilla interior (fo"o)
        # rompía la query y devolvía 500.
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


class ReportStore:
    def __init__(self, db_path: Path | str):
        self.db_path = str(db_path)
        self._lock = threading.Lock()
        # isolation_level=None: autocommit; las transacciones se abren con
        # BEGIN explícito. Misma semántica que database/sql en Go.
        self._conn = sqlite3.connect(
            self.db_path, check_same_thread=False, isolation_level=None
        )
        try:
            self._conn.execute("PRAGMA busy_timeout = 5000")
            self._conn.execute("PRAGMA journal_mode = WAL")
            self._conn.execute("PRAGMA synchronous = NORMAL")
            self._check_fts5()
            self._migrate()
        except BaseException:
            self._conn.close()
            raise

    def _check_fts5(self) -> None:
        try:
            self._conn.execute("CREATE VIRTUAL TABLE temp.__fts5_check USING fts5(x)")
            self._conn.execute("DROP TABLE temp.__fts5_check")
        except sqlite3.OperationalError as e:
            raise RuntimeError(
                "Tu instalación de Python trae un SQLite sin FTS5, que Cognits "
                "necesita para la búsqueda de informes. Instala un Python oficial "
                "de python.org o uno gestionado por uv (uv python install 3.12)."
            ) from e

    def _migrate(self) -> None:
        cur = self._conn.cursor()
        version = cur.execute("PRAGMA user_version").fetchone()[0]

        if version == 0:
            has_reports = cur.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='reports'"
            ).fetchone()[0]
            if has_reports:
                # DB heredada (pre-versionado): copia de seguridad y limpieza de
                # estructuras incompatibles antes de recrearlas con BASE_SCHEMA.
                self._backup()
                cur.execute("DROP TABLE IF EXISTS reports_fts")
                has_api_key = cur.execute(
                    "SELECT COUNT(*) FROM pragma_table_info('session_config') WHERE name='api_key'"
                ).fetchone()[0]
                if has_api_key:
                    cur.execute("ALTER TABLE session_config DROP COLUMN api_key")

        cur.executescript(BASE_SCHEMA)

        if version < SCHEMA_VERSION:
            cur.execute("INSERT INTO reports_fts(reports_fts) VALUES('rebuild')")
            cur.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

    def _backup(self) -> None:
        bak = self.db_path + ".bak"
        try:
            os.remove(bak)
        except FileNotFoundError:
            pass
        escaped = bak.replace("'", "''")
        self._conn.execute(f"VACUUM INTO '{escaped}'")

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # --- reports ---

    def save(self, r: Report) -> None:
        src_json = json.dumps(r.sources if r.sources is not None else [])
        # Upsert explícito en vez de INSERT OR REPLACE: REPLACE borra+inserta
        # sin disparar los triggers de borrado, lo que corrompería el índice
        # FTS de contenido externo.
        with self._lock:
            self._conn.execute(
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
        with self._lock:
            row = self._conn.execute(
                """SELECT id, session_id, title, content, summary, sources, subagent, created_at
                   FROM reports WHERE id = ?""",
                (report_id,),
            ).fetchone()
        if row is None:
            return None
        return self._row_to_report(row)

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

    def search_reports(self, page: int, limit: int, sort: str, search: str) -> dict:
        page, limit = _clamp(page, limit)
        sort_sql = _SORT_SQL.get(sort, "created_at DESC")

        where_sql = ""
        args: list = []
        if search:
            where_sql = r"WHERE title LIKE ? ESCAPE '\' OR summary LIKE ? ESCAPE '\'"
            term = f"%{escape_like(search)}%"
            args = [term, term]

        with self._lock:
            total = self._conn.execute(
                f"SELECT COUNT(*) FROM reports {where_sql}", args
            ).fetchone()[0]
            total_pages = max((total + limit - 1) // limit, 1)
            offset = (page - 1) * limit
            rows = self._conn.execute(
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

    def search_reports_fts(self, page: int, limit: int, sort: str, search: str) -> dict:
        page, limit = _clamp(page, limit)

        fts_query = build_fts5_query(search)
        if not fts_query:
            # Input sin términos útiles (solo comodines/paréntesis): MATCH '' falla.
            return {"reports": [], "total": 0, "page": page, "totalPages": 1}

        sort_sql = {
            "date_asc": "r.created_at ASC",
            "title_asc": "r.title ASC",
            "title_desc": "r.title DESC",
        }.get(sort, "score")

        with self._lock:
            total = self._conn.execute(
                "SELECT COUNT(*) FROM reports_fts WHERE reports_fts MATCH ?",
                (fts_query,),
            ).fetchone()[0]
            total_pages = max((total + limit - 1) // limit, 1)
            offset = (page - 1) * limit
            rows = self._conn.execute(
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

    def delete_report(self, report_id: str) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM reports WHERE id = ?", (report_id,))

    # --- session config ---

    def save_session_config(self, cfg: SessionConfigRow) -> None:
        with self._lock:
            self._conn.execute(
                """INSERT OR REPLACE INTO session_config (session_id, provider, model, reasoning, agent_id)
                   VALUES (?, ?, ?, ?, ?)""",
                (cfg.session_id, cfg.provider, cfg.model, cfg.reasoning, cfg.agent_id),
            )

    def load_session_config(self, session_id: str) -> SessionConfigRow | None:
        with self._lock:
            row = self._conn.execute(
                """SELECT session_id, provider, model, reasoning, agent_id
                   FROM session_config WHERE session_id = ?""",
                (session_id,),
            ).fetchone()
        if row is None:
            return None
        return SessionConfigRow(*row)

    def delete_session_config(self, session_id: str) -> None:
        with self._lock:
            self._conn.execute(
                "DELETE FROM session_config WHERE session_id = ?", (session_id,)
            )

    # --- messages ---

    def save_messages(self, session_id: str, msgs: list[MessageRow]) -> None:
        with self._lock:
            cur = self._conn.cursor()
            cur.execute("BEGIN")
            try:
                cur.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
                cur.executemany(
                    """INSERT INTO messages (session_id, role, content, reasoning, report_id, report_title)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    [
                        (session_id, m.role, m.content, m.reasoning, m.report_id, m.report_title)
                        for m in msgs
                    ],
                )
                cur.execute("COMMIT")
            except BaseException:
                cur.execute("ROLLBACK")
                raise

    def append_message(self, session_id: str, m: MessageRow) -> None:
        # Inserta una sola fila al final del historial; save_messages reescribe
        # la sesión entera y su transacción crece con la conversación.
        with self._lock:
            self._conn.execute(
                """INSERT INTO messages (session_id, role, content, reasoning, report_id, report_title)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (session_id, m.role, m.content, m.reasoning, m.report_id, m.report_title),
            )

    def load_messages(self, session_id: str) -> list[MessageRow]:
        with self._lock:
            rows = self._conn.execute(
                """SELECT id, session_id, role, content, COALESCE(reasoning,''),
                          COALESCE(report_id,''), COALESCE(report_title,''), created_at
                   FROM messages WHERE session_id = ? ORDER BY id ASC""",
                (session_id,),
            ).fetchall()
        return [MessageRow(*row) for row in rows]

    def delete_messages_by_session(self, session_id: str) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
