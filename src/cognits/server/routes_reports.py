"""Port of internal/server/reports.go."""

from __future__ import annotations

import asyncio

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

from cognits.server.exceptions import NotFoundError, StorageError
from cognits.server.util import atoi


def register(app: FastAPI, st) -> None:
    @app.get("/api/reports/{report_id}")
    async def get_report(report_id: str):
        if st.db is None:
            raise StorageError("reports not available")

        try:
            report = await asyncio.to_thread(st.reports.get, report_id)
        except Exception:
            report = None
        if report is None:
            raise NotFoundError("report not found")

        return JSONResponse(report.to_json())

    @app.get("/api/reports")
    async def list_reports(request: Request):
        if st.db is None:
            raise StorageError("reports not available")

        q = request.query_params
        page = max(atoi(q.get("page")), 1)
        limit = atoi(q.get("limit"))
        sort = q.get("sort") or "date_desc"
        search = q.get("search") or ""

        try:
            if search:
                result = await asyncio.to_thread(
                    st.reports.search_fts, page, limit, sort, search
                )
            else:
                result = await asyncio.to_thread(
                    st.reports.search, page, limit, sort, search
                )
        except Exception as e:
            raise StorageError(str(e))

        return JSONResponse(result)

    @app.delete("/api/reports/{report_id}")
    async def delete_report(report_id: str):
        if st.db is None:
            raise StorageError("reports not available")

        try:
            await asyncio.to_thread(st.reports.delete, report_id)
        except Exception as e:
            raise StorageError(str(e))

        return Response(status_code=204)
