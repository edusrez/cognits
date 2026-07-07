"""Study Planner — deterministic algorithms for knowledge frontier
detection, skill scoring, and plan generation.

Pure functions over already-loaded data (Skill list, SkillPrereq list,
dict of LearnerState). No DB I/O, no async — the plan_study tool loads
everything via ReportStore and passes it in. This keeps the planner
testable without a database and gives reproducible results.

Algorithm reference: ALEKS outer fringe (Cosyn et al. 2021) + Math
Academy task-selection scoring (Skycak 2026) adapted for project-based
learning with evolving goals.
"""

from __future__ import annotations

from collections import deque
from datetime import datetime, timezone

from cognits.storage.models import LearnerState, Skill, SkillPrereq, StudyPlanItem

# --- constants --------------------------------------------------------

# BKT p_mastery above which a skill is considered mastered.
from cognits.constants import (
    MASTERY_PROFICIENT_P,
    MASTERY_THRESHOLD,
)

# Rolling window: how many items the plan contains by default.
# Math Academy and ALEKS re-evaluate after every session — long plans
# go stale.  7 gives enough visibility without needing frequent rebuilds.
MAX_PLAN_ITEMS: int = 7

# Scoring weights: higher values dominate.
DECAYING_BOOST: float = 10.0        # review urgency (decaying skills)
DECAYING_OVERDUE_MAX: float = 5.0   # bonus for days-overdue of next_review
PATH_RELEVANCE_MAX: float = 5.0     # proximity to user's stated goal
QUICK_WIN_BONUS: float = 2.0        # skills close to mastering (0.70–0.95)
DIFFICULTY_WEIGHT: float = 1.0      # prefer easier skills
BLOOM_WEIGHT: float = 0.5           # prefer lower Bloom levels
USER_PRIORITY_MULTIPLIER: float = 8.0  # explicit user request
SOFT_PREREQ_BONUS: float = 1.0      # all soft prereqs mastered → small boost
MULTI_PATH_BONUS: float = 0.5       # alt_prereq groups satisfied → reduced entropy


