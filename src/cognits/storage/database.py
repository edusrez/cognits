"""Database holder: single connection, RLock, schema migration, transaction().

Extracted from db.py (Phase 1 split). Owns the one sqlite3.Connection shared
across all domain repositories, plus the reentrant lock that serializes access.
"""

from __future__ import annotations

import os
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path

from cognits.constants import BUSY_TIMEOUT_MS

SCHEMA_VERSION = 1

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
        reports TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL DEFAULT (datetime('now'))
    );
    CREATE INDEX IF NOT EXISTS idx_messages_session
        ON messages(session_id, created_at);

    CREATE TABLE IF NOT EXISTS notes (
        id TEXT PRIMARY KEY,
        title TEXT NOT NULL,
        content TEXT NOT NULL DEFAULT '',
        sort_order REAL NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        updated_at TEXT NOT NULL DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS session_config (
        session_id TEXT PRIMARY KEY,
        provider TEXT NOT NULL DEFAULT 'deepseek',
        model TEXT NOT NULL DEFAULT 'deepseek-v4-pro',
        reasoning TEXT NOT NULL DEFAULT 'max',
        agent_id TEXT NOT NULL DEFAULT 'orchestrator',
        skill_id TEXT NOT NULL DEFAULT ''
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

    CREATE TABLE IF NOT EXISTS skills (
        id TEXT PRIMARY KEY,
        domain TEXT NOT NULL,
        name TEXT NOT NULL,
        description TEXT NOT NULL DEFAULT '',
        bloom_level TEXT NOT NULL DEFAULT '',
        difficulty REAL NOT NULL DEFAULT 0.5,
        parent_skill_id TEXT,
        status TEXT NOT NULL DEFAULT 'active',
        source TEXT NOT NULL DEFAULT '',
        tree_version INTEGER NOT NULL DEFAULT 1,
        superseded_by TEXT,
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        updated_at TEXT NOT NULL DEFAULT (datetime('now'))
    );
    CREATE INDEX IF NOT EXISTS idx_skills_domain ON skills(domain);
    CREATE INDEX IF NOT EXISTS idx_skills_parent ON skills(parent_skill_id);

    CREATE VIRTUAL TABLE IF NOT EXISTS skills_fts USING fts5(
        name, description,
        content='skills',
        content_rowid='rowid',
        tokenize='unicode61'
    );
    CREATE TRIGGER IF NOT EXISTS skills_fts_ai AFTER INSERT ON skills BEGIN
        INSERT INTO skills_fts(rowid, name, description)
        VALUES (new.rowid, new.name, new.description);
    END;
    CREATE TRIGGER IF NOT EXISTS skills_fts_ad AFTER DELETE ON skills BEGIN
        INSERT INTO skills_fts(skills_fts, rowid, name, description)
        VALUES ('delete', old.rowid, old.name, old.description);
    END;
    CREATE TRIGGER IF NOT EXISTS skills_fts_au AFTER UPDATE ON skills BEGIN
        INSERT INTO skills_fts(skills_fts, rowid, name, description)
        VALUES ('delete', old.rowid, old.name, old.description);
        INSERT INTO skills_fts(rowid, name, description)
        VALUES (new.rowid, new.name, new.description);
    END;

    CREATE TABLE IF NOT EXISTS skill_prerequisites (
        skill_id TEXT NOT NULL,
        prereq_id TEXT NOT NULL,
        edge_type TEXT NOT NULL CHECK (edge_type IN ('prereq','coreq','related','soft_prereq')),
        proof_query TEXT NOT NULL DEFAULT '',
        build_id TEXT,
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        PRIMARY KEY (skill_id, prereq_id, edge_type),
        FOREIGN KEY (skill_id) REFERENCES skills(id),
        FOREIGN KEY (prereq_id) REFERENCES skills(id)
    );
    CREATE INDEX IF NOT EXISTS idx_prereqs_skill ON skill_prerequisites(skill_id);
    CREATE INDEX IF NOT EXISTS idx_prereqs_prereq ON skill_prerequisites(prereq_id);

    CREATE TABLE IF NOT EXISTS skill_builds (
        id TEXT PRIMARY KEY,
        session_id TEXT,
        trigger TEXT NOT NULL DEFAULT '',
        skill_count INTEGER NOT NULL DEFAULT 0,
        added INTEGER NOT NULL DEFAULT 0,
        modified INTEGER NOT NULL DEFAULT 0,
        superseded INTEGER NOT NULL DEFAULT 0,
        started_at TEXT NOT NULL DEFAULT (datetime('now')),
        finished_at TEXT,
        status TEXT NOT NULL DEFAULT 'running',
        summary TEXT NOT NULL DEFAULT ''
    );

    CREATE TABLE IF NOT EXISTS learner_state (
        skill_id TEXT PRIMARY KEY,
        alpha REAL NOT NULL DEFAULT 1.0,
        beta REAL NOT NULL DEFAULT 1.0,
        p_mastery REAL NOT NULL DEFAULT 0.5,
        status_enum TEXT NOT NULL DEFAULT 'not_seen',
        retrievability REAL,
        stability REAL,
        difficulty REAL,
        reps INTEGER NOT NULL DEFAULT 0,
        lapses INTEGER NOT NULL DEFAULT 0,
        last_review TEXT,
        next_review TEXT,
        scaffolding_level INTEGER NOT NULL DEFAULT 1,
        updated_at TEXT NOT NULL DEFAULT (datetime('now')),
        FOREIGN KEY (skill_id) REFERENCES skills(id)
    );

    CREATE TABLE IF NOT EXISTS study_plans (
        id TEXT PRIMARY KEY,
        session_id TEXT,
        tree_version INTEGER NOT NULL,
        goal TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL DEFAULT 'active',
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        updated_at TEXT NOT NULL DEFAULT (datetime('now'))
    );
    CREATE INDEX IF NOT EXISTS idx_study_plans_status ON study_plans(status);

    CREATE TABLE IF NOT EXISTS study_plan_items (
        id TEXT PRIMARY KEY,
        plan_id TEXT NOT NULL,
        skill_id TEXT NOT NULL,
        mode TEXT NOT NULL DEFAULT 'socratic',
        status TEXT NOT NULL DEFAULT 'pending',
        order_index INTEGER NOT NULL DEFAULT 0,
        estimated_duration_min INTEGER,
        actual_duration_min INTEGER,
        learning_session_id TEXT,
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        updated_at TEXT NOT NULL DEFAULT (datetime('now')),
        FOREIGN KEY (plan_id) REFERENCES study_plans(id),
        FOREIGN KEY (skill_id) REFERENCES skills(id)
    );
    CREATE INDEX IF NOT EXISTS idx_plan_items_plan ON study_plan_items(plan_id);
    CREATE INDEX IF NOT EXISTS idx_plan_items_status ON study_plan_items(status);

    CREATE TABLE IF NOT EXISTS pedagogical_plans (
        skill_id TEXT PRIMARY KEY,
        content TEXT NOT NULL DEFAULT '',
        generated_at TEXT NOT NULL DEFAULT (datetime('now')),
        updated_at TEXT NOT NULL DEFAULT (datetime('now')),
        FOREIGN KEY (skill_id) REFERENCES skills(id)
    );

    CREATE TABLE IF NOT EXISTS report_chunks (
        id TEXT PRIMARY KEY,
        report_id TEXT NOT NULL,
        text TEXT NOT NULL,
        source_type TEXT NOT NULL DEFAULT 'web',
        topic TEXT NOT NULL DEFAULT '',
        chunk_index INTEGER NOT NULL DEFAULT 0
    );
    CREATE INDEX IF NOT EXISTS idx_chunks_report ON report_chunks(report_id);

    CREATE VIRTUAL TABLE IF NOT EXISTS chunks_vec USING vec0(
        embedding float[1024]
    );
"""


class Database:
    """Single sqlite3.Connection + reentrant lock shared across repos."""

    def __init__(self, db_path: Path | str) -> None:
        self.db_path = str(db_path)
        self.lock = threading.RLock()
        self._closed = False
        self.conn = sqlite3.connect(
            self.db_path, check_same_thread=False, isolation_level=None
        )
        try:
            self.conn.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")
            self.conn.execute("PRAGMA journal_mode = WAL")
            self.conn.execute("PRAGMA synchronous = NORMAL")
            self._check_fts5()
            self.conn.enable_load_extension(True)
            import sqlite_vec
            sqlite_vec.load(self.conn)
            self.conn.enable_load_extension(False)
            self._migrate()
        except BaseException:
            self.conn.close()
            raise

    # -- lifecycle -----------------------------------------------------------

    def shutdown(self) -> None:
        if self._closed:
            return
        with self.lock:
            self.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            self.conn.close()
            self._closed = True

    # -- transactions --------------------------------------------------------

    @contextmanager
    def transaction(self):
        with self.lock:
            self.conn.execute("BEGIN")
            try:
                yield
                self.conn.execute("COMMIT")
            except Exception:
                self.conn.execute("ROLLBACK")
                raise

    # -- internal ------------------------------------------------------------

    def _check_fts5(self) -> None:
        try:
            self.conn.execute(
                "CREATE VIRTUAL TABLE temp.__fts5_check USING fts5(x)"
            )
            self.conn.execute("DROP TABLE temp.__fts5_check")
        except sqlite3.OperationalError as e:
            raise RuntimeError(
                "Your Python installation ships a SQLite without FTS5, which "
                "Cognits needs for report search. Install an official Python "
                "from python.org or one managed by uv (uv python install 3.12)."
            ) from e

    def _migrate(self) -> None:
        cur = self.conn.cursor()
        version = cur.execute("PRAGMA user_version").fetchone()[0]

        if version == 0:
            has_reports = cur.execute(
                "SELECT COUNT(*) FROM sqlite_master"
                " WHERE type='table' AND name='reports'"
            ).fetchone()[0]
            if has_reports:
                self._backup()
                cur.execute("DROP TABLE IF EXISTS reports_fts")
                has_api_key = cur.execute(
                    "SELECT COUNT(*) FROM pragma_table_info('session_config')"
                    " WHERE name='api_key'"
                ).fetchone()[0]
                if has_api_key:
                    cur.execute(
                        "ALTER TABLE session_config DROP COLUMN api_key"
                    )
                has_skill_id = cur.execute(
                    "SELECT COUNT(*) FROM pragma_table_info('session_config')"
                    " WHERE name='skill_id'"
                ).fetchone()[0]
                if not has_skill_id:
                    cur.execute(
                        "ALTER TABLE session_config ADD COLUMN"
                        " skill_id TEXT NOT NULL DEFAULT ''"
                    )

        cur.executescript(BASE_SCHEMA)

        if version < 1:
            has_reports = cur.execute(
                "SELECT COUNT(*) FROM pragma_table_info('messages')"
                " WHERE name='reports'"
            ).fetchone()[0]
            if not has_reports:
                cur.execute(
                    "ALTER TABLE messages ADD COLUMN"
                    " reports TEXT NOT NULL DEFAULT ''"
                )

            has_scaffold = cur.execute(
                "SELECT COUNT(*) FROM pragma_table_info('learner_state')"
                " WHERE name='scaffolding_level'"
            ).fetchone()[0]
            if not has_scaffold:
                cur.execute(
                    "ALTER TABLE learner_state ADD COLUMN"
                    " scaffolding_level INTEGER NOT NULL DEFAULT 1"
                )

        if version < SCHEMA_VERSION:
            cur.execute("INSERT INTO reports_fts(reports_fts) VALUES('rebuild')")
            cur.execute("INSERT INTO skills_fts(skills_fts) VALUES('rebuild')")
            cur.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

    def _backup(self) -> None:
        bak = self.db_path + ".bak"
        try:
            os.remove(bak)
        except FileNotFoundError:
            pass
        escaped = bak.replace("'", "''")
        self.conn.execute(f"VACUUM INTO '{escaped}'")

    # -- vector search -------------------------------------------------------

    def vector_index(self, chunks: list[dict]) -> int:
        with self.lock:
            count = 0
            for chunk in chunks:
                rowid = _chunk_id_to_int(chunk["id"])
                self.conn.execute(
                    """INSERT OR REPLACE INTO report_chunks
                       (rowid, id, report_id, text, source_type, topic, chunk_index)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (rowid, chunk["id"], chunk["report_id"], chunk["text"],
                     chunk.get("source_type", "web"), chunk.get("topic", ""),
                     chunk.get("chunk_index", 0)),
                )
                self.conn.execute(
                    "INSERT OR REPLACE INTO chunks_vec (rowid, embedding) VALUES (?, ?)",
                    (rowid, _embed_to_json(chunk["embedding"])),
                )
                count += 1
        return count

    def vector_search(self, query_embedding, max_results: int = 10) -> list[dict]:
        emb_json = _embed_to_json(query_embedding)
        with self.lock:
            rows = self.conn.execute(
                """SELECT rc.id, rc.report_id, rc.text, rc.source_type, rc.topic,
                          rc.chunk_index, vec_distance_L2(cv.embedding, ?) as dist
                   FROM chunks_vec cv
                   JOIN report_chunks rc ON rc.rowid = cv.rowid
                   ORDER BY dist LIMIT ?""",
                (emb_json, max_results),
            ).fetchall()
        return [
            {
                "id": r[0], "report_id": r[1], "text": r[2],
                "source_type": r[3], "topic": r[4], "chunk_index": r[5],
                "distance": r[6],
            }
            for r in rows
        ]

    def vector_count(self) -> int:
        with self.lock:
            return self.conn.execute("SELECT COUNT(*) FROM chunks_vec").fetchone()[0]


def _chunk_id_to_int(chunk_id: str) -> int:
    return abs(hash(chunk_id)) % (2**62)


def _embed_to_json(floats) -> str:
    import json
    return f"[{','.join(str(f) for f in floats)}]"
