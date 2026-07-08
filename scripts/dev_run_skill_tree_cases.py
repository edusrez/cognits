#!/usr/bin/env python3
"""Generate 3 skill trees for the SAME goal with 3 DIFFERENT learner floors.

Usage::

    uv run python scripts/dev_run_skill_tree_cases.py \
        --config-dir /mnt/c/users/eduar/Documents/Proyectos/godot/.cognits \
        --data-dir /tmp/opencode/tree-cases/.cognits \
        --fresh

    # Skip generation (re-examine existing trees):
    uv run python scripts/dev_run_skill_tree_cases.py \
        --config-dir /mnt/c/users/eduar/Documents/Proyectos/godot/.cognits \
        --data-dir /tmp/opencode/tree-cases/.cognits \
        --skip-generate

Generates sequentially (A → B → C) into separate sub-DBs under *data-dir*,
then prints a structured qualitative examination for human/LLM review.

Not packaged in the wheel — this is dev tooling.
"""

from __future__ import annotations

import argparse
import asyncio
import sqlite3
import sys
import traceback
from collections import Counter, defaultdict
from pathlib import Path

# Ensure the repo root is on sys.path so cognits is importable.
_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

# ---------------------------------------------------------------------------
# The 3 learner profiles (same goal, different floors)
# ---------------------------------------------------------------------------

GOAL = (
    "2D top-down pixel-art roguelike in Godot 4 "
    "(Enter the Gungeon inspired), with emergent systems"
)

CASES: dict[str, dict[str, str]] = {
    "A": {
        "label": "A (beginner)",
        "profile": (
            "Complete beginner. Zero programming experience, zero game "
            "development experience, zero Godot exposure, basic high-school "
            "math. Goal: build a Gungeon-inspired game."
        ),
    },
    "B": {
        "label": "B (physicist)",
        "profile": (
            "Physicist with strong Python proficiency (85%), prior Godot "
            "Editor exposure (70%), knows 2D vector math well (85%), basic "
            "pixel art experience (55%), no game design background. Goal: "
            "build a complete Gungeon-inspired game with procedural dungeons "
            "+ emergent systems."
        ),
    },
    "C": {
        "label": "C (expert)",
        "profile": (
            "Experienced game developer. Already shipped 2 complete 2D games "
            "in Godot 4 (one roguelike), strong GDScript (90%), knows pixel "
            "art (85%), procedural generation (80%), combat systems (80%). "
            "Goal: add emergent systems + narrative depth to a Gungeon-"
            "inspired game (the advanced stuff I haven't done)."
        ),
    },
}

# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Generate 3 skill trees for the same goal with different "
        "learner floors, then print a qualitative examination."
    )
    p.add_argument(
        "--config-dir",
        default="/mnt/c/users/eduar/Documents/Proyectos/godot/.cognits",
        help="Path to .cognits dir where config.json lives (API keys).",
    )
    p.add_argument(
        "--data-dir",
        default="/tmp/opencode/tree-cases/.cognits",
        help="Parent .cognits dir; each case gets a sub-dir case-{A|B|C}/.",
    )
    p.add_argument(
        "--cases",
        default="A,B,C",
        help="Comma-separated cases to run (default: A,B,C).",
    )
    p.add_argument(
        "--fresh",
        action="store_true",
        help="Delete each sub-DB before running (clean tree).",
    )
    p.add_argument(
        "--skip-generate",
        action="store_true",
        help="Do NOT run generation — only examine existing trees.",
    )
    return p.parse_args(argv)


# ---------------------------------------------------------------------------
# Qualitative examination
# ---------------------------------------------------------------------------


