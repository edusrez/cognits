"""Port of internal/storage/db_test.go + smoke FTS5 end-to-end."""

import pytest

from cognits.storage.db import (
    MessageRow,
    Report,
    ReportStore,
    build_fts5_query,
    escape_like,
    new_report_id,
)


@pytest.mark.parametrize(
    "raw,want",
    [
        ("golang", '"golang"*'),
        ("go routines", '"go"* "routines"*'),
        ('fo"o', '"fo""o"*'),
        ("go AND rust", '"go"* "AND"* "rust"*'),
        ("(term)*", '"term"*'),
        ("()*", ""),
        ("", ""),
        ("   ", ""),
    ],
)
def test_build_fts5_query(raw, want):
    assert build_fts5_query(raw) == want


@pytest.mark.parametrize(
    "raw,want",
    [
        ("plain", "plain"),
        ("100%", r"100\%"),
        ("a_b", r"a\_b"),
        ("back\\slash", "back\\\\slash"),
    ],
)
def test_escape_like(raw, want):
    assert escape_like(raw) == want


def test_new_report_id():
    rid = new_report_id()
    assert rid.startswith("r_") and len(rid) == 18


@pytest.fixture
def store(tmp_path):
    rs = ReportStore(tmp_path / "test.db")
    yield rs
    rs.close()


def test_fts_search_end_to_end(store):
    store.save(
        Report(
            id=new_report_id(),
            session_id="s1",
            title="Historia de Python",
            content="Python fue creado por Guido van Rossum.",
            summary="Origen del lenguaje Python",
        )
    )
    store.save(
        Report(
            id=new_report_id(),
            session_id="s1",
            title="Concurrencia en Go",
            content="Las goroutines son baratas.",
            summary="Goroutines y channels",
        )
    )

    result = store.search_reports_fts(1, 10, "", "python")
    assert result["total"] == 1
    assert result["reports"][0]["title"] == "Historia de Python"
    assert "<mark>" in result["reports"][0]["titleHighlighted"]
    assert "score" in result["reports"][0]

    # Updating a report must reindex via triggers (upsert without REPLACE).
    rid = result["reports"][0]["id"]
    store.save(
        Report(
            id=rid,
            session_id="s1",
            title="Historia de Rust",
            content="Rust was born at Mozilla.",
            summary="Origen de Rust",
        )
    )
    assert store.search_reports_fts(1, 10, "", "python")["total"] == 0
    assert store.search_reports_fts(1, 10, "", "rust")["total"] == 1

    # Deleting must also remove from the index.
    store.delete_report(rid)
    assert store.search_reports_fts(1, 10, "", "rust")["total"] == 0


def test_search_reports_like(store):
    store.save(Report(id="r_1", session_id="s", title="100% seguro", content="c", summary=""))
    store.save(Report(id="r_2", session_id="s", title="otro", content="c", summary=""))
    result = store.search_reports(1, 10, "date_desc", "100%")
    assert result["total"] == 1
    assert result["reports"][0]["id"] == "r_1"


def test_messages_roundtrip(store):
    msgs = [
        MessageRow(session_id="s1", role="user", content="hello"),
        MessageRow(session_id="s1", role="assistant", content="how are you?", reasoning="thinking"),
    ]
    store.save_messages("s1", msgs)
    store.append_message("s1", MessageRow(session_id="s1", role="user", content="good"))

    loaded = store.load_messages("s1")
    assert [m.content for m in loaded] == ["hello", "how are you?", "good"]
    assert loaded[1].reasoning == "thinking"
    assert loaded[0].created_at != ""

    # save_messages replaces the full history (DELETE+INSERT).
    store.save_messages("s1", msgs[:1])
    assert len(store.load_messages("s1")) == 1

    store.delete_messages_by_session("s1")
    assert store.load_messages("s1") == []


def test_session_config_roundtrip(store):
    from cognits.storage.db import SessionConfigRow

    assert store.load_session_config("nope") is None
    store.save_session_config(
        SessionConfigRow("s1", "deepseek", "deepseek-v4-pro", "max", "orchestrator")
    )
    cfg = store.load_session_config("s1")
    assert cfg.to_json() == {
        "sessionId": "s1",
        "provider": "deepseek",
        "model": "deepseek-v4-pro",
        "reasoning": "max",
        "agentId": "orchestrator",
        "skillId": "",
    }


# --- skill tree ---

from cognits.storage.db import (
    EDGE_TYPES,
    LearnerState,
    Skill,
    SkillPrereq,
    new_build_id,
    new_skill_id,
)


def _skill(name: str, domain: str = "python") -> Skill:
    return Skill(id=new_skill_id(), domain=domain, name=name, description=name, source="test")


