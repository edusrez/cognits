"""Tests for ApplyProfile tool (Bug 2 fix verification)."""

import asyncio
import json

import pytest

from cognits.agent.tool_ui import ApplyProfile
from cognits.storage.files import StudentProfile


class FakeStore:
    def __init__(self, profile=None):
        self.profile = profile or StudentProfile()
        self.last_saved = None

    def load_profile(self, sid=None):
        return self.profile

    def save_profile(self, profile):
        self.last_saved = profile


def test_apply_profile_confidence_gating_higher():
    store = FakeStore(StudentProfile(
        inferred={"skill_x": {"confidence": 0.5, "level": "beginner"}}
    ))
    tool = ApplyProfile(store=store, session_id="s_test")

    result = asyncio.run(tool.execute(json.dumps({
        "patch_json": json.dumps({
            "inferred": {"skill_x": {"confidence": 0.8, "level": "expert"}}
        })
    })))
    data = json.loads(result)
    assert "message" in data
    assert store.last_saved is not None
    assert store.last_saved.inferred["skill_x"]["level"] == "expert"


def test_apply_profile_confidence_gating_lower_does_not_overwrite():
    store = FakeStore(StudentProfile(
        inferred={"skill_x": {"confidence": 0.8, "level": "expert"}}
    ))
    tool = ApplyProfile(store=store, session_id="s_test")

    asyncio.run(tool.execute(json.dumps({
        "patch_json": json.dumps({
            "inferred": {"skill_x": {"confidence": 0.3, "level": "beginner"}}
        })
    })))
    assert store.last_saved.inferred["skill_x"]["level"] == "expert"


def test_apply_profile_sessions_increment():
    store = FakeStore(StudentProfile(meta={}))
    tool = ApplyProfile(store=store, session_id="s_test")

    asyncio.run(tool.execute(json.dumps({
        "patch_json": json.dumps({
            "meta": {"sessions": "increment"}
        })
    })))
    assert store.last_saved.meta["sessions"] == 1


def test_apply_profile_changelog_truncation():
    store = FakeStore()
    tool = ApplyProfile(store=store, session_id="s_test")
    long_val = "x" * 500

    asyncio.run(tool.execute(json.dumps({
        "patch_json": json.dumps({
            "inferred": {"skill_x": {"value": long_val}}
        })
    })))
    from cognits.constants import CHANGELOG_VALUE_MAX_CHARS
    changelog = store.last_saved.meta.get("changelog", [])
    assert changelog
    logged_val = changelog[-1]["changes"].get("skill_x", "")
    assert len(logged_val) <= CHANGELOG_VALUE_MAX_CHARS


def test_apply_profile_store_none():
    tool = ApplyProfile(store=None, session_id="s_test")

    async def run():
        result = await tool.execute(json.dumps({"patch_json": "{}"}))
        return result

    result = asyncio.run(run())
    assert "error" in json.loads(result)


def test_apply_profile_invalid_args():
    tool = ApplyProfile(store=FakeStore(), session_id="s_test")
    result = asyncio.run(tool.execute("not json"))
    assert "error" in json.loads(result)