def _examine(db_path: Path, case_label: str) -> None:
    """Run a qualitative examination against the DB and print it.

    Opens read-only, queries the skill tree, and prints structured sections
    for human/LLM review.  Mirrors query patterns from ``dev_judge_tree.py``
    but goes deeper: floor, top-level branches, goal-directedness,
    granularity, prerequisite correctness, Bloom spread, item quality,
    floor calibration.
    """
    uri = f"file:{db_path}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    try:
        conn.execute("PRAGMA read_uncommitted = false")

        print(f"\n{'=' * 65}")
        print(f" CASE {case_label} — Qualitative Examination")
        print(f"{'=' * 65}")

        # Counts (summary).
        skills_n = conn.execute("SELECT COUNT(*) FROM skills").fetchone()[0]
        edges_n = conn.execute(
            "SELECT COUNT(*) FROM skill_prerequisites WHERE skill_id IS NOT NULL"
        ).fetchone()[0]
        items_n = conn.execute(
            "SELECT COUNT(*) FROM skill_assessment_items"
        ).fetchone()[0]
        print(f"\nSkills: {skills_n}  Edges: {edges_n}  Items: {items_n}")

        # Pre-fetch skill name/id/bloom/domain lookup.
        skill_rows = conn.execute(
            "SELECT id, name, bloom_level, domain FROM skills"
        ).fetchall()
        skill_name: dict[str, str] = {}
        skill_bloom: dict[str, str] = {}
        skill_domain: dict[str, str] = {}
        for sid, name, bloom, domain in skill_rows:
            skill_name[sid] = name or ""
            skill_bloom[sid] = bloom or ""
            skill_domain[sid] = domain or ""

        all_skill_ids = set(skill_name.keys())

        # Edges: (skill_id, prereq_id).
        edge_rows = conn.execute(
            "SELECT skill_id, prereq_id FROM skill_prerequisites "
            "WHERE skill_id IS NOT NULL"
        ).fetchall()
        edges: list[tuple[str, str]] = [
            (sk, pr) for sk, pr in edge_rows
        ]

        # Reverse adjacency: prereq_id → [dependent skill_ids].
        dep_of: dict[str, list[str]] = defaultdict(list)
        # Forward adjacency: skill_id → [its prereq_ids].
        prereq_of: dict[str, list[str]] = defaultdict(list)
        for sk, pr in edges:
            dep_of[pr].append(sk)
            prereq_of[sk].append(pr)

        # ---------------------------------------------------------------
        # Floor (roots = learner's assumed knowledge)
        # ---------------------------------------------------------------
        print(f"\n--- Floor (roots = where the tree stops) ---")
        has_prereq = {sk for sk, _ in edges}
        # Floor: skills that are prereqs of others but have no prereqs themselves.
        floor_ids = {pr for _, pr in edges if pr not in has_prereq}
        also_root_not_prereq = all_skill_ids - has_prereq - floor_ids
        # Merge: all roots (no prereqs) that are depended-upon or are orphans.
        floor_ids |= {s for s in also_root_not_prereq if s in dep_of}
        floor_ids_sorted = sorted(floor_ids, key=lambda sid: skill_name.get(sid, ""))
        print(f"  {len(floor_ids)} floor skills (the learner's assumed knowledge):")
        for sid in floor_ids_sorted[:10]:
            name = skill_name.get(sid, sid)[:80]
            bloom = skill_bloom.get(sid, "?")
            domain = skill_domain.get(sid, "?")
            deps = len(dep_of.get(sid, []))
            print(f"    [{bloom}] {name} ({domain}, {deps} dependents)")
        if len(floor_ids) > 10:
            print(f"    ... and {len(floor_ids) - 10} more")

        # ---------------------------------------------------------------
        # Top-level branches (goal skill's immediate prerequisites)
        # ---------------------------------------------------------------
        print(f"\n--- Top-level branches (goal's immediate prerequisites) ---")
        goal_id = _find_goal_skill(conn, skill_name)
        if goal_id and goal_id in prereq_of:
            goal_prereqs = prereq_of[goal_id]
            for sid in goal_prereqs:
                name = skill_name.get(sid, sid)[:80]
                bloom = skill_bloom.get(sid, "?")
                subtree_size = _subtree_size(sid, dep_of)
                print(f"    [{bloom}] {name} → subtree: {subtree_size} skills")
        else:
            print("  (goal skill not found or has no prerequisites)")

        # ---------------------------------------------------------------
        # Goal-directedness
        # ---------------------------------------------------------------
        print(f"\n--- Goal-directedness (skills on a path to the goal) ---")
        if goal_id:
            reachable = _bfs_reachable_reverse_from_edges(goal_id, edges)
            reachable_n = len(reachable)
            pct = (reachable_n / skills_n * 100) if skills_n else 0
            print(f"  {reachable_n}/{skills_n} skills ({pct:.1f}%) on a goal-path")
            if reachable_n < skills_n:
                dangling = all_skill_ids - reachable
                print(f"  {len(dangling)} dangling skills (not on any path to goal):")
                for sid in sorted(dangling, key=lambda s: skill_name.get(s, ""))[:5]:
                    name = skill_name.get(sid, sid)[:80]
                    print(f"    - {name}")
                if len(dangling) > 5:
                    print(f"    ... and {len(dangling) - 5} more")
        else:
            print("  (goal skill not found — cannot compute)")

        # ---------------------------------------------------------------
        # Granularity sample (3 deepest leaves)
        # ---------------------------------------------------------------
        print(f"\n--- Granularity sample (3 leaf skills — deepest decomposition) ---")
        leaves = [sid for sid in all_skill_ids if not dep_of.get(sid)]
        if goal_id and leaves:
            reachable_set = _bfs_reachable_reverse_from_edges(goal_id, edges)
            reachable_leaves = [s for s in leaves if s in reachable_set]
            leaves_by_depth = [
                (sid, _depth_from_root(sid, goal_id, dep_of))
                for sid in (reachable_leaves or leaves)
            ]
            leaves_by_depth.sort(key=lambda x: -x[1])
            top_leaves = leaves_by_depth[:3]
        else:
            top_leaves = [(sid, 0) for sid in leaves[:3]]

        for sid, depth in top_leaves:
            name = skill_name.get(sid, sid)[:80]
            bloom = skill_bloom.get(sid, "?")
            items = _items_for_skill(conn, sid)
            item_str = items[0][:120] + "..." if items else "(no items)"
            print(f"    Depth {depth} | [{bloom}] {name}")
            print(f"      Item: {item_str}")

        # ---------------------------------------------------------------
        # Prerequisite sample (3 edges with proof_query)
        # ---------------------------------------------------------------
        print(f"\n--- Prerequisite sample (3 edges — are they correct?) ---")
        proof_rows = conn.execute(
            "SELECT skill_id, prereq_id, proof_query FROM skill_prerequisites "
            "WHERE skill_id IS NOT NULL AND proof_query IS NOT NULL AND proof_query != '' "
            "LIMIT 30"
        ).fetchall()
        import random
        random.seed(42)
        sample_edges = random.sample(proof_rows, min(3, len(proof_rows))) if proof_rows else []
        for sk, pr, proof in sample_edges:
            sk_name = skill_name.get(sk, sk)[:80]
            pr_name = skill_name.get(pr, pr)[:80]
            proof_short = (proof or "")[:150]
            print(f"    {sk_name}")
            print(f"      REQUIRES {pr_name}")
            print(f"      proof: {proof_short}")

        # ---------------------------------------------------------------
        # Bloom spread
        # ---------------------------------------------------------------
        print(f"\n--- Bloom spread (does it match the floor?) ---")
        bloom_counts = conn.execute(
            "SELECT bloom_level, COUNT(*) FROM skills "
            "GROUP BY bloom_level ORDER BY COUNT(*) DESC"
        ).fetchall()
        bloom_total = sum(c for _, c in bloom_counts)
        for lv, c in bloom_counts:
            pct = (c / bloom_total * 100) if bloom_total else 0
            bar = "█" * int(pct / 2)
            print(f"  {lv:<20s}: {c:>3d} ({pct:5.1f}%) {bar}")

        # Also show bloom of seeded (floor) skills.
        seeded = conn.execute(
            "SELECT skill_id, p_mastery FROM learner_state WHERE p_mastery IS NOT NULL"
        ).fetchall()
        seeded_blooms = Counter()
        for sid, _ in seeded:
            seeded_blooms[skill_bloom.get(sid, "?")] += 1
        if seeded_blooms:
            print(f"\n  Seeded (floor) bloom:")
            for lv in sorted(seeded_blooms):
                print(f"    {lv}: {seeded_blooms[lv]}")

        # ---------------------------------------------------------------
        # Item quality sample (3 random items + skill Bloom)
        # ---------------------------------------------------------------
        print(f"\n--- Item quality sample (3 items — are they good?) ---")
        item_rows = conn.execute(
            "SELECT a.rowid, a.skill_id, a.question, a.question_type "
            "FROM skill_assessment_items a ORDER BY RANDOM() LIMIT 3"
        ).fetchall()
        for rowid, sid, question, qtype in item_rows:
            name = skill_name.get(sid, sid)[:80]
            bloom = skill_bloom.get(sid, "?")
            question_short = (question or "")[:200]
            print(f"    Skill [{bloom}]: {name}")
            print(f"      Type: {qtype or '?'}")
            print(f"      Question: {question_short}")

        # ---------------------------------------------------------------
        # Floor calibration (does seeded mastery match profile claims?)
        # ---------------------------------------------------------------
        print(f"\n--- Floor calibration (is the floor right for the profile?) ---")
        if seeded:
            high = [(sid, pm) for sid, pm in seeded if pm is not None and pm >= 0.75]
            mid = [(sid, pm) for sid, pm in seeded if pm is not None and 0.40 <= pm < 0.75]
            low = [(sid, pm) for sid, pm in seeded if pm is not None and pm < 0.40]
            print(f"  Seeded skills: {len(seeded)} total")
            print(f"    High mastery (≥0.75): {len(high)}")
            print(f"    Mid mastery (0.40-0.74): {len(mid)}")
            print(f"    Low mastery (<0.40): {len(low)}")

            # Show high-mastery seeds (the active frontier).
            if high:
                print(f"  High-mastery frontier (what the learner already knows):")
                for sid, pm in high[:10]:
                    name = skill_name.get(sid, sid)[:80]
                    bloom = skill_bloom.get(sid, "?")
                    print(f"    [{bloom}] {name} @ {pm:.2f}")
                if len(high) > 10:
                    print(f"    ... and {len(high) - 10} more")
            else:
                print("  ⚠ No high-mastery seeds — no active frontier present")

            # Show low-mastery seeds (near-zero, likely the goal area).
            if low:
                print(f"  Low-mastery frontier (target learning area):")
                for sid, pm in low[:10]:
                    name = skill_name.get(sid, sid)[:80]
                    bloom = skill_bloom.get(sid, "?")
                    print(f"    [{bloom}] {name} @ {pm:.2f}")
                if len(low) > 10:
                    print(f"    ... and {len(low) - 10} more")
        else:
            print("  No seeded mastery at all — floor is empty")

        # ---------------------------------------------------------------
        # Domains breakdown
        # ---------------------------------------------------------------
        print(f"\n--- Domains ---")
        domain_counts = conn.execute(
            "SELECT domain, COUNT(*) FROM skills GROUP BY domain ORDER BY COUNT(*) DESC"
        ).fetchall()
        for d, c in domain_counts:
            pct = (c / skills_n * 100) if skills_n else 0
            print(f"  {d}: {c} ({pct:.1f}%)")

        print()

    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Helper SQL queries
