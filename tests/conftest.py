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
