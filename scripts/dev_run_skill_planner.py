#!/usr/bin/env python3
"""Run the skill_planner agent autonomously against a target DB.

Usage::

    uv run python scripts/dev_run_skill_planner.py \
        --objective "2D roguelike in Godot 4" \
        --profile "I have 6 months of Python experience..." \
        --config-dir /mnt/c/users/eduar/Documents/Proyectos/godot/.cognits \
        --data-dir /tmp/opencode/tree-build/.cognits \
        --fresh

This script:
1. Reads encrypted API keys from *config-dir* (via Store.load_config).
2. Opens (or creates) the skill-tree DB at *data-dir*.
3. Runs the real skill_planner agent (DeepSeek + TinyFish tokens — ~15-25 min).
4. Prints progress to stdout.

Not packaged in the wheel — this is dev tooling.
"""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import os
import sys
import traceback
from pathlib import Path

# Ensure the repo root is on sys.path so cognits is importable.
_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Run the skill_planner agent autonomously."
    )
    p.add_argument(
        "--objective",
        required=True,
        help="The learning objective (e.g. '2D pixel-art roguelike in Godot 4').",
    )
    p.add_argument(
        "--profile",
        required=True,
        help="Learner profile: background, prior knowledge, goal.",
    )
    p.add_argument(
        "--config-dir",
        default="/mnt/c/users/eduar/Documents/Proyectos/godot/.cognits",
        help="Path to .cognits dir where config.json lives (API keys).",
    )
    p.add_argument(
        "--data-dir",
        default="/tmp/opencode/tree-build/.cognits",
        help="Path to .cognits dir to write the tree DB into.",
    )
    p.add_argument(
        "--fresh",
        action="store_true",
        help="Delete cognits.db in data-dir before running (clean tree).",
    )
    p.add_argument(
        "--session-id",
        default="dev-build",
        help="Session id for the agent (default: dev-build).",
    )
    return p.parse_args(argv)


def _emit(ev: dict) -> None:
    """Print progress to stdout and flush.

    Receives a single dict event {"type": ..., "data": ...} from the agent.
    Only prints high-signal events; skips token/reasoning/usage floods.
    """
    t = ev.get("type", "")
    if t not in ("tool_start", "tool_end", "subagent_end", "error", "finish"):
        return
    data = ev.get("data") or {}
    msg = str(data)[:160] if data else ""
    print(f"  [{t}] {msg}", flush=True)


def _summarize_tree(db: "Database") -> None:
    """Print a quick summary of the generated tree."""
    import sqlite3

    conn = db.conn
    skills_n = conn.execute("SELECT COUNT(*) FROM skills").fetchone()[0]
    edges_n = conn.execute(
        "SELECT COUNT(*) FROM skill_prerequisites WHERE skill_id IS NOT NULL"
    ).fetchone()[0]
    items_n = conn.execute(
        "SELECT COUNT(*) FROM skill_assessment_items"
    ).fetchone()[0]
    domains = [
        r[0]
        for r in conn.execute(
            "SELECT DISTINCT domain FROM skills ORDER BY domain"
        ).fetchall()
    ]
    blooms = conn.execute(
        "SELECT bloom_level, COUNT(*) FROM skills GROUP BY bloom_level ORDER BY COUNT(*) DESC"
    ).fetchall()
    seed_n = conn.execute(
        "SELECT COUNT(*) FROM learner_state WHERE p_mastery IS NOT NULL"
    ).fetchone()[0]

    print(f"\n--- Tree summary ---")
    print(f"Skills: {skills_n}  Edges: {edges_n}  Items: {items_n}")
    print(f"Domains: {len(domains)} ({', '.join(domains)})")
    print(f"Bloom: {', '.join(f'{lv}={n}' for lv, n in blooms)}")
    print(f"Seeded mastery: {seed_n} skills")