# ---------------------------------------------------------------------------


def _find_goal_skill(conn: sqlite3.Connection, skill_name: dict[str, str]) -> str | None:
    """Find the goal skill by matching a Gungeon/roguelike keyword in the name."""
    keywords = ["gungeon", "roguelike", "rogue-like", "roguelike game"]
    for kw in keywords:
        for sid, name in skill_name.items():
            if kw.lower() in name.lower():
                return sid
    # Fallback: the skill with the most dependents (likely the root goal).
    row = conn.execute(
        "SELECT id FROM skills ORDER BY LENGTH(name) DESC LIMIT 1"
    ).fetchone()
    return row[0] if row else None


def _bfs_reachable_reverse_from_edges(
    start_id: str,
    edges: list[tuple[str, str]],
) -> set[str]:
    """BFS from *start_id* through prereq edges (skill → prereq direction).

    Returns all skills on a path from any leaf to the goal, plus the goal.
    """
    # Build adjacency: skill_id → [prereq_ids]
    prereq_of: dict[str, list[str]] = defaultdict(list)
    for sk, pr in edges:
        prereq_of[sk].append(pr)

    visited: set[str] = set()
    queue = [start_id]
    while queue:
        cur = queue.pop(0)
        if cur in visited:
            continue
        visited.add(cur)
        for pr in prereq_of.get(cur, []):
            if pr not in visited:
                queue.append(pr)
    return visited


