"""Tests for server/app.py: drain timeout configuration."""

from cognits.server.app import _DRAIN_TIMEOUT


def test_drain_timeout_exists():
    assert isinstance(_DRAIN_TIMEOUT, float)
    assert _DRAIN_TIMEOUT > 0
