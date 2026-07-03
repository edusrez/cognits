"""Onboarding trigger tests for finish_setup -> skill_planner.

Uses a fake async deployer (no network) and a fake store to verify the
finish_setup tool wires the skill_planner correctly when invoked from the
system_support agent.

Convention: plain asyncio.run, no pytest-asyncio (matches codebase).
"""

import asyncio
import json

import pytest

from cognits.agent.tool_ui import FinishSetup
from cognits.agent.prompts import SYSTEM_SUPPORT_PROMPT


# --- fakes -----------------------------------------------------------

class _FakeStore:
    def __init__(self):
        self.saved = None

    def save_profile(self, profile):
        self.saved = profile


def _make_emit_capture():
    events = []

    def emit(ev):
        events.append(ev)

    return events, emit


# --- prompt static check --------------------------------------------

def test_system_support_prompt_describes_trigger_and_result_contract():
    # The prompt instructs system_support about the new contract.
    assert "skill_planner" in SYSTEM_SUPPORT_PROMPT
    assert "skillTreeBuilt" in SYSTEM_SUPPORT_PROMPT
    assert "skillTreeReport" in SYSTEM_SUPPORT_PROMPT
    assert "skillTreeError" in SYSTEM_SUPPORT_PROMPT
    # Mentions automatic invocation from finish_setup.
    assert "finish_setup" in SYSTEM_SUPPORT_PROMPT
    assert "skill tree" in SYSTEM_SUPPORT_PROMPT.lower() or "skill_tree" in SYSTEM_SUPPORT_PROMPT.lower()
    # Regresión: la regla de idioma por defecto existe.
    assert "default to English" in SYSTEM_SUPPORT_PROMPT


# Spanish phrases that were hardcoded in an earlier revision. Kept as a
# regression guard so prompts stay in English and the agent adapts to the
# user's language at runtime instead.
_SPANISH_PHRASES = (
    "He construido",
    "Tu perfil está",
    "pídemelo",
    "haz click",
    "pestaña",
    "para comenzar",
    "Razón",
    "Configura",
)


@pytest.mark.parametrize("phrase", _SPANISH_PHRASES)
def test_system_support_prompt_contains_no_hardcoded_spanish(phrase):
    assert phrase not in SYSTEM_SUPPORT_PROMPT


@pytest.mark.parametrize("phrase", _SPANISH_PHRASES)
def test_skill_planner_prompt_contains_no_hardcoded_spanish(phrase):
    from cognits.agent.prompts import SKILL_PLANNER_SYSTEM_PROMPT
    assert phrase not in SKILL_PLANNER_SYSTEM_PROMPT


# --- deployer-invocation tests --------------------------------------

def _profile_args():
    return {
        "background": "physics graduate",
        "project": "Aprender Python",
        "experience": "some C, no Python",
        "learning_style": "socratic",
        "availability": "evenings",
        "goals": "programar bien",
    }


def test_finish_setup_calls_deployer_with_serialized_profile():
    received_queries = []

    async def fake_deployer(query: str) -> str:
        received_queries.append(query)
        return json.dumps({"content": "# Skill tree for Python\n\nN skills built."})

    events, emit = _make_emit_capture()
    store = _FakeStore()
    tool = FinishSetup(
        emit=emit,
        store=store,
        skill_planner_deployer=fake_deployer,
    )

    result = asyncio.run(tool.execute(json.dumps(_profile_args())))
    data = json.loads(result)

    assert data["skillTreeBuilt"] is True
    assert data["skillTreeReport"] == "# Skill tree for Python\n\nN skills built."
    assert data["skillTreeError"] is None
    # The deployer was called once with the inline profile.
    assert len(received_queries) == 1
    q = received_queries[0]
    assert "Project: Aprender Python" in q
    assert "Goals: programar bien" in q
    assert "Experience: some C, no Python" in q
    assert "Background: physics graduate" in q
    assert "Learning style: socratic" in q
    assert "Availability: evenings" in q
    # Profile was persisted.
    assert store.saved is not None
    # setup_complete emitted AFTER the tree pass, with the new field.
    assert any(
        e["type"] == "setup_complete" and e["data"].get("skillTreeBuilt") is True
        for e in events
    )


def test_finish_setup_without_deployer_marks_not_built_and_emits_complete():
    events, emit = _make_emit_capture()
    store = _FakeStore()
    tool = FinishSetup(emit=emit, store=store, skill_planner_deployer=None)

    result = asyncio.run(tool.execute(json.dumps(_profile_args())))
    data = json.loads(result)

    assert data["skillTreeBuilt"] is False
    assert data["skillTreeError"] == "TinyFish API key not configured"
    assert data["skillTreeReport"] is None
    # Profile still saved.
    assert store.saved is not None
    # setup_complete still emitted.
    assert any(e["type"] == "setup_complete" for e in events)
    # The emitted payload reports the tree as not built.
    sc = next(e for e in events if e["type"] == "setup_complete")
    assert sc["data"].get("skillTreeBuilt") is False


def test_finish_setup_propagates_deployer_error_gracefully():
    async def failing_deployer(query: str) -> str:
        return json.dumps({"error": "TinyFish API key not configured. Please configure it in Settings."})

    events, emit = _make_emit_capture()
    store = _FakeStore()
    tool = FinishSetup(emit=emit, store=store, skill_planner_deployer=failing_deployer)

    result = asyncio.run(tool.execute(json.dumps(_profile_args())))
    data = json.loads(result)

    assert data["skillTreeBuilt"] is False
    assert "TinyFish" in data["skillTreeError"]
    # Profile still saved despite the error.
    assert store.saved is not None
    # setup_complete emitted with skillTreeBuilt=False.
    sc = next(e for e in events if e["type"] == "setup_complete")
    assert sc["data"].get("skillTreeBuilt") is False


def test_finish_setup_propagates_deployer_exception_gracefully():
    async def crashing_deployer(query: str) -> str:
        raise RuntimeError("boom")

    events, emit = _make_emit_capture()
    store = _FakeStore()
    tool = FinishSetup(emit=emit, store=store, skill_planner_deployer=crashing_deployer)

    result = asyncio.run(tool.execute(json.dumps(_profile_args())))
    data = json.loads(result)

    assert data["skillTreeBuilt"] is False
    assert "boom" in data["skillTreeError"]
    # Profile saved and setup_complete still emitted.
    assert store.saved is not None
    assert any(e["type"] == "setup_complete" for e in events)


def test_finish_setup_propagates_cancellation_without_emitting_complete():
    async def cancelling_deployer(query: str) -> str:
        raise asyncio.CancelledError()

    events, emit = _make_emit_capture()
    store = _FakeStore()
    tool = FinishSetup(emit=emit, store=store, skill_planner_deployer=cancelling_deployer)

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(tool.execute(json.dumps(_profile_args())))
    # On cancellation setup_complete must NOT be emitted.
    assert not any(e["type"] == "setup_complete" for e in events)