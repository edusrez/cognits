"""Tests for RAG engine cache redirect on 9p/DrvFs filesystems."""

from __future__ import annotations

import asyncio
import multiprocessing
import os
import threading
from pathlib import Path
from unittest.mock import patch

import pytest

from cognits.rag.engine import RagEngine


@pytest.fixture
def engine():
    return RagEngine()


def test_cache_redirect_to_tmp_when_on_9p(tmp_path, engine, monkeypatch):
    """When the cache dir is on a 9p filesystem, _load() redirects to /tmp."""
    ninep_dir = tmp_path / "mnt_c_home" / ".cache" / "fastembed"
    ninep_dir.mkdir(parents=True)
    monkeypatch.setenv("FASTEMBED_CACHE_DIR", str(ninep_dir))

    # Add a fake mount entry so the tmp_path's parent is detected as 9p
    fake_mounts = (
        "C:\\ /mnt/c 9p rw,noatime,dirsync 0 0\n"
        f"drvfs {str(tmp_path)} 9p rw,noatime 0 0\n"
    )
    monkeypatch.setattr(
        "cognits.storage.fsdetect._read_proc_mounts",
        lambda: fake_mounts,
    )

    def _run_load():
        engine._load()

    # Avoid spawning a real subprocess — replace Process.start with a no-op
    with patch.object(multiprocessing.Process, "start", lambda self: None):
        t = threading.Thread(target=_run_load)
        t.start()
        t.join(timeout=5)

    redirected = os.environ["FASTEMBED_CACHE_DIR"]
    expected = str(Path("/tmp").resolve() / "fastembed_cache")
    assert redirected == expected
    assert Path(redirected).exists()

    # Cleanup: remove test dir if we created it
    try:
        Path(redirected).rmdir()
    except OSError:
        pass


def test_no_redirect_when_on_native_fs(tmp_path, engine, monkeypatch):
    """When the cache dir is on a native Linux FS, no redirect happens."""
    saved = os.environ.get("FASTEMBED_CACHE_DIR")
    monkeypatch.delenv("FASTEMBED_CACHE_DIR", raising=False)

    # Let fastembed default to ~/.cache/fastembed — /home is on an ext4 mount
    fake_mounts = (
        "/dev/sda1 / ext4 rw,relatime 0 0\n"
        "/dev/sda2 /home ext4 rw 0 0\n"
    )
    monkeypatch.setattr(
        "cognits.storage.fsdetect._read_proc_mounts",
        lambda: fake_mounts,
    )

    def _run_load():
        engine._load()

    with patch.object(multiprocessing.Process, "start", lambda self: None):
        t = threading.Thread(target=_run_load)
        t.start()
        t.join(timeout=5)

    # No redirect happened — FASTEMBED_CACHE_DIR was not set by _load
    assert os.environ.get("FASTEMBED_CACHE_DIR") is None

    # Restore
    if saved is not None:
        os.environ["FASTEMBED_CACHE_DIR"] = saved


def test_start_background_sets_ready_on_error(monkeypatch):
    """When _load() raises, ready is set in finally and error is populated."""
    def _raise(*args, **kwargs):
        raise RuntimeError("simulated load failure")

    monkeypatch.setattr(RagEngine, "_load", _raise)

    async def run():
        eng = RagEngine.start_background()
        try:
            await asyncio.wait_for(eng.ready.wait(), timeout=5)
        except asyncio.TimeoutError:
            pytest.fail("ready was never set after _load failure")
        assert eng.ready.is_set()
        assert eng.error is not None
        assert "simulated load failure" in eng.error

    asyncio.run(run())
