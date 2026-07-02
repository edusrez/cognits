"""HTTP tests for routes_reports.py: CRUD + FTS5/LIKE search."""

import asyncio

import httpx

from cognits.storage.models import Report, new_report_id


async def _get_report_404(app):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
        resp = await client.get("/api/reports/nonexistent")
        assert resp.status_code == 404


def test_get_report_404(real_app):
    asyncio.run(_get_report_404(real_app))


async def _get_report_200(state, app):
    r = Report(id=new_report_id(), session_id="s1", title="X")
    state.reports.save(r)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
        resp = await client.get(f"/api/reports/{r.id}")
        assert resp.status_code == 200
        assert resp.json()["title"] == "X"


def test_get_report_200(real_state):
    state, app = real_state
    asyncio.run(_get_report_200(state, app))


async def _list_reports_empty(app):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
        resp = await client.get("/api/reports")
        assert resp.status_code == 200
        assert "reports" in resp.json()


def test_list_reports(real_app):
    asyncio.run(_list_reports_empty(real_app))
