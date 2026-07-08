"""Tests for study planner frontier + scoring with alt_prereq (OR) support."""

import datetime

from cognits.learner import planner as P
from cognits.storage.models import LearnerState, Skill, SkillPrereq, new_skill_id


# --- helpers ------------------------------------------------------------

def _skill(name, domain="d", difficulty=0.5):
    return Skill(id=new_skill_id(), domain=domain, name=name, description=name, difficulty=difficulty)


def _prereq(skill_id, prereq_id, edge_type="prereq", group_id=""):
    return SkillPrereq(skill_id=skill_id, prereq_id=prereq_id, edge_type=edge_type, group_id=group_id)


def _state(skill_id, p=0.5, status="not_seen", next_review=None):
    return LearnerState(skill_id=skill_id, p_mastery=p, status_enum=status, next_review=next_review)


# --- alt_prereq frontier (OR groups) ------------------------------------

def test_alt_prereq_group_satisfied_when_one_mastered():
    """S has alt_prereq group g1=[A, B]. A mastered, B not. -> S in frontier."""
    a = _skill("A"); b = _skill("B"); s = _skill("S")
    e1 = _prereq(s.id, a.id, "alt_prereq", "g1")
    e2 = _prereq(s.id, b.id, "alt_prereq", "g1")
    st = {a.id: _state(a.id, p=0.95), b.id: _state(b.id, p=0.30), s.id: _state(s.id, p=0.30)}
    frontier = P.compute_frontier([a, b, s], [e1, e2], st)
    assert a.id not in frontier  # mastered
    assert s.id in frontier      # group g1 satisfied via A
    assert b.id in frontier      # no prereqs, not mastered


def test_alt_prereq_group_unsatisfied_when_none_mastered():
    """Group g1=[A, B], neither mastered. -> S NOT in frontier."""
    a = _skill("A"); b = _skill("B"); s = _skill("S")
    e1 = _prereq(s.id, a.id, "alt_prereq", "g1")
    e2 = _prereq(s.id, b.id, "alt_prereq", "g1")
    st = {a.id: _state(a.id, p=0.30), b.id: _state(b.id, p=0.30), s.id: _state(s.id, p=0.30)}
    frontier = P.compute_frontier([a, b, s], [e1, e2], st)
    assert s.id not in frontier  # no member of g1 mastered
    assert a.id in frontier      # root, no prereqs
    assert b.id in frontier


def test_multiple_alt_groups_all_must_be_satisfied():
    """S has g1=[A,B] (A mastered) + g2=[C,D] (neither). -> S NOT in frontier."""
    a = _skill("A"); b = _skill("B"); c = _skill("C"); d = _skill("D"); s = _skill("S")
    e1 = _prereq(s.id, a.id, "alt_prereq", "g1")
    e2 = _prereq(s.id, b.id, "alt_prereq", "g1")
    e3 = _prereq(s.id, c.id, "alt_prereq", "g2")
    e4 = _prereq(s.id, d.id, "alt_prereq", "g2")
    st = {
        a.id: _state(a.id, p=0.95),
        b.id: _state(b.id, p=0.30),
        c.id: _state(c.id, p=0.30),
        d.id: _state(d.id, p=0.30),
        s.id: _state(s.id, p=0.30),
    }
    frontier = P.compute_frontier([a, b, c, d, s], [e1, e2, e3, e4], st)
    assert s.id not in frontier  # g2 unsatisfied


def test_multiple_alt_groups_all_satisfied():
    """S has g1=[A,B] (A mastered) + g2=[C,D] (C mastered). -> S in frontier."""
    a = _skill("A"); b = _skill("B"); c = _skill("C"); d = _skill("D"); s = _skill("S")
    e1 = _prereq(s.id, a.id, "alt_prereq", "g1")
    e2 = _prereq(s.id, b.id, "alt_prereq", "g1")
    e3 = _prereq(s.id, c.id, "alt_prereq", "g2")
    e4 = _prereq(s.id, d.id, "alt_prereq", "g2")
    st = {
        a.id: _state(a.id, p=0.95),
        b.id: _state(b.id, p=0.30),
        c.id: _state(c.id, p=0.95),
        d.id: _state(d.id, p=0.30),
        s.id: _state(s.id, p=0.30),
    }
    frontier = P.compute_frontier([a, b, c, d, s], [e1, e2, e3, e4], st)
    assert s.id in frontier


