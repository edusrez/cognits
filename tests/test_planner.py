"""Tests for study planner frontier + scoring with alt_prereq (OR) support."""

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
