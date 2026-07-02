"""Tests for server/app.py: drain timeout configuration."""

import os

import cognits.server.app as app_mod


def test_drain_timeout_exists():
    assert isinstance(app_mod._DRAIN_TIMEOUT, float)
    assert app_mod._DRAIN_TIMEOUT > 0


def test_drain_timeout_uses_env_default():
    assert app_mod._DRAIN_TIMEOUT == 5.0
