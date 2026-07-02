"""Port of internal/storage/db.go: SQLite with external-content FTS5.

A single connection serialized with a thread lock: with one local user
there is no real contention and it avoids pool issues. Methods are
synchronous; async code invokes them via asyncio.to_thread.
"""

from __future__ import annotations

import json
import os
import secrets
import sqlite3
import threading
from dataclasses import dataclass
from pathlib import Path

from cognits.constants import BUSY_TIMEOUT_MS

SCHEMA_VERSION = 1

# The base schema is idempotent (CREATE IF NOT EXISTS). reports_fts is an
# external-content FTS5 table: the text lives only in reports and the
# triggers keep the index in sync, without duplicating data.
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

    -- Skill tree: DAG of learnable concepts with typed prerequisites.
    -- Each node carries provenance (source, superseded_by) so iterative
    -- builds can supersede rather than delete (preserves history).
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

    -- External-content FTS5 over skills (same pattern as reports_fts).
    -- A TEXT PRIMARY KEY table still has an implicit rowid unless declared
    -- WITHOUT ROWID, so content_rowid='rowid' works.
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

    -- Typed edges between skills. PK (skill_id, prereq_id, edge_type)
    -- allows the same pair to coexist as both prereq and related.
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

    -- One row per skill_planner pass. Allows diffing builds and tracking
    -- what the planner added/modified/superseded in each iteration.
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

    -- Per-skill mastery state (BKT Beta priors + FSRS schedule). Updated by
    -- the future evaluator subagent; v0.0.6 only seeds rows on first insert.
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
        updated_at TEXT NOT NULL DEFAULT (datetime('now')),
        FOREIGN KEY (skill_id) REFERENCES skills(id)
    );

    -- One active study plan per user at a time (v0.0.6). Tree_version
    -- is a snapshot so the planner can detect staleness when the tree
    -- has been mutated since the plan was generated.
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

    -- Ordered list of learning sessions inside a plan. Items are never
    -- deleted – status moves through pending -> in_progress -> done |
    -- skipped | goal_removed so the planner can diff between plan
    -- revisions.
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

    -- One pedagogical plan per skill (the Study Planner generates these
    -- by researching teaching methodology and synthesising a stage-based
    -- Markdown guide for the Teacher to follow during a learning session).
    CREATE TABLE IF NOT EXISTS pedagogical_plans (
        skill_id TEXT PRIMARY KEY,
        content TEXT NOT NULL DEFAULT '',
        generated_at TEXT NOT NULL DEFAULT (datetime('now')),
        updated_at TEXT NOT NULL DEFAULT (datetime('now')),
        FOREIGN KEY (skill_id) REFERENCES skills(id)
    );
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
    reports: str = ""
    created_at: str = ""

    def to_json(self) -> dict:
        result = {
            "id": self.id,
            "sessionId": self.session_id,
            "role": self.role,
            "content": self.content,
            "reasoning": self.reasoning,
            "createdAt": self.created_at,
        }
        if self.reports:
            try:
                result["reports"] = json.loads(self.reports)
            except (json.JSONDecodeError, TypeError):
                pass
        elif self.report_id:
            result["reports"] = [{"reportId": self.report_id, "reportTitle": self.report_title}]
        return result


@dataclass
class SessionConfigRow:
    session_id: str = ""
    provider: str = ""
    model: str = ""
    reasoning: str = ""
    agent_id: str = ""
    skill_id: str = ""

    def to_json(self) -> dict:
        return {
            "sessionId": self.session_id,
            "provider": self.provider,
            "model": self.model,
            "reasoning": self.reasoning,
            "agentId": self.agent_id,
            "skillId": self.skill_id,
        }

    @classmethod
    def from_json(cls, d: dict) -> "SessionConfigRow":
        return cls(
            session_id=d.get("sessionId") or "",
            provider=d.get("provider") or "",
            model=d.get("model") or "",
            reasoning=d.get("reasoning") or "",
            agent_id=d.get("agentId") or "",
            skill_id=d.get("skillId") or "",
        )


@dataclass
class Note:
    id: str = ""
    title: str = ""
    content: str = ""
    created_at: str = ""
    updated_at: str = ""

    def to_json(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "content": self.content,
            "createdAt": self.created_at,
            "updatedAt": self.updated_at,
        }


