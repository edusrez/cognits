"""Tool used by the skill_planner subagent to persist a learner's skill
tree node-by-node and edge-by-edge during an iterative build pass.

A single tool with an ``action`` enum keeps the prompt compact (one function
definition vs four) and preserves DeepSeek's prefix-cache ordering
invariant (tools.definitions() is sorted by name).

All persistence goes through ``ReportStore`` (the same handle used by
reports/notes/etc.) which carries its own thread lock. We wrap the sync
calls with ``asyncio.to_thread`` to keep the event loop free, mirroring
``tool_deploy.py``.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable

from cognits.storage.assessment import AssessmentItemRepository
from cognits.storage.models import (
    EDGE_TYPES,
    AssessmentItem,
    LearnerState,
    Skill,
    new_assessment_item_id,
    new_skill_id,
)
from cognits.tools import Tool, tool_error


class SkillTreeSave(Tool):
    def __init__(
        self,
        skills,
        assessment: AssessmentItemRepository,
        session_id: Callable[[], str] | None = None,
        emit=None,
    ):
        self.skills = skills
        self.assessment = assessment
        self.session_id = session_id
        self.emit = emit

    name = "skill_tree_save"
    description = (
        "Persist a piece of the learner's skill tree atomically. Call "
        "repeatedly while building the tree: open a build pass, upsert "
        "nodes, add typed prerequisite edges, then close the build. Each "
        "call commits to durable storage so partial progress survives "
        "cancellation."
    )
    schema = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["start_build", "propose_targets", "upsert_skill", "add_edge", "finish_build", "save_assessment_items", "list_assessment_items", "validate_tree"],
                "description": "Which tree mutation to perform.",
            },
            "trigger": {
                "type": "string",
                "description": "start_build: short label for what triggered the pass (e.g. 'onboarding').",
            },
            "build_id": {
                "type": "string",
                "description": "add_edge/finish_build: build id returned by start_build.",
            },
            "domain": {
                "type": "string",
                "description": "upsert_skill: coarse domain the skill belongs to (e.g. 'python', 'algebra').",
            },
            "name": {
                "type": "string",
                "description": "upsert_skill: human-readable skill name.",
            },
            "description": {
                "type": "string",
                "description": "upsert_skill: 1-2 sentence description of what the skill entails.",
            },
            "bloom_level": {
                "type": "string",
                "description": "upsert_skill (optional): Bloom's level (remember/understand/apply/analyze/evaluate/create).",
            },
            "difficulty": {
                "type": "number",
                "description": "upsert_skill (optional): 0.0-1.0 estimate of how hard the skill is for a beginner.",
            },
            "parent_skill_id": {
                "type": "string",
                "description": "upsert_skill (optional): id of the parent skill in the tree (for hierarchical grouping).",
            },
            "skill_id": {
                "type": "string",
                "description": "upsert_skill (optional): provide to update an existing skill instead of creating new. add_edge: id of the skill that has the prerequisite.",
            },
            "prereq_id": {
                "type": "string",
                "description": "add_edge: id of the skill that is the prerequisite.",
            },
            "edge_type": {
                "type": "string",
                "enum": list(EDGE_TYPES),
                "description": "add_edge: 'prereq' (AND, all must be mastered), 'alt_prereq' (OR, any one in same group_id satisfies — requires group_id), 'coreq' (taken together), 'related' (loose link), 'soft_prereq' (bonus, never blocks).",
            },
            "group_id": {
                "type": "string",
                "description": "add_edge: REQUIRED for edge_type='alt_prereq'. Shared identifier for OR-alternatives — edges with the same group_id form an OR-set.",
            },
            "proof_query": {
                "type": "string",
                "description": "add_edge (optional): web search query that justified this prerequisite relationship.",
            },
            "summary": {
                "type": "string",
                "description": "finish_build: human-readable synthesis of what the pass produced (domains, counts, depth).",
            },
            "status": {
                "type": "string",
                "description": "finish_build (optional): 'done' (default) or 'partial' if the pass ended early.",
            },
            "items": {
                "type": "array",
                "description": "save_assessment_items: array of item objects. Each must have: question, expected_answer, rubric, question_type, blooms_level, difficulty, generation_model. Optional: rubric_criteria.",
                "items": {"type": "object"},
            },
            "include_all": {
                "type": "boolean",
                "description": "list_assessment_items (optional): include inactive items too (default false).",
            },
            "domain_type": {
                "type": "string",
                "description": "propose_targets: domain type (programming, language, paper, field, creative, project).",
            },
            "size_range": {
                "type": "array",
                "description": "propose_targets: [min, max] skill count for this domain.",
                "items": {"type": "integer"},
                "minItems": 2,
                "maxItems": 2,
            },
            "bloom_targets": {
                "type": "object",
                "description": "propose_targets: per-Bloom-level % ranges. Keys: remember, understand, apply, analyze, evaluate, create. Values: [min, max].",
            },
            "max_depth": {
                "type": "integer",
                "description": "propose_targets: maximum tree depth for this domain.",
            },
            "atomicity_criterion": {
                "type": "string",
                "description": "propose_targets: human-readable atomicity criterion for this domain.",
            },
        },
        "required": ["action"],
    }

    async def execute(self, raw_args: str) -> str:
        try:
            args = json.loads(raw_args)
            action = args["action"]
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            return tool_error(f"invalid args: {e}")

        if action == "start_build":
            return await self._start_build(args)
        if action == "propose_targets":
            return await self._propose_targets(args)
        if action == "upsert_skill":
            return await self._upsert_skill(args)
        if action == "add_edge":
            return await self._add_edge(args)
        if action == "finish_build":
            return await self._finish_build(args)
        if action == "save_assessment_items":
            return await self._save_assessment_items(args)
        if action == "list_assessment_items":
            return await self._list_assessment_items(args)
        if action == "validate_tree":
            return await self._validate_tree(args)
        return tool_error(f"unknown action: {action}")

    async def _start_build(self, args: dict) -> str:
        trigger = args.get("trigger", "")
        sid = self.session_id() if self.session_id is not None else ""
        build_id = await asyncio.to_thread(self.skills.start_build, sid, trigger)
        return json.dumps({"build_id": build_id}, ensure_ascii=False)

    async def _propose_targets(self, args: dict) -> str:
        domain_type = args.get("domain_type", "")
        size_range = args.get("size_range")
        bloom_targets = args.get("bloom_targets")
        max_depth = args.get("max_depth")
        atomicity_criterion = args.get("atomicity_criterion", "")

        if not domain_type:
            return tool_error("propose_targets requires 'domain_type'")
        if not isinstance(size_range, list) or len(size_range) != 2:
            return tool_error("propose_targets requires 'size_range' as [min, max]")
        if not isinstance(bloom_targets, dict):
            return tool_error("propose_targets requires 'bloom_targets' object with per-level [min, max] ranges")

        targets_data = {
            "domain_type": domain_type,
            "size_range": size_range,
            "bloom_targets": bloom_targets,
            "max_depth": max_depth,
            "atomicity_criterion": atomicity_criterion,
        }
        targets_json = json.dumps(targets_data, ensure_ascii=False)

        def _update():
            db = self.skills.db
            with db.lock:
                row = db.conn.execute(
                    "SELECT id FROM skill_builds ORDER BY started_at DESC LIMIT 1"
                ).fetchone()
                if row is None:
                    return None
                build_id = row[0]
                db.conn.execute(
                    "UPDATE skill_builds SET targets = ? WHERE id = ?",
                    (targets_json, build_id),
                )
                return build_id

        build_id = await asyncio.to_thread(_update)
        if build_id is None:
            return tool_error("propose_targets: no active build found — call start_build first")
        return json.dumps({"ok": True, "build_id": build_id, "targets": targets_data}, ensure_ascii=False)

    async def _upsert_skill(self, args: dict) -> str:
        name = args.get("name")
        domain = args.get("domain")
        if not name or not domain:
            return tool_error("upsert_skill requires 'name' and 'domain'")
        skill_id = args.get("skill_id") or new_skill_id()
        skill = Skill(
            id=skill_id,
            domain=domain,
            name=name,
            description=args.get("description", ""),
            bloom_level=args.get("bloom_level", ""),
            difficulty=float(args.get("difficulty", 0.5)),
            parent_skill_id=args.get("parent_skill_id", "") or "",
            source="skill_planner",
        )
        await asyncio.to_thread(self.skills.upsert, skill)
        return json.dumps({"skill_id": skill_id}, ensure_ascii=False)

    async def _add_edge(self, args: dict) -> str:
        skill_id = args.get("skill_id")
        prereq_id = args.get("prereq_id")
        if not skill_id or not prereq_id:
            return tool_error("add_edge requires 'skill_id' and 'prereq_id'")
        edge_type = args.get("edge_type", "prereq")
        proof_query = args.get("proof_query", "")
        build_id = args.get("build_id", "")
        group_id = args.get("group_id", "")
        # Validate alt_prereq requires group_id (redundant with repo-side
        # check, but gives the LLM a friendlier tool_error).
        if edge_type == "alt_prereq" and not group_id:
            return tool_error("alt_prereq requires group_id")
        try:
            await asyncio.to_thread(
                self.skills.add_edge,
                skill_id,
                prereq_id,
                edge_type,
                proof_query,
                build_id,
                group_id,
            )
        except ValueError as e:
            return tool_error(str(e))
        return json.dumps({"ok": True}, ensure_ascii=False)

    async def _finish_build(self, args: dict) -> str:
        build_id = args.get("build_id")
        if not build_id:
            return tool_error("finish_build requires 'build_id'")
        summary = args.get("summary", "")
        status = args.get("status", "done")

        # Count how many active skills have < 3 assessment items (best-effort).
        try:
            all_skills = await asyncio.to_thread(self.skills.list_active)
            if all_skills:
                skill_ids = [s.id for s in all_skills]
                items = await asyncio.to_thread(self.assessment.list_for_skills, skill_ids, True)
                counts: dict[str, int] = {}
                for it in items:
                    counts[it.skill_id] = counts.get(it.skill_id, 0) + 1
                n_underitemed = sum(1 for sid in skill_ids if counts.get(sid, 0) < 3)
                summary += f" | {n_underitemed}/{len(skill_ids)} skills have <3 assessment items"
        except Exception:
            pass

        await asyncio.to_thread(
            self.skills.finish_build, build_id, summary, status
        )
        return json.dumps({"ok": True}, ensure_ascii=False)

    async def _save_assessment_items(self, args: dict) -> str:
        skill_id = args.get("skill_id")
        items = args.get("items")
        if not skill_id:
            return tool_error("save_assessment_items requires 'skill_id'")
        if not isinstance(items, list) or len(items) == 0:
            return tool_error("save_assessment_items requires non-empty 'items' array")

        existing = await asyncio.to_thread(self.skills.get, skill_id)
        if existing is None:
            return tool_error(f"skill_id '{skill_id}' does not exist")

        warning = None
        if len(items) < 3:
            warning = "fewer than 3 items — BKT reliability may suffer"

        saved_ids = []
        for it in items:
            item_id = it.get("id") or new_assessment_item_id()
            rubric_criteria = it.get("rubric_criteria")
            rc_json = None
            if isinstance(rubric_criteria, list):
                rc_json = rubric_criteria
            ai = AssessmentItem(
                id=item_id,
                skill_id=skill_id,
                skill_ids=[skill_id],
                question=it.get("question", ""),
                question_type=it.get("question_type", "open"),
                expected_answer=it.get("expected_answer", ""),
                rubric=it.get("rubric", ""),
                rubric_criteria=rc_json,
                rubric_type=it.get("rubric_type", "analytic"),
                blooms_level=it.get("blooms_level", ""),
                difficulty=float(it.get("difficulty", 0.5)),
                irt_model=it.get("irt_model", "heuristic"),
                generation_model=it.get("generation_model", ""),
                generation_prompt_hash=it.get("generation_prompt_hash", ""),
                source=it.get("source", ""),
                seed_version=int(it.get("seed_version", 1)),
                times_presented=int(it.get("times_presented", 0)),
                times_correct=int(it.get("times_correct", 0)),
                status=it.get("status", "active"),
            )
            await asyncio.to_thread(self.assessment.save, ai)
            saved_ids.append(item_id)

        response = {"saved": len(saved_ids), "item_ids": saved_ids}
        if warning:
            response["warning"] = warning
        return json.dumps(response, ensure_ascii=False)

    async def _list_assessment_items(self, args: dict) -> str:
        skill_id = args.get("skill_id")
        if not skill_id:
            return tool_error("list_assessment_items requires 'skill_id'")
        include_all = bool(args.get("include_all", False))
        items = await asyncio.to_thread(
            self.assessment.list_for_skill, skill_id, include_all
        )
        item_dicts = []
        for ai in items:
            item_dicts.append({
                "id": ai.id,
                "skill_id": ai.skill_id,
                "skill_ids": ai.skill_ids,
                "question": ai.question,
                "question_type": ai.question_type,
                "expected_answer": ai.expected_answer,
                "rubric": ai.rubric,
                "rubric_criteria": ai.rubric_criteria,
                "rubric_type": ai.rubric_type,
                "blooms_level": ai.blooms_level,
                "difficulty": ai.difficulty,
                "p_value": ai.p_value,
                "irt_a": ai.irt_a,
                "irt_b": ai.irt_b,
                "irt_c": ai.irt_c,
                "irt_model": ai.irt_model,
                "generation_model": ai.generation_model,
                "generation_prompt_hash": ai.generation_prompt_hash,
                "template_id": ai.template_id,
                "source": ai.source,
                "seed_version": ai.seed_version,
                "times_presented": ai.times_presented,
                "times_correct": ai.times_correct,
                "avg_response_time_ms": ai.avg_response_time_ms,
                "status": ai.status,
                "reviewed_by": ai.reviewed_by,
                "created_at": ai.created_at,
                "updated_at": ai.updated_at,
            })
        return json.dumps({"items": item_dicts}, ensure_ascii=False)

    async def _validate_tree(self, args: dict) -> str:
        """Run a deterministic audit of the current skill tree in the DB.

        Reuses the EXACT logic from scripts/dev_judge_tree.py — queries the
        DB for counts, Bloom distribution, assessment items, proof_query
        coverage, connectivity (roots/orphans), and cycles. Returns a
        structured JSON response the skill_planner can act on.
        """

        def _audit():
            db = self.skills.db
            with db.lock:
                conn = db.conn

                # --- Counts ---
                skills_n = conn.execute(
                    "SELECT COUNT(*) FROM skills WHERE status='active'"
                ).fetchone()[0]
                edges_n = conn.execute(
                    "SELECT COUNT(*) FROM skill_prerequisites WHERE skill_id IS NOT NULL"
                ).fetchone()[0]
                items_n = conn.execute(
                    "SELECT COUNT(*) FROM skill_assessment_items WHERE status='active'"
                ).fetchone()[0]
                domains_rows = conn.execute(
                    "SELECT DISTINCT domain FROM skills WHERE status='active' ORDER BY domain"
                ).fetchall()
                domains_n = len(domains_rows)

                # --- Mastery seeding ---
                seed_row = conn.execute(
                    "SELECT COUNT(*), MAX(p_mastery) FROM learner_state "
                    "WHERE p_mastery != 0.5"
                ).fetchone()
                seeded_skills = seed_row[0] if seed_row else 0
                max_seeded_p_mastery = seed_row[1] if seed_row and seed_row[1] is not None else 0.0

                # --- Bloom distribution ---
                bloom_rows = conn.execute(
                    "SELECT bloom_level, COUNT(*) FROM skills WHERE status='active' "
                    "GROUP BY bloom_level"
                ).fetchall()
                remember_n = 0
                understand_n = 0
                apply_n = 0
                analyze_n = 0
                evaluate_n = 0
                create_n = 0
                for lv, c in bloom_rows:
                    lv_lower = lv.lower() if lv else ""
                    if "remember" in lv_lower or "recordar" in lv_lower:
                        remember_n += c
                    elif "understand" in lv_lower or "comprender" in lv_lower or "entender" in lv_lower:
                        understand_n += c
                    elif "apply" in lv_lower or "aplicar" in lv_lower:
                        apply_n += c
                    elif "analyze" in lv_lower or "analizar" in lv_lower:
                        analyze_n += c
                    elif "evaluate" in lv_lower or "evaluar" in lv_lower:
                        evaluate_n += c
                    elif "create" in lv_lower or "crear" in lv_lower:
                        create_n += c
                remember_pct = (remember_n / skills_n * 100) if skills_n else 0
                understand_pct = (understand_n / skills_n * 100) if skills_n else 0
                apply_pct = (apply_n / skills_n * 100) if skills_n else 0
                analyze_pct = (analyze_n / skills_n * 100) if skills_n else 0
                evaluate_pct = (evaluate_n / skills_n * 100) if skills_n else 0
                create_pct = (create_n / skills_n * 100) if skills_n else 0
                eval_create_pct = evaluate_pct + create_pct
                any_bloom_max_pct = max(
                    remember_pct, understand_pct, apply_pct,
                    analyze_pct, evaluate_pct, create_pct
                )

                apply_skills: list[str] = []
                if apply_pct > 35:
                    apply_skill_rows = conn.execute(
                        "SELECT id FROM skills WHERE status='active' AND "
                        "(bloom_level LIKE '%apply%' OR bloom_level LIKE '%aplicar%')"
                    ).fetchall()
                    apply_skills = [r[0] for r in apply_skill_rows]

                # --- Assessment items per skill ---
                item_dist = conn.execute(
                    "SELECT s.id, COUNT(a.rowid) as cnt FROM skills s "
                    "LEFT JOIN skill_assessment_items a ON a.skill_id = s.id AND a.status='active' "
                    "WHERE s.status='active' GROUP BY s.id"
                ).fetchall()
                skills_needing_items = [sid for sid, cnt in item_dist if cnt == 0]

                # --- Proof query coverage ---
                proof_nonempty = conn.execute(
                    "SELECT COUNT(*) FROM skill_prerequisites "
                    "WHERE proof_query IS NOT NULL AND proof_query != '' AND skill_id IS NOT NULL"
                ).fetchone()[0]
                proof_pct = (proof_nonempty / edges_n * 100) if edges_n else 100.0

                # --- Connectivity: roots ---
                has_prereq = set(
                    r[0] for r in conn.execute(
                        "SELECT DISTINCT skill_id FROM skill_prerequisites "
                        "WHERE skill_id IS NOT NULL"
                    ).fetchall()
                )
                all_skills = set(
                    r[0] for r in conn.execute(
                        "SELECT id FROM skills WHERE status='active'"
                    ).fetchall()
                )
                roots = all_skills - has_prereq
                ratio = edges_n / skills_n if skills_n else 0

                # --- Orphans: no prereq AND no dependents ---
                is_prereq_for = set(
                    r[0] for r in conn.execute(
                        "SELECT DISTINCT prereq_id FROM skill_prerequisites "
                        "WHERE skill_id IS NOT NULL"
                    ).fetchall()
                )
                orphan_ids = [s for s in roots if s not in is_prereq_for]

                # --- Item quality (WARN only; not FAIL) ---
                quality_rows = conn.execute(
                    "SELECT id, skill_id, question, rubric, expected_answer "
                    "FROM skill_assessment_items WHERE status='active'"
                ).fetchall()
                low_quality_item_ids: list[str] = []
                low_quality_skill_ids_set: set[str] = set()
                for qr in quality_rows:
                    iid, sid, question, rubric, expected_answer = qr
                    q_stripped = (question or "").strip()
                    r_stripped = (rubric or "").strip()
                    ea_stripped = (expected_answer or "").strip()
                    if q_stripped and len(q_stripped) < 20:
                        low_quality_item_ids.append(iid)
                        low_quality_skill_ids_set.add(sid)
                    elif not r_stripped or not ea_stripped:
                        low_quality_item_ids.append(iid)
                        low_quality_skill_ids_set.add(sid)

                # --- Cycle check (Kahn's on prereq/alt_prereq only) ---
                edge_pairs = [
                    (r[0], r[1])
                    for r in conn.execute(
                        "SELECT skill_id, prereq_id FROM skill_prerequisites "
                        "WHERE skill_id IS NOT NULL AND edge_type IN ('prereq','alt_prereq')"
                    ).fetchall()
                ]
                acyclic, _ = _kahn_cycle_check(edge_pairs)

                # --- Tree depth (BFS from roots through prereq/alt_prereq edges) ---
                adj: dict[str, list[str]] = {}
                for src, dst in edge_pairs:
                    adj.setdefault(dst, []).append(src)
                depths: dict[str, int] = {}
                for r in roots:
                    depths[r] = 0
                queue = list(roots)
                while queue:
                    node = queue.pop(0)
                    for child in adj.get(node, []):
                        if child not in depths:
                            depths[child] = depths[node] + 1
                            queue.append(child)
                max_depth_val = max(depths.values()) if depths else 0

                # --- Proposed targets (from the most recent build) ---
                targets_row = conn.execute(
                    "SELECT targets FROM skill_builds "
                    "WHERE targets != '' ORDER BY started_at DESC LIMIT 1"
                ).fetchone()
                targets_json = targets_row[0] if targets_row else None
                targets = None
                if targets_json:
                    try:
                        targets = json.loads(targets_json)
                    except (json.JSONDecodeError, TypeError):
                        pass

            return {
                "skills_n": skills_n,
                "edges_n": edges_n,
                "items_n": items_n,
                "domains_n": domains_n,
                "seeded_skills": seeded_skills,
                "max_seeded_p_mastery": max_seeded_p_mastery,
                "apply_pct": apply_pct,
                "apply_skills": apply_skills,
                "analyze_pct": analyze_pct,
                "eval_create_pct": eval_create_pct,
                "remember_pct": remember_pct,
                "understand_pct": understand_pct,
                "evaluate_pct": evaluate_pct,
                "create_pct": create_pct,
                "any_bloom_max_pct": any_bloom_max_pct,
                "skills_needing_items": skills_needing_items,
                "proof_pct": proof_pct,
                "roots": list(roots),
                "ratio": ratio,
                "orphan_ids": orphan_ids,
                "acyclic": acyclic,
                "low_quality_item_ids": low_quality_item_ids,
                "low_quality_skill_ids": list(low_quality_skill_ids_set),
                "targets": targets,
                "max_depth": max_depth_val,
            }

        result = await asyncio.to_thread(_audit)

        # --- Build structured response ---
        gaps: list[dict] = []
        all_pass = True

        # assessment_items
        zero_items = len(result["skills_needing_items"])
        if zero_items > 0:
            covered = result["skills_n"] - zero_items
            gaps.append({
                "criterion": "assessment_items",
                "severity": "FAIL",
                "current": f"{zero_items} skills with 0 items ({covered}/{result['skills_n']} have \u22651)",
                "target": "\u22651 per skill",
                "fix_hint": "Call save_assessment_items(skill_id=X, items=[...]) for each skill_id in skills_needing_items",
            })
            all_pass = False
        else:
            gaps.append({
                "criterion": "assessment_items",
                "severity": "PASS",
                "current": "All skills have \u22651 assessment item",
                "target": "\u22651 per skill",
            })

        # Bloom distribution checks — adaptive when targets proposed, hardcoded defaults otherwise
        proposed = result.get("targets")
        if proposed and isinstance(proposed, dict) and proposed.get("bloom_targets"):
            bt = proposed["bloom_targets"]
            bloom_pcts = {
                "remember": result["remember_pct"],
                "understand": result["understand_pct"],
                "apply": result["apply_pct"],
                "analyze": result["analyze_pct"],
                "evaluate": result["evaluate_pct"],
                "create": result["create_pct"],
            }
            for level, (lo, hi) in bt.items():
                actual = bloom_pcts.get(level, 0)
                if actual < lo:
                    gaps.append({
                        "criterion": f"bloom_{level}_target",
                        "severity": "FAIL",
                        "current": f"{actual:.1f}%",
                        "target": f"\u2265{lo}% (proposed range [{lo}%, {hi}%])",
                        "fix_hint": f"{level} is below the proposed minimum of {lo}%. Upsert some skills to raise {level}.",
                    })
                    all_pass = False
                elif actual > hi:
                    gaps.append({
                        "criterion": f"bloom_{level}_target",
                        "severity": "FAIL",
                        "current": f"{actual:.1f}%",
                        "target": f"\u2264{hi}% (proposed range [{lo}%, {hi}%])",
                        "fix_hint": f"{level} is above the proposed maximum of {hi}%. Convert some {level} skills to other levels via upsert_skill.",
                    })
                    all_pass = False
                else:
                    gaps.append({
                        "criterion": f"bloom_{level}_target",
                        "severity": "PASS",
                        "current": f"{actual:.1f}%",
                        "target": f"[{lo}%, {hi}%]",
                    })

            # Size target (WARN only — size is aspirational, not a hard gate)
            sr = proposed.get("size_range")
            if sr and isinstance(sr, list) and len(sr) == 2:
                if result["skills_n"] < sr[0]:
                    gaps.append({
                        "criterion": "size_target",
                        "severity": "WARN",
                        "current": f"{result['skills_n']} skills",
                        "target": f"\u2265{sr[0]} (proposed min)",
                        "fix_hint": f"Tree has {result['skills_n']} skills, below the proposed minimum of {sr[0]}. Consider adding more skills.",
                    })
                elif result["skills_n"] > sr[1]:
                    gaps.append({
                        "criterion": "size_target",
                        "severity": "WARN",
                        "current": f"{result['skills_n']} skills",
                        "target": f"\u2264{sr[1]} (proposed max)",
                        "fix_hint": f"Tree has {result['skills_n']} skills, above the proposed maximum of {sr[1]}. Consider merging or removing skills.",
                    })
                else:
                    gaps.append({
                        "criterion": "size_target",
                        "severity": "PASS",
                        "current": f"{result['skills_n']} skills",
                        "target": f"[{sr[0]}, {sr[1]}]",
                    })
            else:
                gaps.append({
                    "criterion": "size_target",
                    "severity": "PASS",
                    "current": f"{result['skills_n']} skills",
                    "target": "no size target proposed",
                })

            # Max depth (WARN only)
            md = proposed.get("max_depth")
            if md is not None:
                cur_depth = result.get("max_depth", 0)
                if cur_depth > md:
                    gaps.append({
                        "criterion": "depth_target",
                        "severity": "WARN",
                        "current": f"max depth={cur_depth}",
                        "target": f"\u2264{md} (proposed max depth)",
                        "fix_hint": f"Tree depth {cur_depth} exceeds proposed max of {md}. Consider merging shallow branches or reducing over-decomposition.",
                    })
                else:
                    gaps.append({
                        "criterion": "depth_target",
                        "severity": "PASS",
                        "current": f"max depth={cur_depth}",
                        "target": f"\u2264{md}",
                    })
            else:
                gaps.append({
                    "criterion": "depth_target",
                    "severity": "PASS",
                    "current": f"max depth={result.get('max_depth', 0)}",
                    "target": "no depth target proposed",
                })
        else:
            # --- No proposed targets — fall back to hardcoded defaults ---
            # bloom_apply_cap
            if result["apply_pct"] > 35:
                gaps.append({
                    "criterion": "bloom_apply_cap",
                    "severity": "FAIL",
                    "current": f"{result['apply_pct']:.1f}%",
                    "target": "\u226435%",
                    "fix_hint": "Convert apply skills to evaluate/create/understand (distribute across levels \u2014 do NOT convert all to analyze, that triggers bloom_analyze_cap). Re-upsert with the new bloom_level",
                })
                all_pass = False
            else:
                gaps.append({
                    "criterion": "bloom_apply_cap",
                    "severity": "PASS",
                    "current": f"{result['apply_pct']:.1f}%",
                    "target": "\u226435%",
                })

            # bloom_analyze_cap
            if result["analyze_pct"] > 30:
                gaps.append({
                    "criterion": "bloom_analyze_cap",
                    "severity": "FAIL",
                    "current": f"{result['analyze_pct']:.1f}%",
                    "target": "\u226430%",
                    "fix_hint": "Convert analyze skills to evaluate/create/understand via upsert_skill \u2014 distribute across multiple levels, not all to one level",
                })
                all_pass = False
            else:
                gaps.append({
                    "criterion": "bloom_analyze_cap",
                    "severity": "PASS",
                    "current": f"{result['analyze_pct']:.1f}%",
                    "target": "\u226430%",
                })

            # bloom_high_order_floor
            if result["eval_create_pct"] < 20:
                gaps.append({
                    "criterion": "bloom_high_order_floor",
                    "severity": "FAIL",
                    "current": f"{result['eval_create_pct']:.1f}% (evaluate+create)",
                    "target": "\u226520% (evaluate+create)",
                    "fix_hint": "Convert some lower-level skills (remember/understand/apply) to evaluate or create to raise higher-order thinking coverage",
                })
                all_pass = False
            else:
                gaps.append({
                    "criterion": "bloom_high_order_floor",
                    "severity": "PASS",
                    "current": f"{result['eval_create_pct']:.1f}% (evaluate+create)",
                    "target": "\u226520% (evaluate+create)",
                })

            # bloom_no_single_dominance
            if result["any_bloom_max_pct"] > 40:
                gaps.append({
                    "criterion": "bloom_no_single_dominance",
                    "severity": "FAIL",
                    "current": f"max single level={result['any_bloom_max_pct']:.1f}%",
                    "target": "no single Bloom level > 40%",
                    "fix_hint": "Distribute skills more evenly across Bloom levels \u2014 no single level should exceed 40% of all skills",
                })
                all_pass = False
            else:
                gaps.append({
                    "criterion": "bloom_no_single_dominance",
                    "severity": "PASS",
                    "current": f"max single level={result['any_bloom_max_pct']:.1f}%",
                    "target": "no single Bloom level > 40%",
                })

        # proof_query
        if result["proof_pct"] < 100:
            gaps.append({
                "criterion": "proof_query",
                "severity": "FAIL",
                "current": f"{result['proof_pct']:.1f}% non-empty",
                "target": "100%",
                "fix_hint": "For each edge with empty proof_query, re-call add_edge with a non-empty proof_query \u2014 the ON CONFLICT DO UPDATE will set the proof_query",
            })
            all_pass = False
        else:
            gaps.append({
                "criterion": "proof_query",
                "severity": "PASS",
                "current": "100% non-empty",
                "target": "100%",
            })

        # connectivity (orphans + density)
        orphan_count = len(result["orphan_ids"])
        if orphan_count > 0:
            gaps.append({
                "criterion": "connectivity_orphans",
                "severity": "FAIL",
                "current": f"{orphan_count} orphans, {result['ratio']:.2f} ed/skill",
                "target": "0 orphans, \u22651.2 ed/skill min (\u22651.5 ideal)",
                "fix_hint": "Add a prereq edge (add_edge) to each orphan skill in orphan_skills \u2014 connect it to a logical prerequisite",
            })
            all_pass = False
        elif result["ratio"] < 1.2:
            gaps.append({
                "criterion": "connectivity_density",
                "severity": "FAIL",
                "current": f"{result['ratio']:.2f} ed/skill",
                "target": "\u22651.2 ed/skill min (\u22651.5 ideal)",
                "fix_hint": f"Add more prereq edges \u2014 skills should have 2+ prerequisites where logical (convergent structure). Current ratio {result['ratio']:.2f}.",
            })
            all_pass = False
        elif result["ratio"] < 1.5:
            gaps.append({
                "criterion": "connectivity_density",
                "severity": "WARN",
                "current": f"{result['ratio']:.2f} ed/skill",
                "target": "\u22651.2 ed/skill min (\u22651.5 ideal)",
                "fix_hint": "Add more prerequisite edges to increase connectivity",
            })
        else:
            gaps.append({
                "criterion": "connectivity_density",
                "severity": "PASS",
                "current": f"0 orphans, {result['ratio']:.2f} ed/skill",
                "target": "0 orphans, \u22651.2 ed/skill min (\u22651.5 ideal)",
            })

        # acyclic
        if not result["acyclic"]:
            gaps.append({
                "criterion": "acyclic",
                "severity": "FAIL",
                "current": "Cycle detected",
                "target": "Acyclic",
                "fix_hint": "Remove or reverse the edge causing the cycle",
            })
            all_pass = False
        else:
            gaps.append({
                "criterion": "acyclic",
                "severity": "PASS",
                "current": "Acyclic",
                "target": "Acyclic",
            })

        # item_quality (WARN — for evaluator, does not block passed)
        n_lq = len(result["low_quality_item_ids"])
        if n_lq > 0:
            gaps.append({
                "criterion": "item_quality",
                "severity": "WARN",
                "current": f"{n_lq} items with question <20 chars or empty rubric or empty expected_answer",
                "target": "all items have ≥20-char questions + rubrics + expected_answers",
                "fix_hint": "Improve the low-quality items (longer questions, add rubrics, fill expected_answers)",
            })
        else:
            gaps.append({
                "criterion": "item_quality",
                "severity": "PASS",
                "current": "All items meet quality thresholds",
                "target": "all items have ≥20-char questions + rubrics + expected_answers",
            })

        # bloom_balance_overall (WARN — informational for understand/remember distribution, does not block passed)
        if result["understand_pct"] > 40 or result["remember_pct"] > 15:
            gaps.append({
                "criterion": "bloom_balance_overall",
                "severity": "WARN",
                "current": f"understand={result['understand_pct']:.1f}%, remember={result['remember_pct']:.1f}%",
                "target": "understand \u226440%, remember \u226415%",
                "fix_hint": "Rebalance \u2014 some understand/remember skills could be apply/analyze/evaluate",
            })
        else:
            gaps.append({
                "criterion": "bloom_balance_overall",
                "severity": "PASS",
                "current": f"understand={result['understand_pct']:.1f}%, remember={result['remember_pct']:.1f}%",
                "target": "understand \u226440%, remember \u226415%",
            })

        # mastery_seeding_frontier (WARN — seeded skills exist but none ≥0.75)
        seeded = result["seeded_skills"]
        max_seeded = result["max_seeded_p_mastery"]
        if seeded > 0 and max_seeded < 0.75:
            gaps.append({
                "criterion": "mastery_seeding_frontier",
                "severity": "WARN",
                "current": f"{seeded} seeded skills, none \u22650.75 (max={max_seeded:.2f})",
                "target": "at least one seeded skill \u22650.75 (drops from frontier)",
                "fix_hint": "If the learner self-reports knowing any skill well (\u226580%), re-call seed_mastery with prior \u22650.80 for that skill.",
            })
        else:
            gaps.append({
                "criterion": "mastery_seeding_frontier",
                "severity": "PASS",
                "current": f"{seeded} seeded skills, max={max_seeded:.2f}" if seeded > 0 else "no seeded skills",
                "target": "at least one seeded skill \u22650.75 when seeding is used",
            })

        # Summary
        fail_gaps = [g for g in gaps if g["severity"] == "FAIL"]
        if fail_gaps:
            summary = f"FAIL: {len(fail_gaps)} gap(s) \u2014 "
            summary += "; ".join(g["criterion"] for g in fail_gaps)
        else:
            summary = "PASS: all criteria met"

        response: dict = {
            "passed": all_pass,
            "summary": summary,
            "gaps": gaps,
            "counts": {
                "skills": result["skills_n"],
                "edges": result["edges_n"],
                "items": result["items_n"],
                "domains": result["domains_n"],
                "seeded_skills": result["seeded_skills"],
                "max_seeded_p_mastery": round(result["max_seeded_p_mastery"], 2),
            },
        }

        if result["skills_needing_items"]:
            response["skills_needing_items"] = result["skills_needing_items"]
        if result["orphan_ids"]:
            response["orphan_skills"] = result["orphan_ids"]
        if result["apply_skills"]:
            response["apply_skills"] = result["apply_skills"]
        if result["low_quality_item_ids"]:
            response["low_quality_items"] = result["low_quality_item_ids"]
            response["low_quality_skill_ids"] = result["low_quality_skill_ids"]

        return json.dumps(response, ensure_ascii=False)


def _kahn_cycle_check(edges: list[tuple[str, str]]) -> tuple[bool, list[str]]:
    """Return (True, []) if acyclic, else (False, cycle_start_nodes)."""
    from collections import defaultdict

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

    remaining = nodes - set(sorted_nodes)
    cycle_start = next(iter(remaining)) if remaining else "?"
    return False, [cycle_start]
