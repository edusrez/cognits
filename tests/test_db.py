"""Port de internal/storage/db_test.go + smoke FTS5 end-to-end."""

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

    # Actualizar un informe debe reindexar vía triggers (upsert sin REPLACE).
    rid = result["reports"][0]["id"]
    store.save(
        Report(
            id=rid,
            session_id="s1",
            title="Historia de Rust",
            content="Rust nació en Mozilla.",
            summary="Origen de Rust",
        )
    )
    assert store.search_reports_fts(1, 10, "", "python")["total"] == 0
    assert store.search_reports_fts(1, 10, "", "rust")["total"] == 1

    # Borrar también debe salir del índice.
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
        MessageRow(session_id="s1", role="user", content="hola"),
        MessageRow(session_id="s1", role="assistant", content="¿qué tal?", reasoning="pensando"),
    ]
    store.save_messages("s1", msgs)
    store.append_message("s1", MessageRow(session_id="s1", role="user", content="bien"))

    loaded = store.load_messages("s1")
    assert [m.content for m in loaded] == ["hola", "¿qué tal?", "bien"]
    assert loaded[1].reasoning == "pensando"
    assert loaded[0].created_at != ""

    # save_messages reemplaza el historial entero (DELETE+INSERT).
    store.save_messages("s1", msgs[:1])
    assert len(store.load_messages("s1")) == 1

    store.delete_messages_by_session("s1")
    assert store.load_messages("s1") == []


def test_session_config_roundtrip(store):
    from cognits.storage.db import SessionConfigRow

    assert store.load_session_config("nope") is None
    store.save_session_config(
        SessionConfigRow("s1", "deepseek", "deepseek-v4-pro", "max", "orquestador")
    )
    cfg = store.load_session_config("s1")
    assert cfg.to_json() == {
        "sessionId": "s1",
        "provider": "deepseek",
        "model": "deepseek-v4-pro",
        "reasoning": "max",
        "agentId": "orquestador",
    }