@dataclass
class Skill:
    id: str = ""
    domain: str = ""
    name: str = ""
    description: str = ""
    bloom_level: str = ""
    difficulty: float = 0.5
    parent_skill_id: str = ""
    status: str = "active"
    source: str = ""
    tree_version: int = 1
    superseded_by: str = ""
    created_at: str = ""
    updated_at: str = ""

    def to_json(self) -> dict:
        return {
            "id": self.id,
            "domain": self.domain,
            "name": self.name,
            "description": self.description,
            "bloomLevel": self.bloom_level,
            "difficulty": self.difficulty,
            "parentSkillId": self.parent_skill_id,
            "status": self.status,
            "source": self.source,
            "treeVersion": self.tree_version,
            "supersededBy": self.superseded_by,
            "createdAt": self.created_at,
            "updatedAt": self.updated_at,
        }


@dataclass
class SkillPrereq:
    skill_id: str = ""
    prereq_id: str = ""
    edge_type: str = "prereq"
    proof_query: str = ""
    build_id: str = ""
    created_at: str = ""

    def to_json(self) -> dict:
        return {
            "skillId": self.skill_id,
            "prereqId": self.prereq_id,
            "edgeType": self.edge_type,
            "proofQuery": self.proof_query,
            "buildId": self.build_id,
            "createdAt": self.created_at,
        }


@dataclass
class SkillBuild:
    id: str = ""
    session_id: str = ""
    trigger: str = ""
    skill_count: int = 0
    added: int = 0
    modified: int = 0
    superseded: int = 0
    started_at: str = ""
    finished_at: str = ""
    status: str = "running"
    summary: str = ""

    def to_json(self) -> dict:
        return {
            "id": self.id,
            "sessionId": self.session_id,
            "trigger": self.trigger,
            "skillCount": self.skill_count,
            "added": self.added,
            "modified": self.modified,
            "superseded": self.superseded,
            "startedAt": self.started_at,
            "finishedAt": self.finished_at,
            "status": self.status,
            "summary": self.summary,
        }


@dataclass
class LearnerState:
    skill_id: str = ""
    alpha: float = 1.0
    beta: float = 1.0
    p_mastery: float = 0.5
    status_enum: str = "not_seen"
    retrievability: float | None = None
    stability: float | None = None
    difficulty: float | None = None
    reps: int = 0
    lapses: int = 0
    last_review: str | None = None
    next_review: str | None = None
    updated_at: str = ""

    def to_json(self) -> dict:
        return {
            "skillId": self.skill_id,
            "alpha": self.alpha,
            "beta": self.beta,
            "pMastery": self.p_mastery,
            "statusEnum": self.status_enum,
            "retrievability": self.retrievability,
            "stability": self.stability,
            "reps": self.reps,
            "lapses": self.lapses,
            "lastReview": self.last_review,
            "nextReview": self.next_review,
            "updatedAt": self.updated_at,
        }


@dataclass
class StudyPlan:
    id: str = ""
    session_id: str = ""
    tree_version: int = 0
    goal: str = ""
    status: str = "active"
    created_at: str = ""
    updated_at: str = ""

    def to_json(self) -> dict:
        return {
            "id": self.id,
            "sessionId": self.session_id,
            "treeVersion": self.tree_version,
            "goal": self.goal,
            "status": self.status,
            "createdAt": self.created_at,
            "updatedAt": self.updated_at,
        }


@dataclass
class StudyPlanItem:
    id: str = ""
    plan_id: str = ""
    skill_id: str = ""
    mode: str = "socratic"
    status: str = "pending"
    order_index: int = 0
    estimated_duration_min: int | None = None
    actual_duration_min: int | None = None
    learning_session_id: str | None = None
    created_at: str = ""
    updated_at: str = ""

    def to_json(self) -> dict:
        return {
            "id": self.id,
            "planId": self.plan_id,
            "skillId": self.skill_id,
            "mode": self.mode,
            "status": self.status,
            "orderIndex": self.order_index,
            "estimatedDurationMin": self.estimated_duration_min,
            "actualDurationMin": self.actual_duration_min,
            "learningSessionId": self.learning_session_id,
            "createdAt": self.created_at,
            "updatedAt": self.updated_at,
        }


def new_report_id() -> str:
    return "r_" + secrets.token_hex(8)


def new_note_id() -> str:
    return "n_" + secrets.token_hex(8)