async def main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)

    from cognits.storage.files import Store
    from cognits.storage.database import Database
    from cognits.storage.skills import SkillRepository
    from cognits.storage.learner_state import LearnerStateRepository
    from cognits.storage.reports import ReportRepository
    from cognits.storage.study_plans import StudyPlanRepository
    from cognits.storage.assessment import AssessmentItemRepository
    from cognits.llm.deepseek import DeepSeekClient
    from cognits.tinyfish import TinyfishClient
    from cognits.agent.subagents import skill_planner_config
    from cognits.agent.agent import Agent
    from cognits.agent.tracer import NoopTracer
    from cognits.llm.types import Message, ROLE_USER
    from cognits.constants import DEFAULT_MODEL, SKILL_PLANNER_MAX_STEPS

    config_dir = Path(args.config_dir)
    data_dir = Path(args.data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    db_path = data_dir / "cognits.db"

    if args.fresh:
        for suffix in ("", "-wal", "-shm", "-journal"):
            p = data_dir / f"cognits.db{suffix}"
            if p.exists():
                p.unlink()
        for legacy_suffix in ("", "-wal", "-shm", "-journal"):
            p = data_dir / f"learnit.db{legacy_suffix}"
            if p.exists():
                p.unlink()
        print(f"[INIT] Fresh run — deleted {db_path}")
    elif db_path.exists():
        print(f"[INIT] DB exists at {db_path} — resuming incremental build")

    db: Database | None = None
    try:
        # 1. Load config (decrypts API keys).
        store = Store(config_dir)
        cfg = store.load_config()
        print(f"[INIT] Config loaded from {config_dir}")
        print(f"       LLM key: {'present' if cfg.llm_api_key else 'MISSING'}")
        print(f"       TinyFish key: {'present' if cfg.tinyfish_api_key else 'MISSING'}")
        print(f"       Config model: {cfg.llm_model or '(not set — will use default)'}")

        if not cfg.llm_api_key:
            print("[FATAL] No LLM API key found in config.json — aborting.")
            sys.exit(1)

        # 2. Open DB + construct repos.
        db = Database(db_path)
        skills_repo = SkillRepository(db)
        learner_state_repo = LearnerStateRepository(db)
        reports_repo = ReportRepository(db)
        study_plans_repo = StudyPlanRepository(db)
        assessment_repo = AssessmentItemRepository(db)

        # 3. Create clients.
        llm_client = DeepSeekClient(cfg.llm_api_key)
        tf_client = TinyfishClient(cfg.tinyfish_api_key)

        print("\n[RAG] Disabled — reports will be saved but not indexed during this "
              "run.\n       Run `cognits` later to backfill-index via the startup scan.\n")

        # 4. Build the skill_planner agent config.
        planner_cfg = skill_planner_config(
            model=DEFAULT_MODEL,
            reasoning="max",
            max_steps=SKILL_PLANNER_MAX_STEPS,
            llm_client=llm_client,
            rag_engine=None,
            tf_client=tf_client,
            reports=reports_repo,
            skills=skills_repo,
            assessment=assessment_repo,
            learner_state=learner_state_repo,
            session_id=lambda: args.session_id,
            emit=_emit,
            tinyfish_api_key=cfg.tinyfish_api_key,
            tool_emit=_emit,
        )
        # Ensure model+reasoning are set (mirrors tool_deploy.py:153)
        planner_cfg = dataclasses.replace(
            planner_cfg, model=DEFAULT_MODEL, reasoning="max"
        )

        # 5. Construct message.
        prompt = (
            f"Build a skill tree for: {args.objective}\n\n"
            f"Learner profile:\n{args.profile}"
        )
        messages = [Message(role=ROLE_USER, content=prompt)]

        # 6. Run agent.
        agent = Agent(planner_cfg, llm_client, tracer=NoopTracer())
        print(f"\n[RUN] Starting skill_planner (max_steps={planner_cfg.max_steps}, "
              f"model={planner_cfg.model}, reasoning={planner_cfg.reasoning})")
        print(f"      Objective: {args.objective[:120]}...")
        print(f"      Session: {args.session_id}\n")

        result = await agent.run(messages, emit=_emit)

        # 7. Summarize.
        print(f"\n[DONE] Agent finished.")
        short = result[:2000]
        print(f"\n--- Agent output (first 2000 chars) ---\n{short}")
        if len(result) > 2000:
            print(f"\n... (truncated, total {len(result)} chars)")

        _summarize_tree(db)

        if db:
            db.shutdown()
            db = None

    except Exception:
        traceback.print_exc()
    finally:
        if db is not None:
            try:
                db.shutdown()
            except Exception:
                pass


if __name__ == "__main__":
    asyncio.run(main())