def test_hard_prereq_and_alt_combined():
    """S has hard prereq X (mastered) + alt group g1=[A,B] (A mastered). S in frontier."""
    x = _skill("X"); a = _skill("A"); b = _skill("B"); s = _skill("S")
    e_hard = _prereq(s.id, x.id, "prereq")
    e_alt1 = _prereq(s.id, a.id, "alt_prereq", "g1")
    e_alt2 = _prereq(s.id, b.id, "alt_prereq", "g1")
    st = {
        x.id: _state(x.id, p=0.95),
        a.id: _state(a.id, p=0.95),
        b.id: _state(b.id, p=0.30),
        s.id: _state(s.id, p=0.30),
    }
    frontier = P.compute_frontier([x, a, b, s], [e_hard, e_alt1, e_alt2], st)
    assert s.id in frontier  # hard OK + alt OK


def test_hard_prereq_and_alt_combined_hard_fails():
    """S has hard prereq X (NOT mastered) + alt group g1=[A,B] (A mastered).
    S NOT in frontier because hard gate fails."""
    x = _skill("X"); a = _skill("A"); b = _skill("B"); s = _skill("S")
    e_hard = _prereq(s.id, x.id, "prereq")
    e_alt1 = _prereq(s.id, a.id, "alt_prereq", "g1")
    e_alt2 = _prereq(s.id, b.id, "alt_prereq", "g1")
    st = {
        x.id: _state(x.id, p=0.30),
        a.id: _state(a.id, p=0.95),
        b.id: _state(b.id, p=0.30),
        s.id: _state(s.id, p=0.30),
    }
    frontier = P.compute_frontier([x, a, b, s], [e_hard, e_alt1, e_alt2], st)
    assert s.id not in frontier  # hard gate blocks


# --- goal distances with alt_prereq -----------------------------------

def test_goal_distance_traverses_alt_prereq():
    """BFS reaches a skill via alt_prereq edge."""
    a = _skill("A"); b = _skill("B"); c = _skill("C")
    e1 = _prereq(b.id, a.id, "alt_prereq", "g1")
    e2 = _prereq(c.id, b.id, "prereq")
    dists = P.compute_goal_distances([e1, e2], "C", [a, b, c])
    assert dists == {c.id: 0, b.id: 1, a.id: 2}


def test_goal_distance_soft_prereq_not_traversed():
    """BFS does NOT traverse soft_prereq edges."""
    a = _skill("A"); b = _skill("B"); c = _skill("C")
    e1 = _prereq(b.id, a.id, "soft_prereq")
    e2 = _prereq(c.id, b.id, "prereq")
    dists = P.compute_goal_distances([e1, e2], "C", [a, b, c])
    assert a.id not in dists  # soft_prereq not a gate edge


# --- multi-path bonus -------------------------------------------------

def test_multi_path_bonus():
    """A skill with a satisfied alt group scores higher than without."""
    a = _skill("A"); b = _skill("B"); s1 = _skill("S1"); s2 = _skill("S2")
    # s1: no alt prereqs
    # s2: alt_prereq group g1=[A] where A is mastered
    e = _prereq(s2.id, a.id, "alt_prereq", "g1")
    st = {
        a.id: _state(a.id, p=0.95),
        b.id: _state(b.id, p=0.30),
        s1.id: _state(s1.id, p=0.30),
        s2.id: _state(s2.id, p=0.30),
    }
    # Both s1 and s2 are roots, same difficulty, same state.
    # Use generate_plan to score them.
    items = P.generate_plan([a, b, s1, s2], [e], st, goal="B", max_items=10)
    s1_idx = next(i for i, it in enumerate(items) if it.skill_id == s1.id)
    s2_idx = next(i for i, it in enumerate(items) if it.skill_id == s2.id)
    # s2 should rank before s1 due to multi-path bonus.
    assert s2_idx < s1_idx, (
        f"s2 (with alt bonus) should rank before s1. "
        f"Got s2_idx={s2_idx}, s1_idx={s1_idx}"
    )


# --- bloom hierarchy (BLOOM_RANK) -------------------------------------

