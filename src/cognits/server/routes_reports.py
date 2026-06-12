"""Port of internal/server/reports.go."""

from __future__ import annotations

import asyncio

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

from cognits.server.util import atoi, text_error


def register(app: FastAPI, st) -> None:
    @app.get("/api/reports/{report_id}")
    async def get_report(report_id: str):
        if st.report_store is None:
            return text_error("reports not available", 500)

        try:
            report = await asyncio.to_thread(st.report_store.get, report_id)
        except Exception:
            report = None
        if report is None:
            return text_error("report not found", 404)

        return JSONResponse(report.to_json())

    @app.get("/api/reports")
    async def list_reports(request: Request):
        if st.report_store is None:
            return text_error("reports not available", 500)

        q = request.query_params
        page = max(atoi(q.get("page")), 1)
        limit = atoi(q.get("limit"))
        sort = q.get("sort") or "date_desc"
        search = q.get("search") or ""

        try:
            if search:
                result = await asyncio.to_thread(
                    st.report_store.search_reports_fts, page, limit, sort, search
                )
            else:
                result = await asyncio.to_thread(
                    st.report_store.search_reports, page, limit, sort, search
                )
        except Exception as e:
            return text_error(str(e), 500)

        return JSONResponse(result)

    @app.delete("/api/reports/{report_id}")
    async def delete_report(report_id: str):
        if st.report_store is None:
            return text_error("reports not available", 500)

        try:
            await asyncio.to_thread(st.report_store.delete_report, report_id)
        except Exception as e:
            return text_error(str(e), 500)

        return Response(status_code=204)