def _parse_iso(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s.rstrip().replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


def _now() -> datetime:
    """Pluggable wall-clock — tests can monkeypatch."""
    return datetime.now(timezone.utc)


def _proficient_threshold(skill_id: str, dependent_count: dict[str, int]) -> float:
    """Adaptive threshold: foundational skills (many dependents) need higher
    confidence. Leaf skills with no dependents can use a lower bar."""
    dc = dependent_count.get(skill_id, 0)
    if dc > 3:
        return 0.90
    elif dc == 0:
        return 0.75
    return MASTERY_PROFICIENT_P  # 0.80


# --- frontier ---------------------------------------------------------

def compute_frontier(
    skills: list[Skill],
    edges: list[SkillPrereq],
    states: dict[str, LearnerState],
) -> set[str]:
    """ALEKS outer fringe with AND/OR prerequisite support.

    A skill is in the frontier (ready to learn) iff:
    1. The skill itself is NOT yet mastered.
    2. ALL hard (``prereq``) edges point to mastered skills.
    3. For EACH ``alt_prereq`` group (by ``group_id``), AT LEAST ONE
       edge in the group points to a mastered skill.
       (AND across groups, OR within a group.)

    ``soft_prereq``, ``coreq``, and ``related`` edges do NOT gate
    the frontier — they only influence scoring.

    Uses adaptive proficiency thresholds: skills with many downstream
    dependents require higher confidence (0.90), leaf skills with none
    can use a lower bar (0.75), default is 0.80."""
    # Count how many skills depend on each skill (as hard prereq).
    dependent_count: dict[str, int] = {}
    for e in edges:
        if e.edge_type in ("prereq", "alt_prereq"):
            dependent_count[e.prereq_id] = dependent_count.get(e.prereq_id, 0) + 1

    mastered: set[str] = {
        sid
        for sid, st in states.items()
        if st.p_mastery >= _proficient_threshold(sid, dependent_count)
    }

    # Build per-skill prerequisite structure:
    #   prereqs_by_skill[sid] = {
    #       "hard": set of hard prereq IDs,
    #       "alt_groups": {group_id -> set of prereq IDs},
    #   }
    prereqs_by_skill: dict[str, dict] = {}
    for skill in skills:
        prereqs_by_skill[skill.id] = {"hard": set(), "alt_groups": {}}

    for e in edges:
        if e.edge_type == "prereq":
            prereqs_by_skill.setdefault(e.skill_id, {"hard": set(), "alt_groups": {}})
            prereqs_by_skill[e.skill_id]["hard"].add(e.prereq_id)
        elif e.edge_type == "alt_prereq":
            prereqs_by_skill.setdefault(e.skill_id, {"hard": set(), "alt_groups": {}})
            groups = prereqs_by_skill[e.skill_id]["alt_groups"]
            gid = e.group_id or "__ungrouped__"
            groups.setdefault(gid, set()).add(e.prereq_id)

    frontier: set[str] = set()
    for skill in skills:
        sid = skill.id
        if sid in mastered:
            continue
        prereq_data = prereqs_by_skill.get(sid, {"hard": set(), "alt_groups": {}})
        hard_set: set = prereq_data["hard"]
        alt_groups: dict = prereq_data["alt_groups"]

        # (a) All hard prereqs must be mastered.
        if not hard_set.issubset(mastered):
            continue

        # (b) For each alt_prereq group, at least one prereq must be mastered.
        all_groups_ok = True
        for gid, members in alt_groups.items():
            if not members & mastered:  # intersection empty → no member mastered
                all_groups_ok = False
                break

        if all_groups_ok:
            frontier.add(sid)

    return frontier


# --- goal distances ---------------------------------------------------

def compute_goal_distances(
    edges: list[SkillPrereq],
    goal_name: str,
    skills: list[Skill],
) -> dict[str, int]:
    """BFS backward from the goal skill through ``prereq`` and ``alt_prereq``
    edges. Returns ``{skill_id: distance}`` where distance is the number of
    prerequisite hops to reach the goal. Skills not reaching the goal
    (disconnected subgraph) are absent from the dict."""
    # Resolve goal name → id (name matching is case-insensitive).
    goal_id: str | None = None
    for s in skills:
        if s.name.strip().lower() == goal_name.strip().lower():
            goal_id = s.id
            break
    if goal_id is None:
        return {}

    # Build adjacency from skill_id -> its direct prerequisites (hard + alt).
    adj: dict[str, list[str]] = {}
    for e in edges:
        if e.edge_type in ("prereq", "alt_prereq"):
            adj.setdefault(e.skill_id, []).append(e.prereq_id)

    distances: dict[str, int] = {}
    queue: deque[tuple[str, int]] = deque([(goal_id, 0)])
    while queue:
        node, dist = queue.popleft()
        if node in distances:
            continue
        distances[node] = dist
        for prereq in adj.get(node, []):
            if prereq not in distances:
                queue.append((prereq, dist + 1))
    return distances


# --- scoring ----------------------------------------------------------

def score_skill(
    skill: Skill,
    state: LearnerState | None,
    goal_dist: int | None,
    user_priorities: set[str] | None = None,
    now_iso: str | None = None,
) -> float:
    """Weighted priority score for a skill in the knowledge frontier.
    Higher score → learn sooner."""
    s = 0.0

    # 1. Spaced repetition urgency.
    if state is not None:
        if state.status_enum == "decaying":
            s += DECAYING_BOOST
        if state.next_review and now_iso:
            next_dt = _parse_iso(state.next_review)
            now_dt = _parse_iso(now_iso) or _now()
            if next_dt and next_dt < now_dt:
                days_overdue = (now_dt - next_dt).total_seconds() / 86400.0
                s += min(DECAYING_OVERDUE_MAX, days_overdue * 0.5)

    # 2. Path-to-goal relevance.
    if goal_dist is not None:
        s += PATH_RELEVANCE_MAX / (1.0 + goal_dist)

    # 3. Quick win (close to mastery).
    if state is not None:
        gap = MASTERY_THRESHOLD - state.p_mastery
        if 0.0 < gap <= 0.25:
            s += QUICK_WIN_BONUS * (1.0 - gap / 0.25)

    # 4. Difficulty (easier first).
    s += DIFFICULTY_WEIGHT * (1.0 - max(0.0, min(1.0, skill.difficulty)))

    # 5. Bloom level (lower levels first — clamped to 1..6).
    bloom = max(1, min(6, len(skill.bloom_level) if skill.bloom_level else 3))
    s += BLOOM_WEIGHT * (1.0 - bloom / 6.0)

    # 6. User explicit priorities.
    if user_priorities and skill.id in user_priorities:
        s += USER_PRIORITY_MULTIPLIER

    return s


# --- plan generation --------------------------------------------------

def generate_plan(
    skills: list[Skill],
    edges: list[SkillPrereq],
    states: dict[str, LearnerState],
    goal: str,
    priorities: list[str] | None = None,
    max_items: int = MAX_PLAN_ITEMS,
    now_iso: str | None = None,
) -> list[StudyPlanItem]:
    """Compute frontier, score & rank, produce an ordered StudyPlanItem list."""
    frontier = compute_frontier(skills, edges, states)

    # Score only frontier skills.
    goal_distances = compute_goal_distances(edges, goal, skills)
    priority_set = set(priorities or [])

    # Build lookup for hard prereq sets (used to compute soft_prereq bonus).
    soft_prereqs_by_skill: dict[str, set[str]] = {}
    for e in edges:
        if e.edge_type == "soft_prereq":
            soft_prereqs_by_skill.setdefault(e.skill_id, set()).add(e.prereq_id)

    # Build lookup: which skills have at least one alt_prereq group satisfied?
    # Structure: {skill_id -> True} if ≥1 alt_group is satisfied.
    alt_satisfied: dict[str, bool] = {}
    alt_groups_by_skill: dict[str, dict[str, set[str]]] = {}
    for e in edges:
        if e.edge_type == "alt_prereq":
            gid = e.group_id or "__ungrouped__"
            alt_groups_by_skill.setdefault(e.skill_id, {}).setdefault(gid, set()).add(e.prereq_id)
    for sid, groups in alt_groups_by_skill.items():
        for gid, members in groups.items():
            if any(
                states.get(p) is not None
                and states[p].p_mastery >= MASTERY_THRESHOLD
                for p in members
            ):
                alt_satisfied[sid] = True
                break  # one satisfied group is enough for the bonus

    scored: list[tuple[str, float]] = []
    for sid in frontier:
        skill = next((s for s in skills if s.id == sid), None)
        if skill is None:
            continue
        state = states.get(sid)
        dist = goal_distances.get(sid)
        sc = score_skill(skill, state, dist, priority_set, now_iso)

        # Soft prereq bonus: all soft prereqs mastered?
        soft_set = soft_prereqs_by_skill.get(sid, set())
        if soft_set and all(
            states.get(p) is not None
            and states[p].p_mastery >= MASTERY_THRESHOLD
            for p in soft_set
        ):
            sc += SOFT_PREREQ_BONUS

        # Multi-path bonus: at least one alt_prereq group satisfied
        # (indicates a well-connected concept).
        if alt_satisfied.get(sid):
            sc += MULTI_PATH_BONUS

        scored.append((sid, sc))

    scored.sort(key=lambda x: x[1], reverse=True)
    chosen = scored[:max_items]

    items: list[StudyPlanItem] = []
    for idx, (sid, _) in enumerate(chosen):
        skill = next(s for s in skills if s.id == sid)
        items.append(
            StudyPlanItem(
                skill_id=sid,
                mode="socratic",
                order_index=idx,
            )
        )
    return items


# --- goal-change diff -------------------------------------------------

def diff_plans(
    old_items: list[StudyPlanItem],
    old_goal: str,
    new_goal: str,
    skills: list[Skill],
    edges: list[SkillPrereq],
    states: dict[str, LearnerState],
    now_iso: str | None = None,
) -> dict:
    """Compute structural diff between two goals.

    Returns::

        {
            "preserved": [StudyPlanItem, ...],   # items relevant to both, original order
            "removed":   [StudyPlanItem, ...],   # items only relevant to old goal -> goal_removed
            "added":     [StudyPlanItem, ...],   # new frontier items for new goal
            "merged":    [StudyPlanItem, ...],   # preserved + added, in sensible order
        }

    Items that are removed are NOT mutated — the caller marks them
    ``goal_removed`` before persisting the new plan.
    """
    old_distances = compute_goal_distances(edges, old_goal, skills)
    new_distances = compute_goal_distances(edges, new_goal, skills)

    old_reachable = set(old_distances)  # skills with a path to old_goal
    new_reachable = set(new_distances)  # skills with a path to new_goal

    # Classify old items.
    preserved: list[StudyPlanItem] = []
    removed: list[StudyPlanItem] = []
    for item in old_items:
        if item.skill_id in new_reachable:
            preserved.append(item)
        elif item.skill_id in old_reachable:
            removed.append(item)
        else:
            # Skill was in plan but not reachable from either goal
            # (edge case: plan had stale items not in either goal's
            # subgraph). Remove them.
            removed.append(item)

    # New frontier items for new goal that aren't in any preserved/removed item.
    seen = {i.skill_id for i in preserved} | {i.skill_id for i in removed}
    frontier = compute_frontier(skills, edges, states)
    newly_relevant = frontier & new_reachable - seen

    priority_set: set[str] | None = set()  # no explicit priorities during diff
    added_scored: list[tuple[str, float]] = []
    for sid in newly_relevant:
        skill = next((s for s in skills if s.id == sid), None)
        if skill is None:
            continue
        state = states.get(sid)
        dist = new_distances.get(sid)
        sc = score_skill(skill, state, dist, priority_set, now_iso)
        added_scored.append((sid, sc))

    added_scored.sort(key=lambda x: x[1], reverse=True)
    added = [
        StudyPlanItem(skill_id=sid, order_index=len(preserved) + i)
        for i, (sid, _) in enumerate(added_scored)
    ]

    return {
        "preserved": [i.to_json() for i in preserved],
        "removed": [i.to_json() for i in removed],
        "added": [i.to_json() for i in added],
        "merged": [i.to_json() for i in preserved + added],
    }