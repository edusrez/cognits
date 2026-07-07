"""Tests for skill repository: alt_prereq edges, cycle detection, group_id."""

import pytest

from cognits.storage.database import Database
from cognits.storage.skills import SkillRepository
from cognits.storage.models import Skill, new_skill_id


@pytest.fixture
def repo(tmp_path):
    db = Database(tmp_path / "test.db")
    yield SkillRepository(db)
    db.shutdown()


def _skill(name, domain="d"):
    return Skill(id=new_skill_id(), domain=domain, name=name, description=name)


def test_alt_prereq_cycle_rejected(repo):
    """A alt_prereq B (group g1), B alt_prereq A (group g2) -> add_edge raises ValueError."""
    a = _skill("A"); b = _skill("B")
    repo.upsert(a)
    repo.upsert(b)
    # A -> B (alt_prereq)
    repo.add_edge(b.id, a.id, "alt_prereq", group_id="g1")
    # B -> A (alt_prereq) should be rejected as cycle
    with pytest.raises(ValueError, match="cycle"):
        repo.add_edge(a.id, b.id, "alt_prereq", group_id="g2")


def test_alt_prereq_without_group_id_rejected(repo):
    """add_edge with edge_type='alt_prereq', no group_id -> ValueError."""
    a = _skill("A"); b = _skill("B")
    repo.upsert(a)
    repo.upsert(b)
    with pytest.raises(ValueError, match="alt_prereq requires a non-empty group_id"):
        repo.add_edge(b.id, a.id, "alt_prereq")


def test_alt_prereq_with_empty_group_id_rejected(repo):
    """add_edge with edge_type='alt_prereq', group_id='' -> ValueError."""
    a = _skill("A"); b = _skill("B")
    repo.upsert(a)
    repo.upsert(b)
    with pytest.raises(ValueError, match="alt_prereq requires a non-empty group_id"):
        repo.add_edge(b.id, a.id, "alt_prereq", group_id="")


def test_alt_prereq_prereq_mixed_cycle_rejected(repo):
    """A prereq B, B alt_prereq A (group g1) -> cycle (alt reaches back through prereq chain)."""
    a = _skill("A"); b = _skill("B")
    repo.upsert(a)
    repo.upsert(b)
    repo.add_edge(b.id, a.id, "prereq")  # B prereq A
    with pytest.raises(ValueError, match="cycle"):
        repo.add_edge(a.id, b.id, "alt_prereq", group_id="g1")  # A alt_prereq B


def test_alt_prereq_group_id_stored(repo):
    """group_id is persisted and retrievable."""
    a = _skill("A"); b = _skill("B")
    repo.upsert(a)
    repo.upsert(b)
    repo.add_edge(b.id, a.id, "alt_prereq", group_id="my_group")
    prereqs = repo.get_prerequisites(b.id)
    assert len(prereqs) == 1
    assert prereqs[0].edge_type == "alt_prereq"
    assert prereqs[0].group_id == "my_group"


def test_alt_prereq_group_id_in_tree(repo):
    """get_tree includes group_id in edge serialization."""
    a = _skill("A"); b = _skill("B")
    repo.upsert(a)
    repo.upsert(b)
    repo.add_edge(b.id, a.id, "alt_prereq", group_id="g1")
    tree = repo.get_tree()
    edges = tree["edges"]
    assert len(edges) == 1
    assert edges[0]["edgeType"] == "alt_prereq"
    assert edges[0]["groupId"] == "g1"


def test_alt_prereq_in_walk_topological(repo):
    """walk_topological treats alt_prereq edges as dependencies."""
    a = _skill("A"); b = _skill("B")
    repo.upsert(a)
    repo.upsert(b)
    # b depends on a via alt_prereq
    repo.add_edge(b.id, a.id, "alt_prereq", group_id="g1")
    order = repo.walk_topological()
    ids = [s.id for s in order]
    assert ids.index(a.id) < ids.index(b.id), (
        f"A must come before B in topological order. Got {ids}"
    )
