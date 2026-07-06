"""Tests for tinyfish.py: basic client construction, constants, and semaphore."""

import asyncio
import time

import pytest

from cognits.tinyfish import TinyfishClient, TinyfishError, _tinyfish_sem


def test_client_constructs():
    client = TinyfishClient("fake-key")
    assert client.api_key == "fake-key"
    assert client._client is not None


def test_error_is_exception():
    e = TinyfishError("boom")
    assert isinstance(e, Exception)
    assert str(e) == "boom"


def test_max_concurrent_deploys():
    from cognits.constants import MAX_CONCURRENT_DEPLOYS
    assert MAX_CONCURRENT_DEPLOYS == 4


def test_tinyfish_concurrency():
    from cognits.constants import TINYFISH_CONCURRENCY
    assert TINYFISH_CONCURRENCY == 3


def test_semaphore_limits_concurrency():
    """Spawn more tasks than TINYFISH_CONCURRENCY; assert at most N run at once."""
    from cognits.constants import TINYFISH_CONCURRENCY

    concurrent = 0
    max_concurrent = 0
    lock = asyncio.Lock()

    async def fake_http_call():
        nonlocal concurrent, max_concurrent
        async with _tinyfish_sem:
            async with lock:
                concurrent += 1
                if concurrent > max_concurrent:
                    max_concurrent = concurrent
            await asyncio.sleep(0.05)
            async with lock:
                concurrent -= 1

    async def run():
        n_tasks = TINYFISH_CONCURRENCY + 5  # 8 tasks, only 3 at once
        start = time.monotonic()
        await asyncio.gather(*(fake_http_call() for _ in range(n_tasks)))
        elapsed = time.monotonic() - start
        return max_concurrent, elapsed

    max_conc, elapsed = asyncio.run(run())

    assert max_conc <= TINYFISH_CONCURRENCY
    # With 8 tasks and max 3 concurrent, sequential would be 8 * 0.05 = 0.4s.
    # With 3-way parallelism: ceil(8/3) * 0.05 ≈ 0.15s. Allow some overhead.
    assert elapsed < 0.35
