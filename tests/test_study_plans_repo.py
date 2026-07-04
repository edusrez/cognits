"""Tests for StudyPlanRepository: plans + items lifecycle."""

from cognits.storage.models import StudyPlanItem


def test_create_and_get_active(study_plans):
    pid = study_plans.create(1, "learn python", "s1")
    plan = study_plans.get_active()
    assert plan is not None
    assert plan.id == pid
    assert plan.goal == "learn python"


def test_supersede(study_plans):
    pid = study_plans.create(1, "goal1")
    study_plans.supersede(pid)
    active = study_plans.get_active()
    assert active is None or active.id != pid


def test_add_and_get_items(study_plans):
    pid = study_plans.create(1, "goal")
    study_plans.add_item(pid, "k1", "socratic", 0)
    study_plans.add_item(pid, "k2", "exercise", 1)
    items = study_plans.get_items(pid)
    assert len(items) == 2
    assert items[0].skill_id == "k1"


def test_replace_items(study_plans):
    pid = study_plans.create(1, "goal")
    study_plans.add_item(pid, "k1", "socratic", 0)
    study_plans.replace_items(pid, [
        StudyPlanItem(skill_id="k2", mode="exercise", order_index=0),
        StudyPlanItem(skill_id="k3", mode="project", order_index=1),
    ])
    items = study_plans.get_items(pid)
    assert len(items) == 2
    assert items[0].skill_id == "k2"
    assert items[1].skill_id == "k3"


def test_update_item(study_plans):
    pid = study_plans.create(1, "goal")
    iid = study_plans.add_item(pid, "k1", "socratic", 0)
    study_plans.update_item(iid, status="done", actual_duration_min=45)
    items = study_plans.get_items(pid)
    assert items[0].status == "done"
    assert items[0].actual_duration_min == 45


def test_get_with_items(study_plans):
    pid = study_plans.create(1, "goal")
    study_plans.add_item(pid, "k1")
    plan, items = study_plans.get_with_items(pid)
    assert plan is not None
    assert len(items) == 1