def new_skill_id() -> str:
    return "k_" + secrets.token_hex(8)


def new_build_id() -> str:
    return "b_" + secrets.token_hex(8)


def new_plan_id() -> str:
    return "p_" + secrets.token_hex(8)


def new_plan_item_id() -> str:
    return "pi_" + secrets.token_hex(8)


# Edges between skills: edge_type is 'prereq' (skill_id needs prereq_id
# before being learnable), 'coreq' (taken together), or 'related'.
EDGE_TYPES = ("prereq", "coreq", "related", "soft_prereq")

# Study-plan lifecycle: one plan active at a time; old plans are superseded.
PLAN_STATUS = ("active", "superseded")

# Per-item progression. "goal_removed" preserves the row when the user
# discards a tree branch (study planner uses it for diffing).
PLAN_ITEM_STATUS = ("pending", "in_progress", "done", "skipped", "goal_removed")

PLAN_ITEM_MODE = ("socratic", "exercise", "project")

# Learner-state status progression (see learner/model.py for the policy):
# not_seen -> exploring -> practicing -> proficient -> mastered -> decaying
SKILL_STATUS = ("not_seen", "exploring", "practicing", "proficient", "mastered", "decaying")


def escape_like(s: str) -> str:
    # Neutralizes LIKE wildcards; clauses using this must carry ESCAPE '\'.
    return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def build_fts5_query(raw: str) -> str:
    raw = raw.strip()
    if not raw:
        return ""
    processed = []
    for w in raw.split():
        # Inside an FTS5 string only the double quote is special: it is
        # escaped by doubling it. Trimming was not enough — an interior
        # quote (fo"o) broke the query and returned 500.
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
        self._closed = False
        # isolation_level=None: autocommit; transactions are opened with an
        # explicit BEGIN. Same semantics as Go's database/sql.
        self._conn = sqlite3.connect(
            self.db_path, check_same_thread=False, isolation_level=None
        )
        try:
            self._conn.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")
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
                "Your Python installation ships a SQLite without FTS5, which "
                "Cognits needs for report search. Install an official Python "
                "from python.org or one managed by uv (uv python install 3.12)."
            ) from e

    def _migrate(self) -> None:
        cur = self._conn.cursor()
        version = cur.execute("PRAGMA user_version").fetchone()[0]

        if version == 0:
            has_reports = cur.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='reports'"
            ).fetchone()[0]
            if has_reports:
                # Inherited DB (pre-versioning): back up and clean incompatible
                # structures before recreating them with BASE_SCHEMA.
                self._backup()
                cur.execute("DROP TABLE IF EXISTS reports_fts")
                has_api_key = cur.execute(
                    "SELECT COUNT(*) FROM pragma_table_info('session_config') WHERE name='api_key'"
                ).fetchone()[0]
                if has_api_key:
                    cur.execute("ALTER TABLE session_config DROP COLUMN api_key")
                has_skill_id = cur.execute(
                    "SELECT COUNT(*) FROM pragma_table_info('session_config') WHERE name='skill_id'"
                ).fetchone()[0]
                if not has_skill_id:
                    cur.execute("ALTER TABLE session_config ADD COLUMN skill_id TEXT NOT NULL DEFAULT ''")

        cur.executescript(BASE_SCHEMA)

        if version < 1:
            has_reports = cur.execute(
                "SELECT COUNT(*) FROM pragma_table_info('messages') WHERE name='reports'"
            ).fetchone()[0]
            if not has_reports:
                cur.execute("ALTER TABLE messages ADD COLUMN reports TEXT NOT NULL DEFAULT ''")

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

    def shutdown(self) -> None:
        if self._closed:
            return
        with self._lock:
            self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            self._conn.close()
            self._closed = True

    # --- reports ---

    def save(self, r: Report) -> None:
        src_json = json.dumps(r.sources if r.sources is not None else [])
        # Explicit upsert instead of INSERT OR REPLACE: REPLACE deletes and
        # re-inserts without firing the delete triggers, which would corrupt
        # the external-content FTS index.
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
            # Input with no useful terms (only wildcards/parens): MATCH '' fails.
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

    # --- skill tree ---

    @staticmethod
    def _row_to_skill(row: tuple) -> Skill:
        return Skill(
            id=row[0],
            domain=row[1],
            name=row[2],
            description=row[3] or "",
            bloom_level=row[4] or "",
            difficulty=row[5],
            parent_skill_id=row[6] or "",
            status=row[7],
            source=row[8] or "",
            tree_version=row[9],
            superseded_by=row[10],
            created_at=row[11],
            updated_at=row[12],
        )

    def start_build(self, session_id: str, trigger: str) -> str:
        build_id = new_build_id()
        with self._lock:
            self._conn.execute(
                "INSERT INTO skill_builds (id, session_id, trigger) VALUES (?, ?, ?)",
                (build_id, session_id, trigger),
            )
        return build_id

    def finish_build(
        self,
        build_id: str,
        summary: str = "",
        status: str = "done",
        skill_count: int | None = None,
        added: int | None = None,
        modified: int | None = None,
        superseded: int | None = None,
    ) -> None:
        sets = ["finished_at = datetime('now')", "status = ?", "summary = ?"]
        args: list = [status, summary]
        for col, val in (
            ("skill_count", skill_count),
            ("added", added),
            ("modified", modified),
            ("superseded", superseded),
        ):
            if val is not None:
                sets.append(f"{col} = ?")
                args.append(val)
        args.append(build_id)
        with self._lock:
            self._conn.execute(
                f"UPDATE skill_builds SET {', '.join(sets)} WHERE id = ?",
                args,
            )

    def upsert_skill(self, s: Skill) -> None:
        with self._lock:
            self._conn.execute(
                """INSERT INTO skills (id, domain, name, description, bloom_level,
                                       difficulty, parent_skill_id, status,
                                       source, tree_version)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(id) DO UPDATE SET
                       domain         = excluded.domain,
                       name           = excluded.name,
                       description    = excluded.description,
                       bloom_level    = excluded.bloom_level,
                       difficulty     = excluded.difficulty,
                       parent_skill_id= excluded.parent_skill_id,
                       status         = excluded.status,
                       source         = excluded.source,
                       tree_version   = excluded.tree_version,
                       updated_at     = datetime('now')""",
                (
                    s.id, s.domain, s.name, s.description, s.bloom_level,
                    s.difficulty, s.parent_skill_id, s.status, s.source,
                    s.tree_version,
                ),
            )
            # Seed learner_state on first insert (alpha=beta=1 -> Beta(1,1)
            # prior, p_mastery=0.5). ON CONFLICT leaves an existing row alone.
            self._conn.execute(
                """INSERT INTO learner_state (skill_id) VALUES (?)
                   ON CONFLICT(skill_id) DO NOTHING""",
                (s.id,),
            )

    def get_skill(self, skill_id: str) -> Skill | None:
        with self._lock:
            row = self._conn.execute(
                """SELECT id, domain, name, description, bloom_level, difficulty,
                          parent_skill_id, status, source, tree_version, superseded_by,
                          created_at, updated_at
                   FROM skills WHERE id = ?""",
                (skill_id,),
            ).fetchone()
        return self._row_to_skill(row) if row else None

    def list_skills(self, domain: str | None = None) -> list[Skill]:
        sql = """SELECT id, domain, name, description, bloom_level, difficulty,
                        parent_skill_id, status, source, tree_version, superseded_by,
                        created_at, updated_at
                 FROM skills WHERE status = 'active'"""
        args: list = []
        if domain:
            sql += " AND domain = ?"
            args.append(domain)
        sql += " ORDER BY domain, name"
        with self._lock:
            rows = self._conn.execute(sql, args).fetchall()
        return [self._row_to_skill(r) for r in rows]

    def supersede_skill(self, skill_id: str, new_skill_id: str) -> None:
        with self._lock:
            self._conn.execute(
                """UPDATE skills
                   SET status = 'superseded',
                       superseded_by = ?,
                       updated_at = datetime('now')
                   WHERE id = ?""",
                (new_skill_id, skill_id),
            )

    def bump_tree_version(self) -> int:
        """Increment tree_version on ALL active skills in one transaction.
        Called by structural mutations (add_branch, prune_branch,
        re_eval_prereqs) in future versions. Returns the new version."""
        with self._lock:
            self._conn.execute(
                "UPDATE skills SET tree_version = tree_version + 1, "
                "updated_at = datetime('now') WHERE status = 'active'"
            )
            row = self._conn.execute(
                "SELECT MAX(tree_version) FROM skills WHERE status = 'active'"
            ).fetchone()
            return row[0] if row else 1

    def get_tree_version(self) -> int:
        """Current tree_version (max across active skills). Returns 1 if no
        skills exist yet. Used by the API and the Study Planner."""
        with self._lock:
            row = self._conn.execute(
                "SELECT MAX(tree_version) FROM skills WHERE status = 'active'"
            ).fetchone()
        return row[0] if row and row[0] is not None else 1

    def _prereq_reaches(self, start_id: str, target_id: str) -> bool:
        # Does target_id appear in the prereq-ancestor closure of start_id?
        # If so, adding edge (target_id prereqs start_id) would form a cycle.
        rows = self._conn.execute(
            """WITH RECURSIVE chain(id) AS (
                   SELECT prereq_id FROM skill_prerequisites
                   WHERE skill_id = ? AND edge_type = 'prereq'
                   UNION
                   SELECT sp.prereq_id
                   FROM skill_prerequisites sp
                   JOIN chain ON sp.skill_id = chain.id
                   WHERE sp.edge_type = 'prereq'
               )
               SELECT 1 FROM chain WHERE id = ? LIMIT 1""",
            (start_id, target_id),
        ).fetchone()
        return rows is not None

    def add_edge(
        self,
        skill_id: str,
        prereq_id: str,
        edge_type: str = "prereq",
        proof_query: str = "",
        build_id: str = "",
    ) -> None:
        if edge_type not in EDGE_TYPES:
            raise ValueError(f"invalid edge_type: {edge_type}")
        with self._lock:
            missing = []
            for sid in (skill_id, prereq_id):
                row = self._conn.execute(
                    "SELECT 1 FROM skills WHERE id = ?", (sid,)
                ).fetchone()
                if not row:
                    missing.append(sid)
            if missing:
                raise ValueError(
                    "skill not found: " + ", ".join(missing)
                    + ". Use the exact skill_id returned by upsert_skill."
                )
            # Cycle guard for 'prereq' edges: if prereq_id already depends
            # (directly or transitively) on skill_id, refuse the edge.
            if edge_type == "prereq" and self._prereq_reaches(prereq_id, skill_id):
                raise ValueError(
                    f"cycle detected: {prereq_id} already depends on {skill_id}"
                )
            self._conn.execute(
                """INSERT INTO skill_prerequisites
                       (skill_id, prereq_id, edge_type, proof_query, build_id)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(skill_id, prereq_id, edge_type) DO UPDATE SET
                       proof_query = excluded.proof_query,
                       build_id    = excluded.build_id""",
                (skill_id, prereq_id, edge_type, proof_query, build_id),
            )

    def get_prerequisites(self, skill_id: str) -> list[SkillPrereq]:
        with self._lock:
            rows = self._conn.execute(
                """SELECT skill_id, prereq_id, edge_type, proof_query, build_id, created_at
                   FROM skill_prerequisites WHERE skill_id = ?""",
                (skill_id,),
            ).fetchall()
        return [SkillPrereq(*r) for r in rows]

    def get_tree(self) -> dict:
        """Whole active tree: nodes + edges + tree_version. For frontend
        rendering and the API."""
        with self._lock:
            skill_rows = self._conn.execute(
                """SELECT id, domain, name, description, bloom_level, difficulty,
                          parent_skill_id, status, source, tree_version, superseded_by,
                          created_at, updated_at
                   FROM skills WHERE status = 'active'
                   ORDER BY domain, name"""
            ).fetchall()
            edge_rows = self._conn.execute(
                """SELECT skill_id, prereq_id, edge_type, proof_query, build_id, created_at
                   FROM skill_prerequisites
                   ORDER BY skill_id, edge_type"""
            ).fetchall()
            tv_row = self._conn.execute(
                "SELECT MAX(tree_version) FROM skills WHERE status = 'active'"
            ).fetchone()
        return {
            "skills": [self._row_to_skill(r).to_json() for r in skill_rows],
            "edges": [SkillPrereq(*r).to_json() for r in edge_rows],
            "treeVersion": tv_row[0] if tv_row and tv_row[0] is not None else 1,
        }

    def walk_topological(self) -> list[Skill]:
        """Kahn's algorithm over 'prereq' edges. Active skills only.
        Returns skills in dependency order (prereqs first). If a cycle is
        found in already-stored data, the participating skills are appended
        at the end rather than raising."""
        skills = self.list_skills()
        by_id = {s.id: s for s in skills}
        indeg: dict[str, int] = {s.id: 0 for s in skills}
        adj: dict[str, list[str]] = {s.id: [] for s in skills}
        with self._lock:
            rows = self._conn.execute(
                """SELECT skill_id, prereq_id FROM skill_prerequisites
                   WHERE edge_type = 'prereq'"""
            ).fetchall()
        for skill_id, prereq_id in rows:
            if skill_id in indeg and prereq_id in indeg:
                indeg[skill_id] += 1
                adj[prereq_id].append(skill_id)
        ready = sorted([i for i, d in indeg.items() if d == 0])
        out: list[Skill] = []
        while ready:
            n = ready.pop(0)
            out.append(by_id[n])
            for m in adj[n]:
                indeg[m] -= 1
                if indeg[m] == 0:
                    ready.append(m)
            ready.sort()
        # Remaining (cycle participants): append deterministically so the
        # caller still sees everything.
        if len(out) < len(skills):
            stuck = sorted(i for i, d in indeg.items() if d > 0)
            out.extend(by_id[i] for i in stuck)
        return out

    def search_skills_fts(self, search: str, limit: int = 20) -> list[Skill]:
        fts_query = build_fts5_query(search)
        if not fts_query:
            return []
        if limit < 1 or limit > 100:
            limit = 20
        with self._lock:
            rows = self._conn.execute(
                f"""SELECT s.id, s.domain, s.name, s.description, s.bloom_level,
                           s.difficulty, s.parent_skill_id, s.status, s.source,
                           s.tree_version, s.superseded_by, s.created_at,
                           s.updated_at,
                           bm25(skills_fts, 10.0, 1.0) AS score
                    FROM skills_fts
                    JOIN skills s ON s.rowid = skills_fts.rowid
                    WHERE skills_fts MATCH ?
                    ORDER BY score
                    LIMIT ?""",
                (fts_query, limit),
            ).fetchall()
        return [self._row_to_skill(r[:13]) for r in rows]

    # --- learner state ---

    def upsert_learner_state(self, st: LearnerState) -> None:
        with self._lock:
            self._conn.execute(
                """INSERT INTO learner_state
                       (skill_id, alpha, beta, p_mastery, status_enum,
                        retrievability, stability, difficulty, reps, lapses,
                        last_review, next_review)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(skill_id) DO UPDATE SET
                       alpha         = excluded.alpha,
                       beta          = excluded.beta,
                       p_mastery     = excluded.p_mastery,
                       status_enum   = excluded.status_enum,
                       retrievability= excluded.retrievability,
                       stability     = excluded.stability,
                       difficulty    = excluded.difficulty,
                       reps          = excluded.reps,
                       lapses        = excluded.lapses,
                       last_review   = excluded.last_review,
                       next_review   = excluded.next_review,
                       updated_at    = datetime('now')""",
                (
                    st.skill_id, st.alpha, st.beta, st.p_mastery, st.status_enum,
                    st.retrievability, st.stability, st.difficulty,
                    st.reps, st.lapses,
                    st.last_review, st.next_review,
                ),
            )

    def get_learner_state(self, skill_id: str) -> LearnerState | None:
        with self._lock:
            row = self._conn.execute(
                """SELECT skill_id, alpha, beta, p_mastery, status_enum,
                          retrievability, stability, difficulty, reps, lapses,
                          last_review, next_review, updated_at
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
            last_review=row[10], next_review=row[11], updated_at=row[12],
        )

    def get_all_learner_states(self) -> dict[str, LearnerState]:
        """All learner states keyed by skill_id. Single SELECT, used by
        the planning mode context injection."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT skill_id, alpha, beta, p_mastery, status_enum, "
                "retrievability, stability, difficulty, reps, lapses, "
                "last_review, next_review, updated_at FROM learner_state"
            ).fetchall()
        result: dict[str, LearnerState] = {}
        for row in rows:
            result[row[0]] = LearnerState(
                skill_id=row[0], alpha=row[1], beta=row[2],
                p_mastery=row[3], status_enum=row[4],
                retrievability=row[5], stability=row[6],
                difficulty=row[7], reps=row[8], lapses=row[9],
                last_review=row[10], next_review=row[11],
                updated_at=row[12],
            )
        return result

    # --- study plan ---

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

    def create_plan(
        self, tree_version: int, goal: str = "", session_id: str = ""
    ) -> str:
        plan_id = new_plan_id()
        with self._lock:
            self._conn.execute(
                "INSERT INTO study_plans (id, session_id, tree_version, goal) "
                "VALUES (?, ?, ?, ?)",
                (plan_id, session_id, tree_version, goal),
            )
        return plan_id

    def supersede_plan(self, plan_id: str) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE study_plans SET status = 'superseded', "
                "updated_at = datetime('now') WHERE id = ?",
                (plan_id,),
            )

    def get_active_plan(self) -> StudyPlan | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT id, session_id, tree_version, goal, status, "
                "created_at, updated_at FROM study_plans "
                "WHERE status = 'active' ORDER BY created_at DESC, rowid DESC LIMIT 1"
            ).fetchone()
        return self._row_to_plan(row) if row else None

    def add_plan_item(
        self,
        plan_id: str,
        skill_id: str,
        mode: str = "socratic",
        order_index: int = 0,
        estimated_duration_min: int | None = None,
    ) -> str:
        item_id = new_plan_item_id()
        with self._lock:
            self._conn.execute(
                "INSERT INTO study_plan_items "
                "(id, plan_id, skill_id, mode, order_index, estimated_duration_min) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (item_id, plan_id, skill_id, mode, order_index, estimated_duration_min),
            )
        return item_id

    def replace_plan_items(self, plan_id: str, items: list[StudyPlanItem]) -> None:
        """Atomic wipe + reinsert of all items for a plan."""
        with self._lock:
            self._conn.execute(
                "DELETE FROM study_plan_items WHERE plan_id = ?", (plan_id,)
            )
            self._conn.executemany(
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

    def update_plan_item(
        self,
        item_id: str,
        status: str | None = None,
        learning_session_id: str | None = None,
        actual_duration_min: int | None = None,
    ) -> None:
        """Patch one plan item. Pass None for fields you want to leave
        untouched; pass an explicit value for fields you want to update."""
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
            return  # nothing to update
        args.append(item_id)
        with self._lock:
            self._conn.execute(
                f"UPDATE study_plan_items SET {', '.join(sets)} WHERE id = ?",
                args,
            )

    def get_plan_items(self, plan_id: str) -> list[StudyPlanItem]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, plan_id, skill_id, mode, status, order_index, "
                "estimated_duration_min, actual_duration_min, learning_session_id, "
                "created_at, updated_at FROM study_plan_items "
                "WHERE plan_id = ? ORDER BY order_index, created_at",
                (plan_id,),
            ).fetchall()
        return [self._row_to_plan_item(r) for r in rows]

    def get_plan_with_items(
        self, plan_id: str
    ) -> tuple[StudyPlan | None, list[StudyPlanItem]]:
        with self._lock:
            row = self._conn.execute(
                "SELECT id, session_id, tree_version, goal, status, "
                "created_at, updated_at FROM study_plans WHERE id = ?",
                (plan_id,),
            ).fetchone()
            plan = self._row_to_plan(row) if row else None
            # Inline the items query — cannot call get_plan_items inside
            # the same lock block (threading.Lock is not reentrant).
            item_rows = self._conn.execute(
                "SELECT id, plan_id, skill_id, mode, status, order_index, "
                "estimated_duration_min, actual_duration_min, learning_session_id, "
                "created_at, updated_at FROM study_plan_items "
                "WHERE plan_id = ? ORDER BY order_index, created_at",
                (plan_id,),
            ).fetchall()
            items = [self._row_to_plan_item(r) for r in item_rows]
        return plan, items

    # --- pedagogical plans ------------------------------------------------

    def save_pedagogical_plan(self, skill_id: str, content: str) -> None:
        """Persist a stage-based teaching guide for a skill. Overwrites
        any existing plan for the same skill_id (FOR EACH row is fine —
        table has no FTS5 index, no INSERT OR REPLACE issues)."""
        with self._lock:
            self._conn.execute(
                """INSERT OR REPLACE INTO pedagogical_plans
                   (skill_id, content, updated_at)
                   VALUES (?, ?, datetime('now'))""",
                (skill_id, content),
            )

    def get_pedagogical_plan(self, skill_id: str) -> str | None:
        """Return the Markdown plan for a skill, or None if no plan exists."""
        with self._lock:
            row = self._conn.execute(
                "SELECT content FROM pedagogical_plans WHERE skill_id = ?",
                (skill_id,),
            ).fetchone()
        return row[0] if row else None

    # --- session config ---

    def save_session_config(self, cfg: SessionConfigRow) -> None:
        with self._lock:
            self._conn.execute(
                """INSERT OR REPLACE INTO session_config (session_id, provider, model, reasoning, agent_id, skill_id)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (cfg.session_id, cfg.provider, cfg.model, cfg.reasoning, cfg.agent_id, cfg.skill_id),
            )

    def load_session_config(self, session_id: str) -> SessionConfigRow | None:
        with self._lock:
            row = self._conn.execute(
                """SELECT session_id, provider, model, reasoning, agent_id, skill_id
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

    def append_message(self, session_id: str, m: MessageRow) -> None:
        # Inserts a single row at the end of the history; save_messages
        # rewrites the whole session and its transaction grows with the
        # conversation.
        with self._lock:
            self._conn.execute(
                """INSERT INTO messages (session_id, role, content, reasoning, report_id, report_title, reports)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (session_id, m.role, m.content, m.reasoning, m.report_id, m.report_title, m.reports),
            )

    def load_messages(self, session_id: str) -> list[MessageRow]:
        with self._lock:
            rows = self._conn.execute(
                """SELECT id, session_id, role, content, COALESCE(reasoning,''),
                          COALESCE(report_id,''), COALESCE(report_title,''),
                          COALESCE(reports,''), created_at
                   FROM messages WHERE session_id = ? ORDER BY id ASC""",
                (session_id,),
            ).fetchall()
        return [MessageRow(*row) for row in rows]

    def delete_messages_by_session(self, session_id: str) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))

    # --- notes ---

    def create_note(self, title: str) -> Note:
        note = Note(
            id=new_note_id(),
            title=title,
            content="",
            created_at="",
            updated_at="",
        )
        with self._lock:
            self._conn.execute(
                "INSERT INTO notes (id, title) VALUES (?, ?)",
                (note.id, note.title),
            )
            row = self._conn.execute(
                "SELECT id, title, content, created_at, updated_at FROM notes WHERE id = ?",
                (note.id,),
            ).fetchone()
        return Note(*row)

    def list_notes(self) -> list[Note]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, title, content, created_at, updated_at FROM notes ORDER BY sort_order, created_at DESC"
            ).fetchall()
        return [Note(*row) for row in rows]

    def get_note(self, note_id: str) -> Note | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT id, title, content, created_at, updated_at FROM notes WHERE id = ?",
                (note_id,),
            ).fetchone()
        return Note(*row) if row else None

    def rename_note(self, note_id: str, title: str) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE notes SET title = ?, updated_at = datetime('now') WHERE id = ?",
                (title, note_id),
            )

    def delete_note(self, note_id: str) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM notes WHERE id = ?", (note_id,))

    def save_note_content(self, note_id: str, content: str) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE notes SET content = ?, updated_at = datetime('now') WHERE id = ?",
                (content, note_id),
            )

    def reorder_notes(self, ordered_ids: list[str]) -> None:
        with self._lock:
            for i, nid in enumerate(ordered_ids):
                self._conn.execute(
                    "UPDATE notes SET sort_order = ? WHERE id = ?",
                    (float(i), nid),
                )

    # --- compat aliases for agent migration (new repo method names) ---
    # Agents now call shorter method names. These aliases let a ReportStore
    # object work as a drop-in for tests and transitional callers.
    upsert = upsert_skill
    list_active = list_skills
    search_fts = search_skills_fts
    supersede = supersede_skill
    get_active = get_active_plan
    get_items = get_plan_items
    get_with_items = get_plan_with_items
    create = create_plan
    supersede_plan_alias = supersede_plan  # noqa
    replace_items = replace_plan_items
    add_item = add_plan_item
    update_item = update_plan_item
    list_all = list_notes
    rename = rename_note
    save_content = save_note_content
    reorder = reorder_notes
    save_msgs = save_messages  # noqa
    append = append_message
    load = load_messages
    delete_by_session = delete_messages_by_session
    save_ped_plan = save_pedagogical_plan
    get_ped_plan = get_pedagogical_plan
