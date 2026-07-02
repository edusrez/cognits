"""Tests for storage/database.py: shutdown, transaction, RLock."""

import pytest

from cognits.storage.database import Database


def test_database_creates_tables(db):
    assert db.conn is not None
    row = db.conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='reports'"
    ).fetchone()
    assert row is not None


def test_database_shutdown_idempotent(db):
    db.shutdown()
    db.shutdown()  # must not raise


def test_database_shutdown_closes_connection(db):
    db.shutdown()
    with pytest.raises(Exception):
        db.conn.execute("SELECT 1")


def test_transaction_commits(db):
    with db.transaction():
        db.conn.execute(
            "INSERT INTO notes (id, title) VALUES ('n1', 'hello')"
        )
    row = db.conn.execute("SELECT title FROM notes WHERE id = 'n1'").fetchone()
    assert row[0] == "hello"


def test_transaction_rollback(db):
    try:
        with db.transaction():
            db.conn.execute(
                "INSERT INTO notes (id, title) VALUES ('n2', 'rollback')"
            )
            raise RuntimeError("forced")
    except RuntimeError:
        pass
    row = db.conn.execute("SELECT id FROM notes WHERE id = 'n2'").fetchone()
    assert row is None


def test_transaction_rollback_preserves_prior_data(db):
    db.conn.execute("INSERT INTO notes (id, title) VALUES ('n_pre', 'before')")
    try:
        with db.transaction():
            db.conn.execute(
                "INSERT INTO notes (id, title) VALUES ('n_fail', 'fail')"
            )
            raise RuntimeError("forced")
    except RuntimeError:
        pass
    row = db.conn.execute(
        "SELECT title FROM notes WHERE id = 'n_pre'"
    ).fetchone()
    assert row[0] == "before"
    assert db.conn.execute(
        "SELECT 1 FROM notes WHERE id = 'n_fail'"
    ).fetchone() is None