def _subtree_size(skill_id: str, dep_of: dict[str, list[str]]) -> int:
    """Count all descendants (skills that depend on this one, recursively)."""
    seen: set[str] = set()
    stack = [skill_id]
    while stack:
        sid = stack.pop()
        if sid in seen:
            continue
        seen.add(sid)
        stack.extend(dep_of.get(sid, []))
    return len(seen) - 1  # exclude self


def _depth_from_root(
    leaf_id: str,
    goal_id: str,
    dep_of: dict[str, list[str]],
) -> int:
    """Compute depth from *leaf_id* to *goal_id* following dependency edges.

    dep_of maps prereq_id → [dependent skills]. We reverse it to walk
    skill → prereq direction (i.e. leaf → ... → goal).
    """
    # Build reverse: skill → [its prereqs].
    prereq_of: dict[str, list[str]] = defaultdict(list)
    for pr, deps in dep_of.items():
        for dep in deps:
            prereq_of[dep].append(pr)

    # BFS from leaf to goal.
    if leaf_id == goal_id:
        return 0
    visited: set[str] = {leaf_id}
    queue = [(leaf_id, 0)]
    while queue:
        cur, d = queue.pop(0)
        for pr in prereq_of.get(cur, []):
            if pr == goal_id:
                return d + 1
            if pr not in visited:
                visited.add(pr)
                queue.append((pr, d + 1))
    return -1


