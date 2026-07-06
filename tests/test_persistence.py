"""Integration tests: data persistence across Database close/reopen cycles.

Covers the WSL DrvFs data-loss scenario: WAL checkpoint silently failed on 9p,
and the DB was empty on reopen. These tests verify that data survives close/reopen
cycles in DELETE mode and that the WAL->DELETE cleanup preserves data.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from cognits.storage.database import Database
from cognits.storage.learner_state import LearnerStateRepository
from cognits.storage.messages import MessageRepository
from cognits.storage.models import (
    LearnerState,
    MessageRow,
    Report,
    Skill,
    new_report_id,
    new_skill_id,
)
from cognits.storage.reports import ReportRepository
from cognits.storage.skills import SkillRepository


class TestFullPersistenceCycle:
    """Simulate full setup cycle in DELETE mode: report + skill + message +
    learner_state survive two close/reopen cycles."""

    def test_full_persistence_cycle_delete_mode(self, tmp_path, monkeypatch):
        monkeypatch.setenv("COGNITS_JOURNAL_MODE", "delete")
        db_path = tmp_path / "persist.db"

        # ---------- first open ----------
        db = Database(db_path)
        assert db.journal_mode == "delete"

        reports = ReportRepository(db)
        skills = SkillRepository(db)
        messages = MessageRepository(db)
        learner = LearnerStateRepository(db)

        report_id = new_report_id()
        session_id = "sess_abc"
        skill_id = new_skill_id()

        reports.save(Report(
            id=report_id,
            session_id=session_id,
            title="Test Report",
            content="Report content for persistence test.",
            sources=["https://example.com"],
        ))

        skills.upsert(Skill(
            id=skill_id,
            domain="math",
            name="Test Skill",
            description="A test skill.",
            bloom_level="understand",
            difficulty=0.5,
        ))

        messages.append(session_id, MessageRow(
            session_id=session_id,
            role="user",
            content="Hello, test!",
        ))

        learner.upsert(LearnerState(
            skill_id=skill_id,
            p_mastery=0.7,
            status_enum="practicing",
        ))

        db.shutdown()

        # ---------- second open ----------
        db2 = Database(db_path)
        assert db2.journal_mode == "delete"

        reports2 = ReportRepository(db2)
        skills2 = SkillRepository(db2)
        messages2 = MessageRepository(db2)
        learner2 = LearnerStateRepository(db2)

        got = reports2.get(report_id)
        assert got is not None
        assert got.title == "Test Report"
        assert got.content == "Report content for persistence test."
        assert got.sources == ["https://example.com"]

        tree = skills2.get_tree()
        skill_ids = [sk["id"] for sk in tree["skills"]]
        assert skill_id in skill_ids

        msgs = messages2.load(session_id)
        assert len(msgs) == 1
        assert msgs[0].content == "Hello, test!"
        assert msgs[0].role == "user"

        st = learner2.get(skill_id)
        assert st is not None
        assert st.p_mastery == 0.7
        assert st.status_enum == "practicing"

        db2.shutdown()

        # ---------- third open ----------
        db3 = Database(db_path)
        assert db3.journal_mode == "delete"

        reports3 = ReportRepository(db3)
        got3 = reports3.get(report_id)
        assert got3 is not None
        assert got3.title == "Test Report"

        db3.shutdown()


class TestPersistenceWithoutTransaction:
    """ReportRepository.save() uses self.db.lock + autocommit (NOT transaction()).
    Verify data survives close/reopen."""

    def test_persistence_without_transaction(self, tmp_path, monkeypatch):
        monkeypatch.setenv("COGNITS_JOURNAL_MODE", "delete")
        db_path = tmp_path / "autocommit.db"

        db = Database(db_path)
        reports = ReportRepository(db)

        report_id = new_report_id()
        reports.save(Report(
            id=report_id,
            session_id="sess_x",
            title="Autocommit Test",
            content="Saved without explicit transaction.",
        ))
        db.shutdown()

        db2 = Database(db_path)
        reports2 = ReportRepository(db2)
        got = reports2.get(report_id)
        assert got is not None
        assert got.title == "Autocommit Test"
        assert got.content == "Saved without explicit transaction."
        db2.shutdown()


class TestWalCleanupOnReopen:
    """Verify data survives when switching from WAL to DELETE mode."""

    def test_wal_cleanup_on_reopen(self, tmp_path, monkeypatch):
        db_path = tmp_path / "wal.db"

        # Phase 1: create with WAL mode
        monkeypatch.setenv("COGNITS_JOURNAL_MODE", "wal")
        db = Database(db_path)
        assert db.journal_mode == "wal"

        reports = ReportRepository(db)
        report_id = new_report_id()
        reports.save(Report(
            id=report_id,
            session_id="sess_wal",
            title="WAL Report",
            content="Created in WAL mode.",
        ))
        db.shutdown()

        # Phase 2: reopen with DELETE mode - triggers WAL cleanup path
        monkeypatch.setenv("COGNITS_JOURNAL_MODE", "delete")
        db2 = Database(db_path)
        assert db2.journal_mode in ("delete", "wal"), \
            f"Unexpected journal_mode: {db2.journal_mode}"

        reports2 = ReportRepository(db2)
        got = reports2.get(report_id)
        assert got is not None
        assert got.title == "WAL Report"
        assert got.content == "Created in WAL mode."
        db2.shutdown()


class TestMultipleShutdownReopenCycles:
    """5 save/shutdown/reopen/verify cycles in DELETE mode."""

    def test_multiple_shutdown_reopen_cycles(self, tmp_path, monkeypatch):
        monkeypatch.setenv("COGNITS_JOURNAL_MODE", "delete")
        db_path = tmp_path / "cycles.db"

        db = Database(db_path)
        assert db.journal_mode == "delete"
        reports = ReportRepository(db)

        for i in range(5):
            reports.save(Report(
                id=f"r{i}",
                session_id="sess_cycle",
                title=f"Report {i}",
                content=f"Content {i}",
            ))
            db.shutdown()

            db = Database(db_path)
            assert db.journal_mode == "delete"
            reports = ReportRepository(db)

            for j in range(i + 1):
                got = reports.get(f"r{j}")
                assert got is not None, f"Missing report r{j} after cycle {i}"
                assert got.title == f"Report {j}"

        db.shutdown()


class TestDeleteModeNoWalFiles:
    """In DELETE mode, no -wal or -shm files should remain after shutdown."""

    def test_delete_mode_no_wal_files(self, tmp_path, monkeypatch):
        monkeypatch.setenv("COGNITS_JOURNAL_MODE", "delete")
        db_path = tmp_path / "nowal.db"

        db = Database(db_path)
        assert db.journal_mode == "delete"

        reports = ReportRepository(db)
        reports.save(Report(
            id=new_report_id(),
            session_id="sess_nowal",
            title="No WAL",
            content="Should not leave WAL files.",
        ))
        db.shutdown()

        wal_path = Path(str(db_path) + "-wal")
        shm_path = Path(str(db_path) + "-shm")
        assert not wal_path.exists(), f"Unexpected WAL file: {wal_path}"
        assert not shm_path.exists(), f"Unexpected SHM file: {shm_path}"
        assert db_path.exists()
        assert db_path.stat().st_size > 0