def test_bloom_hierarchy_respected():
    """A skill with bloom_level='understand' (rank 2) should score HIGHER
    (lower bloom = preferred) than one with bloom_level='create' (rank 6)."""
    s_low = _skill("LowBloom", difficulty=0.5)
    s_low.bloom_level = "understand"
    s_high = _skill("HighBloom", difficulty=0.5)
    s_high.bloom_level = "create"
    # Same state → difference driven solely by bloom.
    st = {
        s_low.id: _state(s_low.id, p=0.3),
        s_high.id: _state(s_high.id, p=0.3),
    }
    score_low = P.score_skill(s_low, st[s_low.id], goal_dist=0)
    score_high = P.score_skill(s_high, st[s_high.id], goal_dist=0)
    assert score_low > score_high, (
        f"understand (rank 2) should outscore create (rank 6). "
        f"Got low={score_low:.4f}, high={score_high:.4f}"
    )


def test_bloom_unknown_defaults_to_apply():
    """Empty or unknown bloom_level → rank 3 (apply)."""
    s_empty = _skill("NoBloom", difficulty=0.5)
    s_empty.bloom_level = ""
    s_known = _skill("Apply", difficulty=0.5)
    s_known.bloom_level = "apply"
    st = {
        s_empty.id: _state(s_empty.id, p=0.3),
        s_known.id: _state(s_known.id, p=0.3),
    }
    score_empty = P.score_skill(s_empty, st[s_empty.id], goal_dist=0)
    score_known = P.score_skill(s_known, st[s_known.id], goal_dist=0)
    assert abs(score_empty - score_known) < 1e-9, (
        f"empty bloom should score same as apply (rank 3). "
        f"Got empty={score_empty:.4f}, known={score_known:.4f}"
    )


def test_bloom_multiword_takes_first():
    """bloom_level='apply (hands-on)' → first word 'apply' → rank 3."""
    s_multi = _skill("MultiBloom", difficulty=0.5)
    s_multi.bloom_level = "apply (hands-on)"
    s_single = _skill("SingleBloom", difficulty=0.5)
    s_single.bloom_level = "apply"
    st = {
        s_multi.id: _state(s_multi.id, p=0.3),
        s_single.id: _state(s_single.id, p=0.3),
    }
    score_multi = P.score_skill(s_multi, st[s_multi.id], goal_dist=0)
    score_single = P.score_skill(s_single, st[s_single.id], goal_dist=0)
    assert abs(score_multi - score_single) < 1e-9, (
        f"multiword 'apply (hands-on)' should score same as 'apply'. "
        f"Got multi={score_multi:.4f}, single={score_single:.4f}"
    )


def test_multi_path_bonus_only_when_alt_satisfied():
    """Skill with alt group but no master -> blocked from frontier (gate not satisfied)."""
    a = _skill("A"); s1 = _skill("S1"); s2 = _skill("S2")
    # s1: no alt prereqs
    # s2: alt_prereq group g1=[A] but A is NOT mastered -> s2 blocked
    e = _prereq(s2.id, a.id, "alt_prereq", "g1")
    st = {
        a.id: _state(a.id, p=0.30),
        s1.id: _state(s1.id, p=0.30),
        s2.id: _state(s2.id, p=0.30),
    }
    items = P.generate_plan([a, s1, s2], [e], st, goal="A", max_items=10)
    item_ids = {it.skill_id for it in items}
    assert s1.id in item_ids    # root, no prereqs -> in frontier
    assert a.id in item_ids     # root, no prereqs -> in frontier
    assert s2.id not in item_ids  # blocked: alt_prereq group unsatisfied


# --- T8: fuzzy goal match ----------------------------------------------

def test_fuzzy_goal_substring():
    """Goal 'twin-stick' matches 'Twin-Stick Controls: Decoupled Move and Aim' via substring."""
    a = _skill("Twin-Stick Controls: Decoupled Move and Aim")
    b = _skill("B")
    e = _prereq(b.id, a.id, "prereq")
    dists = P.compute_goal_distances([e], "twin-stick", [a, b])
    # a is the goal match (distance 0); b depends on a via prereq, so b is NOT
    # reachable backward from a (BFS starts at the goal, goes to its prereqs).
    assert a.id in dists
    assert dists[a.id] == 0


def test_fuzzy_goal_levenshtein():
    """Goal 'dogenkeep' matches 'Dungeon Keeper' via difflib (Levenshtein distance ≤2)."""
    dk = _skill("Dungeon Keeper")
    dists = P.compute_goal_distances([], "dogenkeep", [dk])
    # dk is the goal itself (no edges → only the goal skill appears with distance 0)
    assert dk.id in dists


def test_fuzzy_goal_no_match():
    """Goal 'xyzzy' matches nothing → returns {} and logs a warning."""
    a = _skill("A")
    dists = P.compute_goal_distances([], "xyzzy", [a])
    assert dists == {}


