"""Tests for ReportRepository."""

from cognits.storage.models import Report, new_report_id


def test_save_and_get(reports):
    r = Report(id=new_report_id(), session_id="s1", title="X", content="body")
    reports.save(r)
    result = reports.get(r.id)
    assert result is not None
    assert result.title == "X"
    assert result.content == "body"


def test_get_missing(reports):
    assert reports.get("nonexistent") is None


def test_search_empty(reports):
    result = reports.search(1, 10, "date_asc", "")
    assert result["total"] == 0
    assert result["reports"] == []


def test_search_finds(reports):
    reports.save(Report(id=new_report_id(), session_id="s1", title="Alpha"))
    reports.save(Report(id=new_report_id(), session_id="s1", title="Beta"))
    result = reports.search(1, 10, "title_asc", "")
    assert result["total"] == 2


def test_search_like(reports):
    reports.save(Report(id=new_report_id(), session_id="s1", title="Hello World"))
    reports.save(Report(id=new_report_id(), session_id="s1", title="Bye"))
    result = reports.search(1, 10, "date_asc", "hello")
    assert result["total"] == 1


def test_delete(reports):
    r = Report(id=new_report_id(), session_id="s1", title="X")
    reports.save(r)
    reports.delete(r.id)
    assert reports.get(r.id) is None
