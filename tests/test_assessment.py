"""Tests for AssessmentItemRepository: CRUD, FTS search, stats, triggers."""

import pytest

from cognits.storage.database import Database
from cognits.storage.models import AssessmentItem, build_fts5_query, new_assessment_item_id


def _make_item(**overrides) -> AssessmentItem:
    defaults = {
        "id": new_assessment_item_id(),
        "skill_id": "k_test123",
        "skill_ids": ["k_test123", "k_test456"],
        "question": "What is the time complexity of quicksort in the worst case?",
        "question_type": "multiple_choice",
        "expected_answer": "O(n^2)",
        "rubric": "Correctly identifies O(n^2) as worst case.",
        "rubric_criteria": [
            {"criterion": "correctness", "weight": 1.0, "description": "Must say O(n^2)"},
        ],
        "rubric_type": "analytic",
        "blooms_level": "remember",
        "difficulty": 0.4,
        "p_value": None,
        "irt_a": None,
        "irt_b": None,
        "irt_c": None,
        "irt_model": "heuristic",
        "generation_model": "deepseek-v4-pro",
        "generation_prompt_hash": "abc123",
        "template_id": "",
        "source": "auto",
        "seed_version": 1,
        "times_presented": 0,
        "times_correct": 0,
        "avg_response_time_ms": None,
        "status": "active",
        "reviewed_by": "",
    }
    defaults.update(overrides)
    return AssessmentItem(**defaults)


class TestAssessmentItemRepo:
    def test_save_and_get_item(self, db):
        from cognits.storage.assessment import AssessmentItemRepository

        repo = AssessmentItemRepository(db)
        item = _make_item()
        repo.save(item)

        got = repo.get(item.id)
        assert got is not None
        assert got.id == item.id
        assert got.skill_id == "k_test123"
        assert got.skill_ids == ["k_test123", "k_test456"]
        assert got.question == item.question
        assert got.question_type == "multiple_choice"
        assert got.expected_answer == "O(n^2)"
        assert got.rubric == item.rubric
        assert len(got.rubric_criteria) == 1
        assert got.rubric_criteria[0]["criterion"] == "correctness"
        assert got.rubric_type == "analytic"
        assert got.blooms_level == "remember"
        assert got.difficulty == 0.4
        assert got.p_value is None
        assert got.irt_model == "heuristic"
        assert got.generation_model == "deepseek-v4-pro"
        assert got.status == "active"
        assert got.times_presented == 0
        assert got.times_correct == 0

    def test_list_for_skill(self, db):
        from cognits.storage.assessment import AssessmentItemRepository

        repo = AssessmentItemRepository(db)
        for i in range(3):
            repo.save(_make_item(skill_id="k_algo"))
        repo.save(_make_item(skill_id="k_other"))

        items = repo.list_for_skill("k_algo")
        assert len(items) == 3

        items_draft = repo.list_for_skill("k_algo", include_all=True)
        assert len(items_draft) == 3

        # Ensure inactive items are excluded by default
        draft = _make_item(skill_id="k_algo", status="draft")
        repo.save(draft)
        active = repo.list_for_skill("k_algo")
        assert len(active) == 3  # draft excluded
        all_items = repo.list_for_skill("k_algo", include_all=True)
        assert len(all_items) == 4  # draft included

    def test_list_for_skills(self, db):
        from cognits.storage.assessment import AssessmentItemRepository

        repo = AssessmentItemRepository(db)
        repo.save(_make_item(skill_id="k_a"))
        repo.save(_make_item(skill_id="k_b"))
        repo.save(_make_item(skill_id="k_a"))

        items = repo.list_for_skills(["k_a", "k_b"])
        assert len(items) == 3

    def test_list_all(self, db):
        from cognits.storage.assessment import AssessmentItemRepository

        repo = AssessmentItemRepository(db)
        repo.save(_make_item(status="active"))
        repo.save(_make_item(status="draft"))

        active = repo.list_all()
        assert len(active) == 1
        assert active[0].status == "active"

        all_items = repo.list_all(include_inactive=True)
        assert len(all_items) == 2

    def test_search_fts(self, db):
        from cognits.storage.assessment import AssessmentItemRepository

        repo = AssessmentItemRepository(db)
        repo.save(_make_item(question="What is a binary search tree?"))
        repo.save(_make_item(question="Explain quicksort partitioning"))
        repo.save(_make_item(question="Graph traversal with BFS"))

        results = repo.search_fts("binary search")
        assert len(results) == 1
        assert "binary search tree" in results[0].question.lower()

        results2 = repo.search_fts("quicksort")
        assert len(results2) == 1
        assert "quicksort" in results2[0].question.lower()

        # Empty query returns nothing
        assert repo.search_fts("") == []

    def test_record_response_updates_stats(self, db):
        from cognits.storage.assessment import AssessmentItemRepository

        repo = AssessmentItemRepository(db)
        item = _make_item()
        repo.save(item)

        # First correct response
        repo.record_response(item.id, correctness=1.0, response_time_ms=5000.0)
        got = repo.get(item.id)
        assert got.times_presented == 1
        assert got.times_correct == 1
        assert got.p_value == 1.0
        assert got.avg_response_time_ms == 5000.0

        # Second incorrect response
        repo.record_response(item.id, correctness=0.0, response_time_ms=3000.0)
        got = repo.get(item.id)
        assert got.times_presented == 2
        assert got.times_correct == 1
        assert got.p_value == 0.5  # 1/2
        # Running mean: (5000 * 1 + 3000) / 2 = 4000
        assert got.avg_response_time_ms == 4000.0

        # Third correct response
        repo.record_response(item.id, correctness=1.0)
        got = repo.get(item.id)
        assert got.times_presented == 3
        assert got.times_correct == 2
        assert got.p_value == pytest.approx(2 / 3, abs=1e-6)

    def test_upsert_not_replace(self, db):
        from cognits.storage.assessment import AssessmentItemRepository

        repo = AssessmentItemRepository(db)
        item = _make_item(question="Original question")
        repo.save(item)

        # Save again with same id but updated question
        item.question = "Updated question"
        repo.save(item)

        # Should still be ONE row
        items = repo.list_for_skill(item.skill_id)
        assert len(items) == 1
        assert items[0].question == "Updated question"

    def test_fts_triggers_sync(self, db):
        from cognits.storage.assessment import AssessmentItemRepository

        repo = AssessmentItemRepository(db)
        item = _make_item(question="What is memoization?")
        repo.save(item)

        # Verify initial FTS
        results = repo.search_fts("memoization")
        assert len(results) == 1

        # Update question
        item.question = "What is dynamic programming with memoization?"
        repo.save(item)

        # Old term should no longer find it (only the new question text is indexed)
        results = repo.search_fts("binary")
        assert len(results) == 0

        # New term should find it
        results2 = repo.search_fts("dynamic programming")
        assert len(results2) == 1

    def test_idempotent_migration(self, tmp_path):
        from cognits.storage.database import Database

        db = Database(tmp_path / "test_migrate.db")
        try:
            # Migration already ran in __init__. Run it again via a second open
            db._migrate()
            # Should not raise
            db._migrate()
        finally:
            db.shutdown()
