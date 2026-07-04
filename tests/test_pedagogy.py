"""Tests for storage/pedagogical.py: PedagogicalPlanRepository."""

from cognits.storage.pedagogical import PedagogicalPlanRepository


def test_save_and_get(pedagogy):
    pedagogy.save("k1", "# Plan\n\n## Stage 1\nIntro")
    result = pedagogy.get("k1")
    assert result is not None
    assert "Stage 1" in result


def test_get_missing(pedagogy):
    assert pedagogy.get("nonexistent") is None


def test_save_overwrites(pedagogy):
    pedagogy.save("k1", "old")
    pedagogy.save("k1", "new")
    assert "new" in pedagogy.get("k1")


def test_save_empty_content(pedagogy):
    pedagogy.save("k2", "")
    result = pedagogy.get("k2")
    assert result is not None
