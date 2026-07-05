"""Shared fixtures for storage tests: Database + 8 per-domain repos."""

import pytest

from cognits.storage.database import Database
from cognits.storage.learner_state import LearnerStateRepository
from cognits.storage.messages import MessageRepository
from cognits.storage.notes import NoteRepository
from cognits.storage.pedagogical import PedagogicalPlanRepository
from cognits.storage.reports import ReportRepository
from cognits.storage.session_config import SessionConfigRepository
from cognits.storage.skills import SkillRepository
from cognits.storage.study_plans import StudyPlanRepository


@pytest.fixture(autouse=True)
def _disable_rag_for_tests(monkeypatch):
    monkeypatch.setenv("COGNITS_DISABLE_RAG", "1")


@pytest.fixture
def db(tmp_path):
    d = Database(tmp_path / "test.db")
    yield d
    d.shutdown()


@pytest.fixture
def reports(db):
    return ReportRepository(db)


@pytest.fixture
def messages(db):
    return MessageRepository(db)


@pytest.fixture
def notes(db):
    return NoteRepository(db)


@pytest.fixture
def skills(db):
    return SkillRepository(db)


@pytest.fixture
def learner_state(db):
    return LearnerStateRepository(db)


@pytest.fixture
def study_plans(db):
    return StudyPlanRepository(db)


@pytest.fixture
def pedagogy(db):
    return PedagogicalPlanRepository(db)


@pytest.fixture
def session_config(db):
    return SessionConfigRepository(db)


@pytest.fixture
def real_state(tmp_path, monkeypatch):
    """AppState wired to real repos on a tmp_path Database (no LegacyStore).
    
    Use this for integration tests that must exercise production code paths."""
    monkeypatch.chdir(tmp_path)
    from cognits.server.app import AppState, create_app
    from cognits.storage.database import Database

    state = AppState()
    state.db.shutdown()
    db = Database(tmp_path / "test.db")
    state.db = db
    state.reports = ReportRepository(db)
    state.messages = MessageRepository(db)
    state.notes = NoteRepository(db)
    state.skills = SkillRepository(db)
    state.learner_state = LearnerStateRepository(db)
    state.study_plans = StudyPlanRepository(db)
    state.pedagogy = PedagogicalPlanRepository(db)
    state.session_config = SessionConfigRepository(db)
    yield state, create_app(state)
    db.shutdown()


@pytest.fixture
def real_app(real_state):
    """FastAPI app wired to real repos (no async needed)."""
    _, app = real_state
    return app

