"""HTTP tests for routes_files.py: content (text mode) + raw."""

import asyncio

import httpx


async def _write_test_file(tmp_path, content="hello world"):
    p = tmp_path / "test.txt"
    p.write_text(content)
    return str(p.relative_to(tmp_path)) if p.is_relative_to(tmp_path) else str(p)


def test_file_content_text(real_state, tmp_path):
    state, app = real_state
    rel = asyncio.run(_write_test_file(tmp_path))

    async def go():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
            resp = await client.get(f"/api/files/content?path={rel}")
            assert resp.status_code == 200
            data = resp.json()
            assert data["content"] == "hello world"
    asyncio.run(go())


def test_file_raw(real_state, tmp_path):
    state, app = real_state
    rel = asyncio.run(_write_test_file(tmp_path, "raw content"))

    async def go():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
            resp = await client.get(f"/api/files/raw?path={rel}")
            assert resp.status_code == 200
            assert "raw content" in resp.text
    asyncio.run(go())