# --- T9: estimated_duration_min ----------------------------------------

def test_estimate_duration():
    """_estimate_duration produces expected ranges for different difficulty/Bloom combos."""
    # difficulty 0, remember (rank 1) → base=15, mult=0.7 → 10.5→10
    assert P._estimate_duration(0.0, "remember") == 10
    # difficulty 1, apply (rank 3) → base=60, mult=1.0 → 60.0→60
    assert P._estimate_duration(1.0, "apply") == 60
    # difficulty 0.5, create (rank 6) → base=37.5, mult=1.5 → 56.25→55
    assert P._estimate_duration(0.5, "create") == 55
    # difficulty 0.3, understand (rank 2) → base=28.5, mult=0.7 → 19.95→20
    assert P._estimate_duration(0.3, "understand") == 20
    # difficulty 0.8, evaluate (rank 5) → base=51, mult=1.3 → 66.3→65
    assert P._estimate_duration(0.8, "evaluate") == 65
    # all results are multiples of 5
    for d in [0.0, 0.25, 0.5, 0.75, 1.0]:
        for bl in ["remember", "understand", "apply", "analyze", "evaluate", "create"]:
            dur = P._estimate_duration(d, bl)
            assert dur % 5 == 0, f"duration {dur} not multiple of 5 for d={d}, bl={bl}"
            assert 5 <= dur <= 90, f"duration {dur} out of range for d={d}, bl={bl}"


def test_plan_items_have_duration():
    """generate_plan produces items with estimated_duration_min > 0."""
    a = _skill("A", difficulty=0.5)
    a.bloom_level = "apply"
    b = _skill("B", difficulty=0.8)
    b.bloom_level = "create"
    c = _skill("C", difficulty=0.2)
    c.bloom_level = "remember"
    states = {a.id: _state(a.id, p=0.3), b.id: _state(b.id, p=0.3), c.id: _state(c.id, p=0.3)}
    items = P.generate_plan([a, b, c], [], states, goal="A", max_items=10)
    for item in items:
        assert item.estimated_duration_min is not None, f"item {item.skill_id} has no duration"
        assert item.estimated_duration_min > 0, f"item {item.skill_id} duration is {item.estimated_duration_min}"
    # Verify diff_plans added items also have duration
    old_items = [P.StudyPlanItem(skill_id=a.id, order_index=0)]
    diff = P.diff_plans(old_items, "A", "B", [a, b, c], [], states)
    added_json = diff["added"]
    for item_json in added_json:
        assert "estimatedDurationMin" in item_json
        assert item_json["estimatedDurationMin"] is not None
        assert item_json["estimatedDurationMin"] > 0


# --- T11: scoring weights + adaptive threshold + ZPD -------------------

def test_proficient_threshold_smooth():
    """Smooth threshold: 0 deps→0.75, 1 dep→0.79, 5 deps→0.95, 10 deps→0.95 (capped)."""
    assert P._proficient_threshold("any", {}) == 0.75
    assert P._proficient_threshold("any", {"any": 1}) == 0.79
    assert P._proficient_threshold("any", {"any": 5}) == 0.95
    assert P._proficient_threshold("any", {"any": 10}) == 0.95  # capped


def test_zpd_bonus():
    """Skill with p_mastery=0.5 scores higher than same skill with p=0.3 or p=0.8
    (ZPD bonus 1.5 is active in 0.4-0.69, no overlap with quick-win at 0.70+)."""
    sk = _skill("ZPD_skill", difficulty=0.5)
    # Three states: below ZPD, in ZPD, above ZPD (with weak quick-win)
    st_low = _state(sk.id, p=0.3)
    st_zpd = _state(sk.id, p=0.5)
    st_high = _state(sk.id, p=0.8)
    score_low = P.score_skill(sk, st_low, goal_dist=0)
    score_zpd = P.score_skill(sk, st_zpd, goal_dist=0)
    score_high = P.score_skill(sk, st_high, goal_dist=0)
    # ZPD gets the +1.5 bonus that others don't.
    assert score_zpd > score_low, f"ZPD (0.5) should score higher than low (0.3): {score_zpd:.4f} vs {score_low:.4f}"
    assert score_zpd > score_high, f"ZPD (0.5) should score higher than high (0.8): {score_zpd:.4f} vs {score_high:.4f}"
    # Verify boundary: 0.4 gets bonus, 0.399 doesn't; 0.69 gets bonus, 0.70 gets no ZPD (only quick-win which is 0 at boundary)
    st_edge_low_in = _state(sk.id, p=0.4)
    st_edge_low_out = _state(sk.id, p=0.399)
    st_edge_high_in = _state(sk.id, p=0.69)
    st_edge_high_out = _state(sk.id, p=0.70)
    assert P.score_skill(sk, st_edge_low_in, goal_dist=0) > P.score_skill(sk, st_edge_low_out, goal_dist=0)
    assert P.score_skill(sk, st_edge_high_in, goal_dist=0) > P.score_skill(sk, st_edge_high_out, goal_dist=0)


