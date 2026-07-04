"""Tests for tinyfish.py: basic client construction."""

import pytest

from cognits.tinyfish import TinyfishClient, TinyfishError


def test_client_constructs():
    client = TinyfishClient("fake-key")
    assert client.api_key == "fake-key"
    assert client._client is not None


def test_error_is_exception():
    e = TinyfishError("boom")
    assert isinstance(e, Exception)
    assert str(e) == "boom"