def _items_for_skill(conn: sqlite3.Connection, skill_id: str) -> list[str]:
    """Return the question text of assessment items for a skill."""
    rows = conn.execute(
        "SELECT question FROM skill_assessment_items WHERE skill_id = ?",
        (skill_id,),
    ).fetchall()
    return [r[0] or "" for r in rows]


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


async def main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)

    from scripts.dev_run_skill_planner import generate

    config_dir = Path(args.config_dir)
    data_dir = Path(args.data_dir)
    cases_to_run = [c.strip() for c in args.cases.split(",") if c.strip() in CASES]

    if not cases_to_run:
        print("[FATAL] No valid cases selected (use A, B, C).")
        sys.exit(1)

    total_fails = 0

    for case_key in cases_to_run:
        case_info = CASES[case_key]
        case_label = case_info["label"]
        case_profile = case_info["profile"]
        sub_data_dir = data_dir / f"case-{case_key}"

        print(f"\n{'#' * 65}")
        print(f"# CASE {case_label}")
        print(f"{'#' * 65}")

        if not args.skip_generate:
            print(f"\n=== Generating case {case_label} ===")
            db = None
            try:
                db = await generate(
                    objective=GOAL,
                    profile=case_profile,
                    config_dir=config_dir,
                    data_dir=sub_data_dir,
                    fresh=args.fresh,
                    session_id=f"dev-cases-{case_key}",
                )
            except Exception:
                traceback.print_exc()
                total_fails += 1
                continue
            finally:
                if db is not None:
                    try:
                        db.shutdown()
                    except Exception:
                        pass

        # Examine the generated tree.
        db_path = sub_data_dir / "cognits.db"
        if not db_path.exists():
            legacy_path = sub_data_dir / "learnit.db"
            if legacy_path.exists():
                db_path = legacy_path
            else:
                print(f"\n[WARN] No DB at {sub_data_dir} — skipping examination")
                total_fails += 1
                continue

        # Run the judge audit (structural PASS/FAIL).
        print(f"\n=== Auditing case {case_label} (judge) ===")
        from scripts.dev_judge_tree import _audit
        _audit(db_path, GOAL)

        # Run the qualitative examination.
        _examine(db_path, case_label)

    if total_fails:
        print(f"\n[FATAL] {total_fails} case(s) failed or skipped.\n")
        sys.exit(1)
    else:
        print("\n[DONE] All cases generated and examined.\n")


if __name__ == "__main__":
    asyncio.run(main())