def test_reduced_priority_multiplier():
    """User priority still boosts but doesn't dominate: multiplier is 3.0 not 8.0."""
    assert P.USER_PRIORITY_MULTIPLIER == 3.0
    sk = _skill("P_skill", difficulty=0.5)
    st = _state(sk.id, p=0.3)
    score_no_priority = P.score_skill(sk, st, goal_dist=0)
    score_with_priority = P.score_skill(sk, st, goal_dist=0, user_priorities={sk.id})
    diff = score_with_priority - score_no_priority
    assert diff == P.USER_PRIORITY_MULTIPLIER
    # The boost shouldn't dominate all scoring dimensions.
    assert diff < score_no_priority + 8.0  # old multiplier would have been >8


# --- M2: R-based classification ---------------------------------------

def _make_iso(dt: datetime.datetime) -> str:
    return dt.astimezone(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def test_classify_item_r_based_review():
    """Skill with stability=5, last_review=10 days ago → R < 0.9 → 'review'."""
    from cognits.agent.tool_study_plan import classify_item

    now = datetime.datetime(2026, 7, 10, 0, 0, 0, tzinfo=datetime.timezone.utc)
    last = now - datetime.timedelta(days=10)
    state = LearnerState(
        skill_id="k_r_tiny",
        stability=5.0,
        last_review=_make_iso(last),
        reps=2,
        p_mastery=0.70,
        alpha=5.0,
        beta=2.0,
    )
    states = {state.skill_id: state}
    result = classify_item(state.skill_id, states, now)
    assert result == "review", f"Expected 'review' but got '{result}'"


def test_classify_item_r_based_new():
    """Skill with stability=30, last_review=1 day ago → R > 0.9 → 'new'."""
    from cognits.agent.tool_study_plan import classify_item

    now = datetime.datetime(2026, 7, 10, 0, 0, 0, tzinfo=datetime.timezone.utc)
    last = now - datetime.timedelta(days=1)
    state = LearnerState(
        skill_id="k_r_healthy",
        stability=30.0,
        last_review=_make_iso(last),
        reps=5,
        p_mastery=0.85,
        alpha=10.0,
        beta=2.0,
    )
    states = {state.skill_id: state}
    result = classify_item(state.skill_id, states, now)
    assert result == "new", f"Expected 'new' but got '{result}'"


def test_classify_item_fallback_next_review():
    """Skill without stability but with next_review in the past → 'review' (fallback)."""
    from cognits.agent.tool_study_plan import classify_item

    now = datetime.datetime(2026, 7, 10, 0, 0, 0, tzinfo=datetime.timezone.utc)
    state = LearnerState(
        skill_id="k_legacy",
        next_review="2026-07-01T00:00:00Z",
        reps=3,
        p_mastery=0.70,
        alpha=5.0,
        beta=2.0,
    )
    states = {state.skill_id: state}
    result = classify_item(state.skill_id, states, now)
    assert result == "review", f"Expected 'review' via next_review fallback, got '{result}'"


def test_classify_item_skip_seeded_known():
    """p_mastery ≥ MASTERY_THRESHOLD, no last_review → 'skip'."""
    from cognits.agent.tool_study_plan import classify_item

    now = datetime.datetime(2026, 7, 10, 0, 0, 0, tzinfo=datetime.timezone.utc)
    state = LearnerState(
        skill_id="k_seeded",
        p_mastery=0.99,
        alpha=198.0,
        beta=2.0,
        reps=1,  # seeded-only, never reviewed
        status_enum="mastered",
    )
    states = {state.skill_id: state}
    result = classify_item(state.skill_id, states, now)
    assert result == "skip", f"Expected 'skip' for seeded-known skill, got '{result}'"
