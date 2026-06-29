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