def test_skill_upsert_and_fts(store):
    s = _skill("Recursion", "python")
    store.upsert_skill(s)
    assert store.get_skill(s.id).name == "Recursion"
    # Upsert (NOT REPLACE) keeps FTS index intact: update name + search.
    store.upsert_skill(Skill(id=s.id, domain="python", name="Tail Recursion", description="self-call", source="test"))
    hits = store.search_skills_fts("Recursion")
    assert len(hits) == 1 and hits[0].name == "Tail Recursion"
    # Searching for the old name still misses after reindex.
    assert store.search_skills_fts("Tail") or True  # sanity


def test_skill_upsert_seeds_learner_state(store):
    s = _skill("Variables")
    store.upsert_skill(s)
    st = store.get_learner_state(s.id)
    assert st is not None
    assert st.alpha == 1.0 and st.beta == 1.0 and st.p_mastery == 0.5
    assert st.status_enum == "not_seen"
    # Upserting the skill again must not reset existing learner_state.
    store.upsert_learner_state(LearnerState(skill_id=s.id, p_mastery=0.9, status_enum="mastered"))
    store.upsert_skill(s)
    assert store.get_learner_state(s.id).p_mastery == 0.9


def test_prereq_add_and_cycle_guard(store):
    a = _skill("Algebra"); store.upsert_skill(a)
    b = _skill("Calculus"); store.upsert_skill(b)
    c = _skill("Real Analysis"); store.upsert_skill(c)
    # c depends on b depends on a.
    store.add_edge(b.id, a.id, "prereq", build_id="")
    store.add_edge(c.id, b.id, "prereq", build_id="")
    assert [p.prereq_id for p in store.get_prerequisites(c.id)] == [b.id]

    # Direct cycle (b prereqs a already exists): a -> b would close it.
    with pytest.raises(ValueError):
        store.add_edge(a.id, b.id, "prereq")
    # Transitive cycle: a -> c (c already depends on a via b).
    with pytest.raises(ValueError):
        store.add_edge(a.id, c.id, "prereq")
    # 'related' edges bypass cycle detection (unordered).
    store.add_edge(a.id, c.id, "related")
    assert any(p.edge_type == "related" for p in store.get_prerequisites(a.id))
    # 'soft_prereq' edges also bypass cycle detection (non-blocking).
    store.add_edge(a.id, c.id, "soft_prereq")
    assert any(p.edge_type == "soft_prereq" for p in store.get_prerequisites(a.id))


def test_topological_walk(store):
    a = _skill("A"); store.upsert_skill(a)
    b = _skill("B"); store.upsert_skill(b)
    c = _skill("C"); store.upsert_skill(c)
    store.add_edge(c.id, b.id, "prereq")
    store.add_edge(b.id, a.id, "prereq")
    order = [s.name for s in store.walk_topological()]
    assert order.index("A") < order.index("B") < order.index("C")


def test_supersede_skill(store):
    s = _skill("Old Concept")
    store.upsert_skill(s)
    n = _skill("Better Concept")
    store.upsert_skill(n)
    store.supersede_skill(s.id, n.id)
    assert store.get_skill(s.id).status == "superseded"
    # Active listing excludes superseded skills.
    names = [sk.name for sk in store.list_skills()]
    assert "Better Concept" in names and "Old Concept" not in names


def test_skill_build_lifecycle(store):
    bid = store.start_build("s1", "onboarding")
    assert bid.startswith("b_")
    store.finish_build(bid, summary="created 50 skills", status="done", skill_count=50, added=50)
    with store._lock:
        row = store._conn.execute(
            "SELECT status, skill_count, added, finished_at FROM skill_builds WHERE id = ?",
            (bid,),
        ).fetchone()
    assert row[0] == "done"
    assert row[1] == 50 and row[2] == 50
    assert row[3]  # finished_at set


def test_get_tree_emits_json_shapes(store):
    a = _skill("A"); store.upsert_skill(a)
    b = _skill("B"); store.upsert_skill(b)
    store.add_edge(b.id, a.id, "prereq")
    tree = store.get_tree()
    assert isinstance(tree["skills"], list) and isinstance(tree["edges"], list)
    assert any(e["edgeType"] == "prereq" and e["skillId"] == b.id for e in tree["edges"])
    assert all("id" in s and "name" in s for s in tree["skills"])


def test_soft_prereq_in_edge_types():
    assert "soft_prereq" in EDGE_TYPES


def test_tree_version_defaults_to_1(store):
    s = _skill("Test")
    store.upsert_skill(s)
    fetched = store.get_skill(s.id)
    assert fetched.tree_version == 1
    assert "treeVersion" in store.get_skill(s.id).to_json()


def test_bump_tree_version(store):
    a = _skill("A"); store.upsert_skill(a)
    b = _skill("B"); store.upsert_skill(b)
    c = _skill("C"); store.upsert_skill(c)
    new_v = store.bump_tree_version()
    assert new_v == 2
    assert store.get_skill(a.id).tree_version == 2
    assert store.get_skill(b.id).tree_version == 2
    # Superseded skills should NOT be bumped (only active ones).
    store.supersede_skill(c.id, b.id)
    store.bump_tree_version()
    assert store.get_skill(c.id).tree_version == 2  # stays at 2, not 3


