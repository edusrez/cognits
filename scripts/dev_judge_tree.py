#!/usr/bin/env python3
"""Judge a skill tree's quality — structured, machine-parseable audit.

Usage::

    uv run python scripts/dev_judge_tree.py \
        --data-dir /mnt/c/users/eduar/Documents/Proyectos/godot/.cognits \
        --objective "2D roguelike in Godot 4"

Opens the DB read-only, runs a full audit, and prints a structured verdict.

Not packaged in the wheel — this is dev tooling.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

# Ensure the repo root is on sys.path.
_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Audit a skill tree DB.")
    p.add_argument(
        "--data-dir",
        required=True,
        help="Path to the .cognits directory containing cognits.db.",
    )
    p.add_argument(
        "--objective",
        default="",
        help="Optional learning objective for goal-relevance heuristics.",
    )
    return p.parse_args(argv)


# ---------------------------------------------------------------------------
# Cycle detection (Kahn's algorithm)
# ---------------------------------------------------------------------------


def _check_acyclic(edges: list[tuple[str, str]]) -> tuple[bool, list[str]]:
    """Return (True, []) if acyclic, else (False, cycle_nodes)."""
    in_degree: dict[str, int] = defaultdict(int)
    out_edges: dict[str, list[str]] = defaultdict(list)
    nodes: set[str] = set()

    for src, dst in edges:
        nodes.add(src)
        nodes.add(dst)
        out_edges[src].append(dst)
        in_degree[dst] += 1
        in_degree.setdefault(src, 0)

    queue = [n for n in nodes if in_degree[n] == 0]
    sorted_nodes: list[str] = []
    while queue:
        n = queue.pop(0)
        sorted_nodes.append(n)
        for child in out_edges.get(n, []):
            in_degree[child] -= 1
            if in_degree[child] == 0:
                queue.append(child)

    if len(sorted_nodes) == len(nodes):
        return True, []

    # Find a cycle
    remaining = nodes - set(sorted_nodes)
    cycle_start = next(iter(remaining)) if remaining else "?"
    return False, [cycle_start]


# ---------------------------------------------------------------------------
# Goal skill detection
# ---------------------------------------------------------------------------


def _pick_goal_skill(candidate_ids: set[str], conn) -> str | None:
    """Pick the best goal skill from candidates (skills that have prereqs but
    nothing depends on them).

    Priority:
    1. A skill with domain ``__goal__`` (explicit goal marker).
    2. A skill whose name appears in the most recent build's summary.
    3. If still ambiguous, return None (goal not identifiable — caller NOTES).
    """
    if not candidate_ids:
        return None
    if len(candidate_ids) == 1:
        return next(iter(candidate_ids))

    # 1. Prefer __goal__ domain (the planner creates this for the top goal)
    for cid in candidate_ids:
        row = conn.execute(
            "SELECT domain FROM skills WHERE id=?", (cid,)
        ).fetchone()
        if row and row[0] == "__goal__":
            return cid

    # 2. Try name-match against the most recent build's summary
    build_row = conn.execute(
        "SELECT summary FROM skill_builds ORDER BY started_at DESC LIMIT 1"
    ).fetchone()
    if build_row and build_row[0]:
        summary_lower = build_row[0].lower()
        for cid in candidate_ids:
            name_row = conn.execute(
                "SELECT name FROM skills WHERE id=?", (cid,)
            ).fetchone()
            if name_row and name_row[0]:
                name_lower = name_row[0].lower()
                if name_lower in summary_lower:
                    return cid
                # Also check if summary words match the name
                for word in summary_lower.split():
                    if len(word) > 3 and word in name_lower:
                        return cid

    # 3. Also check targets domain_type from most recent build
    targets_row = conn.execute(
        "SELECT targets FROM skill_builds "
        "WHERE targets != '' ORDER BY started_at DESC LIMIT 1"
    ).fetchone()
    if targets_row and targets_row[0]:
        try:
            targets = json.loads(targets_row[0])
            domain_type = targets.get("domain_type", "")
            if domain_type:
                dt_lower = domain_type.lower()
                for cid in candidate_ids:
                    name_row = conn.execute(
                        "SELECT name FROM skills WHERE id=?", (cid,)
                    ).fetchone()
                    if name_row and name_row[0]:
                        if dt_lower in name_row[0].lower():
                            return cid
        except (json.JSONDecodeError, TypeError):
            pass

    # Ambiguous — caller will NOTE
    return None


# ---------------------------------------------------------------------------
# Main audit
# ---------------------------------------------------------------------------


def _audit(db_path: Path, objective: str = "") -> int:
    uri = f"file:{db_path}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    try:
        conn.execute("PRAGMA read_uncommitted = false")

        issues: list[str] = []
        warn: list[str] = []
        passed: list[str] = []

        def _flag(msg: str, criteria: str) -> None:
            issues.append(f"FAIL [{criteria}] {msg}")

        def _warn(msg: str, criteria: str) -> None:
            warn.append(f"WARN [{criteria}] {msg}")

        def _ok(msg: str, criteria: str) -> None:
            passed.append(f"OK   [{criteria}] {msg}")

        # ---------------------------------------------------------------
        # Counts
        # ---------------------------------------------------------------
        skills_n = conn.execute("SELECT COUNT(*) FROM skills").fetchone()[0]
        edges_n = conn.execute(
            "SELECT COUNT(*) FROM skill_prerequisites WHERE skill_id IS NOT NULL"
        ).fetchone()[0]
        items_n = conn.execute(
            "SELECT COUNT(*) FROM skill_assessment_items"
        ).fetchone()[0]
        domains_rows = conn.execute(
            "SELECT DISTINCT domain FROM skills ORDER BY domain"
        ).fetchall()
        domains_n = len(domains_rows)
        domains_list = [r[0] for r in domains_rows]
        learner_n = conn.execute(
            "SELECT COUNT(*) FROM learner_state"
        ).fetchone()[0]
        reports_n = conn.execute("SELECT COUNT(*) FROM reports").fetchone()[0]
        chunks_n = conn.execute("SELECT COUNT(*) FROM report_chunks").fetchone()[0]
        pedagogical_n = conn.execute(
            "SELECT COUNT(*) FROM pedagogical_plans"
        ).fetchone()[0]
        study_plans_n = conn.execute(
            "SELECT COUNT(*) FROM study_plans"
        ).fetchone()[0]

        print("=" * 65)
        print(" SKILL TREE AUDIT")
        print("=" * 65)
        print(f"\nDB: {db_path}")
        print(f"Objective: {objective or '(not provided)'}")
        print(f"\n--- Counts ---")
        print(f"Skills:           {skills_n}")
        print(f"Edges:            {edges_n}")
        print(f"Assessment items: {items_n}")
        print(f"Domains:          {domains_n}  ({', '.join(domains_list)})")
        print(f"Learner states:   {learner_n}")
        print(f"Reports:          {reports_n}")
        print(f"Report chunks:    {chunks_n}")
        print(f"Pedagogical plans:{pedagogical_n}")
        print(f"Study plans:      {study_plans_n}")

        # ---------------------------------------------------------------
        # Build targets (adaptive)
        # ---------------------------------------------------------------
        bloom_targets: dict | None = None
        targets_data: dict | None = None
        try:
            row = conn.execute(
                "SELECT targets FROM skill_builds WHERE targets IS NOT NULL AND targets != '' "
                "ORDER BY started_at DESC LIMIT 1"
            ).fetchone()
            if row and row[0]:
                targets_data = json.loads(row[0])
                bloom_targets = targets_data.get("bloom_targets")
        except (sqlite3.OperationalError, json.JSONDecodeError):
            pass

        if targets_data:
            print(f"\n--- Targets (build parameters) ---")
            print(f"  domain_type: {targets_data.get('domain_type', '?')}")
            sz = targets_data.get("size_range", "?")
            print(f"  size_range: {sz}")
            md = targets_data.get("max_depth", "?")
            print(f"  max_depth: {md}")
            ac = targets_data.get("atomicity_criterion", "?")
            if isinstance(ac, str) and len(ac) > 80:
                ac = ac[:80] + "..."
            print(f"  atomicity: {ac}")
            if bloom_targets:
                print(f"  bloom_targets:")
                for lv, (lo, hi) in sorted(bloom_targets.items()):
                    print(f"    {lv}: [{lo}, {hi}]")

        # ---------------------------------------------------------------
        # Domains breakdown
        # ---------------------------------------------------------------
        domain_counts = conn.execute(
            "SELECT domain, COUNT(*) FROM skills GROUP BY domain ORDER BY COUNT(*) DESC"
        ).fetchall()
        print(f"\n--- Domains breakdown ---")
        for d, c in domain_counts:
            pct = (c / skills_n * 100) if skills_n else 0
            print(f"  {d}: {c} ({pct:.1f}%)")

        # ---------------------------------------------------------------
        # Bloom distribution
        # ---------------------------------------------------------------
        bloom_counts = conn.execute(
            "SELECT bloom_level, COUNT(*) FROM skills "
            "GROUP BY bloom_level ORDER BY COUNT(*) DESC"
        ).fetchall()
        print(f"\n--- Bloom distribution ---")
        bloom_lookup: dict[str, int] = {}
        for lv, c in bloom_counts:
            pct = (c / skills_n * 100) if skills_n else 0
            print(f"  {lv}: {c} ({pct:.1f}%)")
            bloom_lookup[lv] = c

        # Build bloom verdict rows (used in verdict table below)
        bloom_verdicts: list[tuple[str, str, str]] = []

        if bloom_targets:
            # Adaptive per-level check against proposed targets
            for lv, (lo, hi) in sorted(bloom_targets.items()):
                c = bloom_lookup.get(lv, 0)
                pct = (c / skills_n * 100) if skills_n else 0
                in_range = lo <= pct <= hi
                label = f"Bloom '{lv}' target [{lo},{hi}]"
                actual = f"{pct:.1f}% {'in' if in_range else '∉'} [{lo}, {hi}]"
                result = "PASS" if in_range else "FAIL"
                if in_range:
                    _ok(f"Bloom '{lv}' at {pct:.1f}% in [{lo}, {hi}]", f"bloom_{lv}")
                else:
                    _flag(
                        f"Bloom '{lv}' at {pct:.1f}% outside range [{lo}, {hi}]",
                        f"bloom_{lv}",
                    )
                bloom_verdicts.append((label, actual, result))
        else:
            # Legacy hardcoded check (backward compat)
            apply_n = 0
            for lv in bloom_lookup:
                if "apply" in lv.lower() or "aplicar" in lv.lower():
                    apply_n = bloom_lookup[lv]
                    break
            apply_pct = (apply_n / skills_n * 100) if skills_n else 0
            if apply_pct > 35:
                _flag(
                    f"Bloom 'apply/create' levels at {apply_pct:.1f}% (> 35% target)",
                    "bloom_apply_gt_35",
                )
            else:
                _ok(
                    f"Bloom 'apply/create' levels at {apply_pct:.1f}% (≤ 35%)",
                    "bloom_apply_gt_35",
                )
            bloom_verdicts.append((
                "Bloom apply ≤ 35%",
                f"{apply_pct:.1f}%",
                "PASS" if apply_pct <= 35 else "FAIL",
            ))

        # ---------------------------------------------------------------
        # Edge types + proof_query coverage
        # ---------------------------------------------------------------
        edge_types = conn.execute(
            "SELECT edge_type, COUNT(*) FROM skill_prerequisites "
            "WHERE skill_id IS NOT NULL GROUP BY edge_type"
        ).fetchall()
        proof_nonempty = conn.execute(
            "SELECT COUNT(*) FROM skill_prerequisites "
            "WHERE proof_query IS NOT NULL AND proof_query != ''"
        ).fetchone()[0]
        proof_pct = (proof_nonempty / edges_n * 100) if edges_n else 0
        print(f"\n--- Edges ---")
        for et, c in edge_types:
            print(f"  {et}: {c}")
        print(f"  proof_query non-empty: {proof_nonempty}/{edges_n} ({proof_pct:.1f}%)")
        if proof_pct < 100:
            _flag(
                f"Only {proof_pct:.1f}% of edges have proof_query (target: 100%)",
                "proof_query_coverage",
            )
        else:
            _ok("All edges have proof_query", "proof_query_coverage")

        # ---------------------------------------------------------------
        # Assessment items distribution
        # ---------------------------------------------------------------
        item_dist = conn.execute(
            "SELECT s.id, COUNT(a.rowid) as cnt FROM skills s "
            "LEFT JOIN skill_assessment_items a ON a.skill_id = s.id "
            "GROUP BY s.id"
        ).fetchall()
        # Count items per skill
        per_skill = Counter(c for _, c in item_dist)
        zero_items = per_skill.get(0, 0)
        one_item = per_skill.get(1, 0)
        two_items = per_skill.get(2, 0)
        three_plus = sum(v for k, v in per_skill.items() if k >= 3)
        print(f"\n--- Assessment items per skill ---")
        print(f"  0 items: {zero_items}")
        print(f"  1 item:  {one_item}")
        print(f"  2 items: {two_items}")
        print(f"  3+ items:{three_plus}")
        if zero_items > 0:
            _flag(
                f"{zero_items} skill(s) have 0 assessment items",
                "zero_items_skills",
            )
        else:
            _ok("All skills have ≥ 1 assessment item", "zero_items_skills")

        # ---------------------------------------------------------------
        # Mastery seeding
        # ---------------------------------------------------------------
        seeded = conn.execute(
            "SELECT skill_id, p_mastery FROM learner_state WHERE p_mastery IS NOT NULL"
        ).fetchall()
        print(f"\n--- Mastery seeding ---")
        print(f"  Seeded skills: {len(seeded)}")
        frontier_ok = any(pm for _, pm in seeded if pm is not None and pm >= 0.75)
        if not frontier_ok:
            _flag(
                "No seeded skill has p_mastery ≥ 0.75 (learner will see no frontier)",
                "mastery_frontier",
            )
        else:
            high_seeds = [
                (sid, pm)
                for sid, pm in seeded
                if pm is not None and pm >= 0.75
            ]
            print(f"  Skills with p_mastery ≥ 0.75: {len(high_seeds)}")
            for sid, pm in high_seeds[:10]:
                name_row = conn.execute(
                    "SELECT name FROM skills WHERE id=?", (sid,)
                ).fetchone()
                name = name_row[0] if name_row else "?"
                print(f"    {sid}: {name} (p={pm:.3f})")
            _ok(
                f"Frontier present: {len(high_seeds)} skill(s) at ≥ 0.75",
                "mastery_frontier",
            )

        # ---------------------------------------------------------------
        # Difficulty range
        # ---------------------------------------------------------------
        diff_stats = conn.execute(
            "SELECT MIN(difficulty), MAX(difficulty), AVG(difficulty) FROM skills"
        ).fetchone()
        print(f"\n--- Difficulty ---")
        if diff_stats and all(v is not None for v in diff_stats):
            dmin, dmax, davg = diff_stats
            print(f"  Min: {dmin:.2f}  Max: {dmax:.2f}  Avg: {davg:.2f}")
        else:
            print("  (no skills with difficulty set)")

        # ---------------------------------------------------------------
        # Connectivity
        # ---------------------------------------------------------------
        # Compute roots: skills with no prereq
        has_prereq = set(
            r[0] for r in conn.execute(
                "SELECT DISTINCT skill_id FROM skill_prerequisites WHERE skill_id IS NOT NULL"
            ).fetchall()
        )
        all_skills = set(
            r[0] for r in conn.execute("SELECT id FROM skills").fetchall()
        )
        roots = all_skills - has_prereq
        root_pct = (len(roots) / skills_n * 100) if skills_n else 0
        ratio = edges_n / skills_n if skills_n else 0
        print(f"\n--- Connectivity ---")
        print(f"  Edges/skill ratio: {ratio:.2f} (target ≥0.8, no hard upper limit per SOTA)")
        print(f"  Roots: {len(roots)}/{skills_n} ({root_pct:.1f}%)")
        if ratio < 0.8:
            _warn(
                f"Edges/skill ratio {ratio:.2f} below 0.8 (very sparse tree)",
                "edges_ratio",
            )
        else:
            _ok(f"Edges/skill ratio {ratio:.2f} ≥ 0.8", "edges_ratio")

        print(f"  Roots (floor breadth): {len(roots)}/{skills_n} ({root_pct:.1f}%) \u2014 "
              f"roots = learner's floor; broad floor = many roots, correct for top-down goal-directed generation")

        # Orphans: skills with no prereq AND no dependents
        is_prereq_for = set(
            r[0] for r in conn.execute(
                "SELECT DISTINCT prereq_id FROM skill_prerequisites WHERE skill_id IS NOT NULL"
            ).fetchall()
        )
        orphans = [s for s in roots if s not in is_prereq_for]
        orphan_pct = (len(orphans) / skills_n * 100) if skills_n else 0
        print(f"  Orphans (no prereq + no dependent): {len(orphans)} ({orphan_pct:.1f}%)")
        if len(orphans) > 0:
            _flag(
                f"{len(orphans)} orphan skill(s) — disconnected from the tree",
                "orphans",
            )
        else:
            _ok("No orphans", "orphans")

        # ---------------------------------------------------------------
        # Top hubs
        # ---------------------------------------------------------------
        hubs = conn.execute(
            "SELECT prereq_id, COUNT(*) as cnt FROM skill_prerequisites "
            "WHERE skill_id IS NOT NULL "
            "GROUP BY prereq_id ORDER BY cnt DESC LIMIT 10"
        ).fetchall()
        print(f"\n--- Top hubs (most dependents) ---")
        for pid, cnt in hubs:
            name_row = conn.execute(
                "SELECT name FROM skills WHERE id=?", (pid,)
            ).fetchone()
            name = name_row[0] if name_row else "?"
            print(f"  {pid}: {name} ({cnt} dependents)")

        # ---------------------------------------------------------------
        # Cycle check
        # ---------------------------------------------------------------
        edge_pairs = [
            (r[0], r[1])
            for r in conn.execute(
                "SELECT skill_id, prereq_id FROM skill_prerequisites WHERE skill_id IS NOT NULL"
            ).fetchall()
        ]
        acyclic, cycle_nodes = _check_acyclic(edge_pairs)
        print(f"\n--- Cycle check ---")
        if acyclic:
            print("  ACYCLIC ✓")
            _ok("Acyclic — no cycles detected", "cycles")
        else:
            print(f"  CYCLE: {cycle_nodes}")
            _flag(f"Cycle detected involving: {cycle_nodes}", "cycles")

        # ---------------------------------------------------------------
        # SOTA quality checks (bottleneck, bloom coverage, goal relevance,
        # transitive redundancy, naming specificity)
        # ---------------------------------------------------------------

        # ── Bottleneck detection ──
        bottleneck_rows = conn.execute(
            "SELECT prereq_id, COUNT(*) as cnt FROM skill_prerequisites "
            "WHERE skill_id IS NOT NULL AND edge_type IN ('prereq','alt_prereq') "
            "GROUP BY prereq_id HAVING cnt > 8"
        ).fetchall()
        bottleneck_names: list[str] = []
        for pid, cnt in bottleneck_rows:
            name_row = conn.execute(
                "SELECT name FROM skills WHERE id=?", (pid,)
            ).fetchone()
            name = name_row[0] if name_row else "?"
            bottleneck_names.append(f"'{name}' ({cnt} incoming)")
        has_bottleneck = len(bottleneck_names) > 0
        print(f"\n--- Bottleneck check ---")
        if has_bottleneck:
            print(f"  BOTTLENECK: {', '.join(bottleneck_names)}")
            _warn(f"Bottleneck skills: {', '.join(bottleneck_names)}", "bottleneck")
        else:
            print("  No bottlenecks (all ≤ 8 incoming)")
            _ok("No bottleneck skills (>8 incoming prereqs)", "bottleneck")

        # ── Bloom coverage ──
        # Reuse bloom_lookup from earlier Bloom distribution section.
        bloom_levels_present = sum(1 for n in bloom_lookup.values() if n > 0)
        bloom_ok = bloom_levels_present >= 4
        print(f"\n--- Bloom coverage ---")
        print(f"  {bloom_levels_present}/6 Bloom levels represented")
        if bloom_ok:
            _ok(f"{bloom_levels_present}/6 Bloom levels represented", "bloom_coverage")
        else:
            _warn(
                f"Only {bloom_levels_present}/6 Bloom levels represented (diversity low)",
                "bloom_coverage",
            )

        # ── Goal relevance ──
        goal_candidate_ids = set(
            r[0] for r in conn.execute(
                "SELECT id FROM skills "
                "WHERE id NOT IN (SELECT DISTINCT prereq_id FROM skill_prerequisites "
                "WHERE skill_id IS NOT NULL AND edge_type IN ('prereq','alt_prereq')) "
                "AND id IN (SELECT DISTINCT skill_id FROM skill_prerequisites "
                "WHERE skill_id IS NOT NULL AND edge_type IN ('prereq','alt_prereq'))"
            ).fetchall()
        )
        goal_skill_id = _pick_goal_skill(goal_candidate_ids, conn)
        goal_reachable_count = 0
        goal_relevance_pct = 0.0
        if goal_skill_id is not None:
            fwd_adj: dict[str, list[str]] = {}
            for r in conn.execute(
                "SELECT skill_id, prereq_id FROM skill_prerequisites "
                "WHERE skill_id IS NOT NULL AND edge_type IN ('prereq','alt_prereq')"
            ).fetchall():
                fwd_adj.setdefault(r[0], []).append(r[1])
            visited = set()
            queue = [goal_skill_id]
            visited.add(goal_skill_id)
            while queue:
                node = queue.pop(0)
                for prereq in fwd_adj.get(node, []):
                    if prereq not in visited:
                        visited.add(prereq)
                        queue.append(prereq)
            goal_reachable_count = len(visited)
            goal_relevance_pct = (goal_reachable_count / skills_n * 100) if skills_n else 0
        print(f"\n--- Goal relevance ---")
        if goal_skill_id is None:
            print("  No goal skill — cannot compute (organic model: goal may be external)")
            _warn("No goal skill resolved — cannot compute relevance (organic model: goal may be external)", "goal_relevance")
        else:
            print(f"  {goal_relevance_pct:.1f}% ({goal_reachable_count}/{skills_n}) skills on goal path")
            if goal_relevance_pct < 20:
                _flag(
                    f"Only {goal_relevance_pct:.1f}% of skills on goal path",
                    "goal_relevance",
                )
            elif goal_relevance_pct < 40:
                _warn(
                    f"Only {goal_relevance_pct:.1f}% of skills on goal path",
                    "goal_relevance",
                )
            else:
                _ok(
                    f"{goal_relevance_pct:.1f}% of skills on goal path",
                    "goal_relevance",
                )

        # ── Transitive redundancy ──
        trans_adj: dict[str, set[str]] = {}
        all_edges: list[tuple[str, str]] = []
        for r in conn.execute(
            "SELECT skill_id, prereq_id FROM skill_prerequisites "
            "WHERE skill_id IS NOT NULL AND edge_type IN ('prereq','alt_prereq')"
        ).fetchall():
            sid, pid = r[0], r[1]
            trans_adj.setdefault(sid, set()).add(pid)
            all_edges.append((sid, pid))
        redundant_count = 0
        for sid, pid in all_edges:
            other_prereqs = trans_adj.get(sid, set()) - {pid}
            found = False
            for k in other_prereqs:
                visited_bfs: set[str] = set()
                queue_bfs = [k]
                visited_bfs.add(k)
                while queue_bfs and not found:
                    node = queue_bfs.pop(0)
                    if node == pid:
                        found = True
                        break
                    for neighbor in trans_adj.get(node, set()):
                        if neighbor not in visited_bfs:
                            visited_bfs.add(neighbor)
                            queue_bfs.append(neighbor)
                if found:
                    break
            if found:
                redundant_count += 1
        redundant_pct = (redundant_count / len(all_edges) * 100) if all_edges else 0
        print(f"\n--- Transitive redundancy ---")
        print(f"  {redundant_pct:.1f}% redundant edges ({redundant_count}/{edges_n})")
        if redundant_pct > 10:
            _warn(
                f"{redundant_pct:.1f}% redundant edges (>10%)",
                "transitive_redundancy",
            )
        else:
            _ok(
                f"{redundant_pct:.1f}% redundant edges (≤10%)",
                "transitive_redundancy",
            )

        # ── Naming specificity ──
        generic_count = 0
        for r in conn.execute("SELECT name FROM skills").fetchall():
            if len(r[0].split()) <= 2:
                generic_count += 1
        generic_name_pct = (generic_count / skills_n * 100) if skills_n else 0
        print(f"\n--- Naming specificity ---")
        print(f"  {generic_name_pct:.1f}% skills with ≤2-word names ({generic_count}/{skills_n})")
        if generic_name_pct > 20:
            _warn(
                f"{generic_name_pct:.1f}% of skill names are too generic (≤2 words)",
                "naming_specificity",
            )
        else:
            _ok(
                f"{generic_name_pct:.1f}% generic names (≤20%)",
                "naming_specificity",
            )

        # ---------------------------------------------------------------
        # Reports
        # ---------------------------------------------------------------
        reports = conn.execute(
            "SELECT id, title, LENGTH(content), sources FROM reports ORDER BY created_at"
        ).fetchall()
        print(f"\n--- Reports ({len(reports)}) ---")
        sources_empty = 0
        for rid, title, clen, sources_raw in reports:
            sources_val = sources_raw or ""
            short_title = (title or "")[:80]
            has_sources = (
                sources_val.strip() not in ("", "[]", "null", '""')
            )
            if not has_sources:
                sources_empty += 1
            print(f"  {rid}: {short_title} ({clen} chars, sources={'yes' if has_sources else 'no'})")

        if sources_empty > 0 and reports:
            _warn(
                f"{sources_empty}/{len(reports)} reports have empty sources",
                "report_sources",
            )
        else:
            _ok("All reports have non-empty sources", "report_sources")

        # ---------------------------------------------------------------
        # Report chunks
        # ---------------------------------------------------------------
        print(f"\n--- Report chunks ---")
        print(f"  Total: {chunks_n}")
        if chunks_n == 0:
            note = (
                "Expected if generated via dev_run_skill_planner with RAG "
                "disabled; run `cognits` to backfill-index."
            )
            print(f"  NOTE: {note}")
            _warn(note, "report_chunks_zero")
        else:
            _ok(f"{chunks_n} chunks indexed", "report_chunks_zero")

        # ---------------------------------------------------------------
        # Skill builds
        # ---------------------------------------------------------------
        builds = conn.execute(
            "SELECT id, trigger, status, summary, skill_count, added, modified, superseded "
            "FROM skill_builds ORDER BY started_at"
        ).fetchall()
        print(f"\n--- Skill builds ({len(builds)}) ---")
        for b in builds:
            sid, trigger, status, summary, sc, add, mod, sup = b
            summary_short = (summary or "")[:120]
            print(f"  {sid}: [{status}] trigger={trigger} "
                  f"skills={sc} +{add} ~{mod} -{sup}")
            if summary_short:
                print(f"    summary: {summary_short}")

        # ---------------------------------------------------------------
        # Verdict table
        # ---------------------------------------------------------------
        print(f"\n{'=' * 65}")
        print(" VERDICT TABLE")
        print(f"{'=' * 65}")

        # Skills count is organic — displayed as informational NOTE only.
        print(f"\n  NOTE  | Skills count          | {skills_n}")

        verdicts = [
            ("Edges count",
             "≥ 10" if edges_n >= 10 else f"FAIL: only {edges_n}",
             "PASS" if edges_n >= 10 else "FAIL"),
            ("Assessment items",
             f"0 zero-item skills" if zero_items == 0 else f"FAIL: {zero_items} skills with 0 items",
             "PASS" if zero_items == 0 else "FAIL"),
            *bloom_verdicts,
            ("Proof query coverage",
             f"{proof_pct:.1f}%",
             "PASS" if proof_pct >= 100 else "FAIL"),
            ("Mastery frontier ≥ 0.75",
             "present" if frontier_ok else "FAIL: no high-mastery seed",
             "PASS" if frontier_ok else "FAIL"),
            ("Edges/skill ratio",
             f"{ratio:.2f}",
             "PASS" if ratio >= 0.8 else "WARN"),
            ("Roots (floor breadth)",
             f"{len(roots)} ({root_pct:.1f}%)",
             "NOTE"),
            ("Orphans",
             f"{len(orphans)}" if len(orphans) > 0 else "none",
             "PASS" if len(orphans) == 0 else "FAIL"),
            ("Acyclic",
             "acyclic" if acyclic else "CYCLE",
             "PASS" if acyclic else "FAIL"),
            ("Bottleneck (>8 incoming)",
             "found" if has_bottleneck else "none",
             "WARN" if has_bottleneck else "PASS"),
            ("Bloom coverage (≥4/6)",
             f"{bloom_levels_present}/6",
             "PASS" if bloom_ok else "WARN"),
            ("Goal relevance",
             f"{goal_relevance_pct:.1f}%" if goal_skill_id else "N/A",
             "FAIL" if goal_skill_id and goal_relevance_pct < 20 else ("WARN" if goal_skill_id and goal_relevance_pct < 40 else ("PASS" if goal_skill_id else "NOTE"))),
            ("Transitive redundancy",
             f"{redundant_pct:.1f}%",
             "WARN" if redundant_pct > 10 else "PASS"),
            ("Naming specificity",
             f"{generic_name_pct:.1f}% generic",
             "WARN" if generic_name_pct > 20 else "PASS"),
            ("Report chunks",
             f"{chunks_n}",
             "PASS" if chunks_n > 0 else "WARN"),
            ("Report sources",
             f"{sources_empty}/{len(reports)} empty",
             "PASS" if sources_empty == 0 else "WARN"),
        ]

        for name, actual, result in verdicts:
            print(f"  {result:5s} | {name:<22s} | {actual}")

        # ---------------------------------------------------------------
        # Overall verdict
        # ---------------------------------------------------------------
        fail_count = sum(1 for _, _, r in verdicts if r == "FAIL")
        warn_count = sum(1 for _, _, r in verdicts if r == "WARN")

        print(f"\n{'=' * 65}")
        print(" OVERALL VERDICT")
        print(f"{'=' * 65}")
        if fail_count == 0 and warn_count == 0:
            print("  ★ SOTA — tree meets all quality criteria")
        elif fail_count == 0:
            print("  ✓ ACCEPTABLE — minor warnings, ready for use")
        else:
            print(f"  ✗ NEEDS ITERATION — {fail_count} failures, {warn_count} warnings")

        if fail_count > 0:
            print(f"\n  Top issues:")
            for i, issue in enumerate(issues[:3]):
                print(f"  {i+1}. {issue}")

        print(f"\n  Summary: {len(passed)} passed, {len(warn)} warnings, "
              f"{len(issues)} failures")

        return 1 if fail_count > 0 else 0

    finally:
        conn.close()


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    data_dir = Path(args.data_dir)
    db_path = data_dir / "cognits.db"

    legacy_path = data_dir / "learnit.db"
    if not db_path.exists() and legacy_path.exists():
        db_path = legacy_path

    if not db_path.exists():
        print(f"[FATAL] No DB found at {data_dir} (tried cognits.db and learnit.db)")
        return 2

    return _audit(db_path, args.objective)


if __name__ == "__main__":
    sys.exit(main())
