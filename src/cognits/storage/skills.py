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
        with self.db.transaction():
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
                   WHERE skill_id = ? AND edge_type IN ('prereq','alt_prereq')
                   UNION
                   SELECT sp.prereq_id
                   FROM skill_prerequisites sp
                   JOIN chain ON sp.skill_id = chain.id
                   WHERE sp.edge_type IN ('prereq','alt_prereq')
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
        group_id: str = "",
    ) -> None:
        if edge_type not in EDGE_TYPES:
            raise ValueError(f"invalid edge_type: {edge_type}")
        # alt_prereq requires a non-empty group_id — otherwise it's a
        # single-element OR which is semantically meaningless.
        if edge_type == "alt_prereq" and not group_id:
            raise ValueError("alt_prereq requires a non-empty group_id")
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
            # Cycle detection: both prereq and alt_prereq can form cycles.
            if edge_type in ("prereq", "alt_prereq") and self._prereq_reaches(prereq_id, skill_id):
                raise ValueError(
                    f"cycle detected: {prereq_id} already depends on {skill_id}"
                )
            self.db.conn.execute(
                """INSERT INTO skill_prerequisites
                       (skill_id, prereq_id, edge_type, proof_query, build_id, group_id)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(skill_id, prereq_id, edge_type) DO UPDATE SET
                       proof_query = excluded.proof_query,
                       build_id    = excluded.build_id,
                       group_id    = excluded.group_id""",
                (skill_id, prereq_id, edge_type, proof_query, build_id, group_id),
            )

    def get_prerequisites(self, skill_id: str) -> list[SkillPrereq]:
        with self.db.lock:
            rows = self.db.conn.execute(
                """SELECT skill_id, prereq_id, edge_type, proof_query, build_id, group_id, created_at
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
                """SELECT skill_id, prereq_id, edge_type, proof_query, build_id, group_id, created_at
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
                   WHERE edge_type IN ('prereq','alt_prereq')"""
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

    def merge_skills(self, keep_id: str, merge_ids: list[str]) -> dict:
        """Merge multiple skills into keep_id.

        Remaps prerequisite edges, moves assessment items, merges learner
        state (keeps the higher p_mastery), and deletes the merged skills.
        All operations run in a single transaction.
        """
        with self.db.transaction():
            edges_remapped = 0
            items_moved = 0
            for merge_id in merge_ids:
                if merge_id == keep_id:
                    continue

                # Re-point edges where merge_id is the prereq OR the skill.
                for col in ("prereq_id", "skill_id"):
                    cur = self.db.conn.execute(
                        f"UPDATE skill_prerequisites SET {col} = ? WHERE {col} = ?",
                        (keep_id, merge_id),
                    )
                    edges_remapped += cur.rowcount

                # Remove self-references (keep_id -> keep_id) created by re-pointing.
                self.db.conn.execute(
                    "DELETE FROM skill_prerequisites WHERE skill_id = ? AND prereq_id = ?",
                    (keep_id, keep_id),
                )

                # Deduplicate colliding edges: for each (skill_id, prereq_id, edge_type)
                # group where keep_id is involved, keep only the row with the lowest rowid.
                dup_rows = self.db.conn.execute(
                    """SELECT skill_id, prereq_id, edge_type, MIN(rowid)
                       FROM skill_prerequisites
                       WHERE skill_id = ? OR prereq_id = ?
                       GROUP BY skill_id, prereq_id, edge_type
                       HAVING COUNT(*) > 1""",
                    (keep_id, keep_id),
                ).fetchall()
                for skill, prereq, et, min_rid in dup_rows:
                    self.db.conn.execute(
                        """DELETE FROM skill_prerequisites
                           WHERE skill_id = ? AND prereq_id = ?
                             AND edge_type = ? AND rowid != ?""",
                        (skill, prereq, et, min_rid),
                    )

                # Move assessment items from merge_id to keep_id.
                cur = self.db.conn.execute(
                    "UPDATE skill_assessment_items SET skill_id = ? WHERE skill_id = ?",
                    (keep_id, merge_id),
                )
                items_moved += cur.rowcount

                # Merge learner state: keep whichever has higher p_mastery.
                kept_ls = self.db.conn.execute(
                    """SELECT p_mastery, alpha, beta, reps, lapses,
                              retrievability, stability, difficulty, status_enum,
                              last_review, next_review, scaffolding_level
                       FROM learner_state WHERE skill_id = ?""",
                    (keep_id,),
                ).fetchone()
                merge_ls = self.db.conn.execute(
                    """SELECT p_mastery, alpha, beta, reps, lapses,
                              retrievability, stability, difficulty, status_enum,
                              last_review, next_review, scaffolding_level
                       FROM learner_state WHERE skill_id = ?""",
                    (merge_id,),
                ).fetchone()
                if merge_ls and kept_ls:
                    kept_p = kept_ls[0] if kept_ls[0] is not None else 0.5
                    merge_p = merge_ls[0] if merge_ls[0] is not None else 0.5
                    if merge_p > kept_p:
                        self.db.conn.execute(
                            """UPDATE learner_state SET
                                p_mastery = ?, alpha = ?, beta = ?,
                                reps = ?, lapses = ?,
                                retrievability = ?, stability = ?, difficulty = ?,
                                status_enum = ?,
                                last_review = ?, next_review = ?,
                                scaffolding_level = ?,
                                updated_at = datetime('now')
                            WHERE skill_id = ?""",
                            (
                                merge_ls[0], merge_ls[1], merge_ls[2],
                                merge_ls[3], merge_ls[4],
                                merge_ls[5], merge_ls[6], merge_ls[7],
                                merge_ls[8],
                                merge_ls[9], merge_ls[10],
                                merge_ls[11],
                                keep_id,
                            ),
                        )

                # Delete the merged skill's learner state row.
                self.db.conn.execute(
                    "DELETE FROM learner_state WHERE skill_id = ?", (merge_id,),
                )

                # Delete the merged skill row.
                self.db.conn.execute(
                    "DELETE FROM skills WHERE id = ?", (merge_id,),
                )

        return {
            "merged": len(merge_ids),
            "edges_remapped": edges_remapped,
            "items_moved": items_moved,
            "kept": keep_id,
        }

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