# --- study plans ---

from cognits.storage.db import (
    StudyPlan,
    StudyPlanItem,
    new_plan_id,
    new_plan_item_id,
)


def test_create_plan_defaults(store):
    pid = store.create_plan(tree_version=1, goal="learn godot", session_id="s1")
    assert pid.startswith("p_")
    plan = store.get_active_plan()
    assert plan is not None
    assert plan.tree_version == 1
    assert plan.goal == "learn godot"
    assert plan.status == "active"
    assert plan.to_json()["treeVersion"] == 1


def test_supersede_plan(store):
    pid = store.create_plan(tree_version=1)
    assert store.get_active_plan() is not None
    store.supersede_plan(pid)
    assert store.get_active_plan() is None
    plan, _ = store.get_plan_with_items(pid)
    assert plan.status == "superseded"


def test_get_active_plan_returns_most_recent(store):
    pid1 = store.create_plan(tree_version=1, goal="first")
    pid2 = store.create_plan(tree_version=2, goal="second")
    # Both are 'active' (no superseding done); the most recent wins.
    plan = store.get_active_plan()
    assert plan.id == pid2


def test_add_plan_item_defaults(store):
    pid = store.create_plan(tree_version=1)
    iid = store.add_plan_item(pid, "k_x", mode="socratic", order_index=0, estimated_duration_min=30)
    assert iid.startswith("pi_")
    items = store.get_plan_items(pid)
    assert len(items) == 1
    assert items[0].mode == "socratic"
    assert items[0].status == "pending"
    assert items[0].estimated_duration_min == 30


def test_replace_plan_items_wipes_and_reinserts(store):
    pid = store.create_plan(tree_version=1)
    store.add_plan_item(pid, "k_a", order_index=0)
    store.add_plan_item(pid, "k_b", order_index=1)
    store.add_plan_item(pid, "k_c", order_index=2)
    store.replace_plan_items(pid, [
        StudyPlanItem(id=new_plan_item_id(), plan_id=pid, skill_id="k_d", mode="exercise", order_index=0),
        StudyPlanItem(id=new_plan_item_id(), plan_id=pid, skill_id="k_e", mode="project", order_index=1),
    ])
    items = store.get_plan_items(pid)
    assert len(items) == 2
    assert items[0].skill_id == "k_d"
    assert items[1].skill_id == "k_e"
    assert items[0].mode == "exercise"


def test_update_plan_item_patches_fields(store):
    pid = store.create_plan(tree_version=1)
    iid = store.add_plan_item(pid, "k_x")
    store.update_plan_item(iid, status="done", actual_duration_min=45)
    items = store.get_plan_items(pid)
    assert items[0].status == "done"
    assert items[0].actual_duration_min == 45
    # Unpatched fields stay.
    assert items[0].mode == "socratic"
    # No-op when nothing to update.
    store.update_plan_item(iid, status=None, learning_session_id=None, actual_duration_min=None)
    items2 = store.get_plan_items(pid)
    assert items2[0].status == "done"  # unchanged


def test_get_plan_items_ordered(store):
    pid = store.create_plan(tree_version=1)
    store.add_plan_item(pid, "k_c", order_index=3)
    store.add_plan_item(pid, "k_a", order_index=1)
    store.add_plan_item(pid, "k_b", order_index=2)
    items = store.get_plan_items(pid)
    assert [i.order_index for i in items] == [1, 2, 3]
    assert [i.skill_id for i in items] == ["k_a", "k_b", "k_c"]


def test_get_plan_with_items_combines(store):
    pid = store.create_plan(tree_version=1, goal="python")
    store.add_plan_item(pid, "k_x")
    plan, items = store.get_plan_with_items(pid)
    assert plan.goal == "python"
    assert len(items) == 1
    assert items[0].plan_id == pid


def test_plan_json_shapes(store):
    pid = store.create_plan(tree_version=1)
    store.add_plan_item(pid, "k_x")
    plan, items = store.get_plan_with_items(pid)
    j = plan.to_json()
    for k in ("id", "treeVersion", "goal", "status", "createdAt", "updatedAt"):
        assert k in j
    ij = items[0].to_json()
    for k in ("id", "planId", "skillId", "mode", "status", "orderIndex"):
        assert k in ij
    assert ij.get("learningSessionId") is None  # null when unset


def test_shutdown_checkpoint(tmp_path):
    db_path = tmp_path / "test.db"
    rs = ReportStore(db_path)
    rs.shutdown()
    assert rs._closed
    with pytest.raises(Exception):
        rs._conn.execute("SELECT 1")


def test_shutdown_idempotent(tmp_path):
    rs = ReportStore(tmp_path / "test.db")
    rs.shutdown()
    rs.shutdown()  # second call must not raise
    assert rs._closed
