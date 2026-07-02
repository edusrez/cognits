"""Skill repository — skill tree, prerequisites, builds, FTS5 search."""

from __future__ import annotations

from cognits.storage.database import Database
from cognits.storage.models import (
    EDGE_TYPES,
    Skill,
    SkillBuild,
    SkillPrereq,
    build_fts5_query,
    new_build_id,
    new_skill_id,
)


class SkillRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

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
        with self.db.lock:
            self.db.conn.execute(
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
        with self.db.lock:
            self.db.conn.execute(
                f"UPDATE skill_builds SET {', '.join(sets)} WHERE id = ?",
                args,
            )

    def upsert(self, s: Skill) -> None:
        with self.db.lock:
            self.db.conn.execute(
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
            self.db.conn.execute(
                """INSERT INTO learner_state (skill_id) VALUES (?)
                   ON CONFLICT(skill_id) DO NOTHING""",
                (s.id,),
            )

    def get(self, skill_id: str) -> Skill | None:
        with self.db.lock:
            row = self.db.conn.execute(
                """SELECT id, domain, name, description, bloom_level, difficulty,
                          parent_skill_id, status, source, tree_version, superseded_by,
                          created_at, updated_at
                   FROM skills WHERE id = ?""",
                (skill_id,),
            ).fetchone()
        return self._row_to_skill(row) if row else None

    def list_active(self, domain: str | None = None) -> list[Skill]:
        sql = """SELECT id, domain, name, description, bloom_level, difficulty,
                        parent_skill_id, status, source, tree_version, superseded_by,
                        created_at, updated_at
                 FROM skills WHERE status = 'active'"""
        args: list = []
        if domain:
            sql += " AND domain = ?"
            args.append(domain)
        sql += " ORDER BY domain, name"
        with self.db.lock:
            rows = self.db.conn.execute(sql, args).fetchall()
        return [self._row_to_skill(r) for r in rows]

    def supersede(self, skill_id: str, new_skill_id: str) -> None:
        with self.db.lock:
            self.db.conn.execute(
                """UPDATE skills
                   SET status = 'superseded',
                       superseded_by = ?,
                       updated_at = datetime('now')
                   WHERE id = ?""",
                (new_skill_id, skill_id),
            )

    def bump_tree_version(self) -> int:
        with self.db.lock:
            self.db.conn.execute(
                "UPDATE skills SET tree_version = tree_version + 1, "
                "updated_at = datetime('now') WHERE status = 'active'"
            )
            row = self.db.conn.execute(
                "SELECT MAX(tree_version) FROM skills WHERE status = 'active'"
            ).fetchone()
            return row[0] if row else 1

    def get_tree_version(self) -> int:
        with self.db.lock:
            row = self.db.conn.execute(
                "SELECT MAX(tree_version) FROM skills WHERE status = 'active'"
            ).fetchone()
        return row[0] if row and row[0] is not None else 1

    def _prereq_reaches(self, start_id: str, target_id: str) -> bool:
        rows = self.db.conn.execute(
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
        with self.db.lock:
            missing = []
            for sid in (skill_id, prereq_id):
                row = self.db.conn.execute(
                    "SELECT 1 FROM skills WHERE id = ?", (sid,)
                ).fetchone()
                if not row:
                    missing.append(sid)
            if missing:
                raise ValueError(
                    "skill not found: " + ", ".join(missing)
                    + ". Use the exact skill_id returned by upsert."
                )
            if edge_type == "prereq" and self._prereq_reaches(prereq_id, skill_id):
                raise ValueError(
                    f"cycle detected: {prereq_id} already depends on {skill_id}"
                )
            self.db.conn.execute(
                """INSERT INTO skill_prerequisites
                       (skill_id, prereq_id, edge_type, proof_query, build_id)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(skill_id, prereq_id, edge_type) DO UPDATE SET
                       proof_query = excluded.proof_query,
                       build_id    = excluded.build_id""",
                (skill_id, prereq_id, edge_type, proof_query, build_id),
            )

    def get_prerequisites(self, skill_id: str) -> list[SkillPrereq]:
        with self.db.lock:
            rows = self.db.conn.execute(
                """SELECT skill_id, prereq_id, edge_type, proof_query, build_id, created_at
                   FROM skill_prerequisites WHERE skill_id = ?""",
                (skill_id,),
            ).fetchall()
        return [SkillPrereq(*r) for r in rows]

    def get_tree(self) -> dict:
        with self.db.lock:
            skill_rows = self.db.conn.execute(
                """SELECT id, domain, name, description, bloom_level, difficulty,
                          parent_skill_id, status, source, tree_version, superseded_by,
                          created_at, updated_at
                   FROM skills WHERE status = 'active'
                   ORDER BY domain, name"""
            ).fetchall()
            edge_rows = self.db.conn.execute(
                """SELECT skill_id, prereq_id, edge_type, proof_query, build_id, created_at
                   FROM skill_prerequisites
                   ORDER BY skill_id, edge_type"""
            ).fetchall()
            tv_row = self.db.conn.execute(
                "SELECT MAX(tree_version) FROM skills WHERE status = 'active'"
            ).fetchone()
        return {
            "skills": [self._row_to_skill(r).to_json() for r in skill_rows],
            "edges": [SkillPrereq(*r).to_json() for r in edge_rows],
            "treeVersion": tv_row[0] if tv_row and tv_row[0] is not None else 1,
        }

    def walk_topological(self) -> list[Skill]:
        skills = self.list_active()
        by_id = {s.id: s for s in skills}
        indeg: dict[str, int] = {s.id: 0 for s in skills}
        adj: dict[str, list[str]] = {s.id: [] for s in skills}
        with self.db.lock:
            rows = self.db.conn.execute(
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
        if len(out) < len(skills):
            stuck = sorted(i for i, d in indeg.items() if d > 0)
            out.extend(by_id[i] for i in stuck)
        return out

    def search_fts(self, search: str, limit: int = 20) -> list[Skill]:
        fts_query = build_fts5_query(search)
        if not fts_query:
            return []
        if limit < 1 or limit > 100:
            limit = 20
        with self.db.lock:
            rows = self.db.conn.execute(
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
