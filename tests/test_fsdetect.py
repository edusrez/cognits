"""Tests for storage/fsdetect.py: filesystem detection + journal mode selection."""
from __future__ import annotations

import pytest

from cognits.storage.database import Database
from cognits.storage.fsdetect import (
    WAL_UNSAFE_FSTYPES,
    choose_journal_mode,
    fstype_of,
    is_wal_unsafe_fstype,
    synchronous_for,
)


# -- choose_journal_mode -------------------------------------------------

def test_choose_journal_mode_env_delete(monkeypatch):
    monkeypatch.setenv("COGNITS_JOURNAL_MODE", "delete")
    assert choose_journal_mode("/tmp/test.db") == "delete"


def test_choose_journal_mode_env_wal(monkeypatch):
    monkeypatch.setenv("COGNITS_JOURNAL_MODE", "wal")
    assert choose_journal_mode("/tmp/test.db") == "wal"


def test_choose_journal_mode_env_truncate(monkeypatch):
    monkeypatch.setenv("COGNITS_JOURNAL_MODE", "truncate")
    assert choose_journal_mode("/tmp/test.db") == "truncate"


def test_choose_journal_mode_env_persist(monkeypatch):
    monkeypatch.setenv("COGNITS_JOURNAL_MODE", "persist")
    assert choose_journal_mode("/tmp/test.db") == "persist"


def test_choose_journal_mode_env_memory(monkeypatch):
    monkeypatch.setenv("COGNITS_JOURNAL_MODE", "memory")
    assert choose_journal_mode("/tmp/test.db") == "memory"


def test_choose_journal_mode_env_invalid_falls_through(monkeypatch):
    monkeypatch.setenv("COGNITS_JOURNAL_MODE", "foobar")
    # Not a valid journal mode — auto-detect kicks in.
    # On a native Linux filesystem, this should return "wal".
    assert choose_journal_mode("/tmp/test.db") == "wal"


def test_choose_journal_mode_auto_detect_wal(tmp_path):
    # tmp_path is on a real Linux filesystem (ext4/xfs) → "wal"
    assert choose_journal_mode(tmp_path / "test.db") == "wal"


def test_choose_journal_mode_auto_detect_unsafe(monkeypatch):
    fake_mounts = (
        "/dev/sda1 / ext4 rw,relatime 0 0\n"
        "C:\\ /mnt/c 9p rw,noatime,dirsync,aname=drvfs;path=C:\\;uid=1000;gid=1000;metadata;case=off;symlinkroot=/mnt/ 0 0\n"
    )
    monkeypatch.setattr(
        "cognits.storage.fsdetect._read_proc_mounts",
        lambda: fake_mounts,
    )
    assert choose_journal_mode("/mnt/c/Users/test.db") == "memory"


# -- fstype_of ----------------------------------------------------------------

def test_fstype_of_finds_mount(monkeypatch):
    fake_mounts = (
        "/dev/sda1 / ext4 rw,relatime 0 0\n"
        "C:\\ /mnt/c 9p rw,noatime,dirsync 0 0\n"
    )
    monkeypatch.setattr(
        "cognits.storage.fsdetect._read_proc_mounts",
        lambda: fake_mounts,
    )
    assert fstype_of("/mnt/c/Users/test.db") == "9p"
    assert fstype_of("/home/user/test.db") == "ext4"
    assert fstype_of("/") == "ext4"


def test_fstype_of_longest_prefix_wins(monkeypatch):
    fake_mounts = (
        "/dev/sda1 / ext4 rw,relatime 0 0\n"
        "/dev/sda2 /var ext4 rw 0 0\n"
        "/dev/sda3 /var/log btrfs rw 0 0\n"
    )
    monkeypatch.setattr(
        "cognits.storage.fsdetect._read_proc_mounts",
        lambda: fake_mounts,
    )
    assert fstype_of("/var/log/test.db") == "btrfs"
    assert fstype_of("/var/spool/test.db") == "ext4"


def test_fstype_of_no_match_returns_none(monkeypatch):
    monkeypatch.setattr(
        "cognits.storage.fsdetect._read_proc_mounts",
        lambda: "",
    )
    assert fstype_of("/tmp/test.db") is None


def test_fstype_of_fuse_dot(monkeypatch):
    fake_mounts = (
        "/dev/sda1 / ext4 rw,relatime 0 0\n"
        "sshfs /mnt/remote fuse.sshfs rw 0 0\n"
    )
    monkeypatch.setattr(
        "cognits.storage.fsdetect._read_proc_mounts",
        lambda: fake_mounts,
    )
    assert fstype_of("/mnt/remote/test.db") == "fuse.sshfs"


# -- is_wal_unsafe_fstype -------------------------------------------------------

def test_is_wal_unsafe_known_unsafe():
    assert is_wal_unsafe_fstype("9p") is True
    assert is_wal_unsafe_fstype("drvfs") is True
    assert is_wal_unsafe_fstype("cifs") is True
    assert is_wal_unsafe_fstype("nfs") is True
    assert is_wal_unsafe_fstype("nfs4") is True
    assert is_wal_unsafe_fstype("smb") is True
    assert is_wal_unsafe_fstype("fuse") is True


def test_is_wal_unsafe_fuse_dot():
    assert is_wal_unsafe_fstype("fuse.sshfs") is True
    assert is_wal_unsafe_fstype("fuse.s3fs") is True


def test_is_wal_unsafe_known_safe():
    assert is_wal_unsafe_fstype("ext4") is False
    assert is_wal_unsafe_fstype("xfs") is False
    assert is_wal_unsafe_fstype("btrfs") is False
    assert is_wal_unsafe_fstype("tmpfs") is False
    assert is_wal_unsafe_fstype("ntfs") is False


def test_is_wal_unsafe_none():
    assert is_wal_unsafe_fstype(None) is False


# -- synchronous_for -----------------------------------------------------------

def test_synchronous_for_delete():
    assert synchronous_for("delete") == "EXTRA"


def test_synchronous_for_memory():
    assert synchronous_for("memory") == "NORMAL"


def test_synchronous_for_wal():
    assert synchronous_for("wal") == "NORMAL"


def test_synchronous_for_other():
    assert synchronous_for("truncate") == "NORMAL"
    assert synchronous_for("persist") == "NORMAL"


# -- WAL_UNSAFE_FSTYPES completeness -------------------------------------------

def test_wal_unsafe_contains_wsl_types():
    assert "9p" in WAL_UNSAFE_FSTYPES
    assert "drvfs" in WAL_UNSAFE_FSTYPES


# -- Integration: Database with forced delete mode -----------------------------

def test_database_delete_mode_durable(tmp_path, monkeypatch):
    """Open a Database with COGNITS_JOURNAL_MODE=delete, verify mode + durability."""
    monkeypatch.setenv("COGNITS_JOURNAL_MODE", "delete")

    db = Database(tmp_path / "int.db")
    try:
        # journal_mode should be "delete"
        assert db.journal_mode == "delete"

        # synchronous should be EXTRA (PRAGMA synchronous returns an integer: 3).
        sync_val = db.conn.execute("PRAGMA synchronous").fetchone()[0]
        assert sync_val == 3  # 3 = EXTRA

        # Write data in a transaction and commit.
        with db.transaction():
            db.conn.execute(
                "INSERT INTO notes (id, title) VALUES ('n1', 'durable')"
            )
    finally:
        db.shutdown()

    # Reopen and verify the row survived.
    db2 = Database(tmp_path / "int.db")
    try:
        assert db2.journal_mode == "delete"
        row = db2.conn.execute(
            "SELECT title FROM notes WHERE id = 'n1'"
        ).fetchone()
        assert row is not None
        assert row[0] == "durable"
    finally:
        db2.shutdown()


def test_database_memory_mode_writable(tmp_path, monkeypatch):
    """Open a Database with COGNITS_JOURNAL_MODE=memory, verify mode + writability."""
    monkeypatch.setenv("COGNITS_JOURNAL_MODE", "memory")

    db = Database(tmp_path / "mem.db")
    try:
        assert db.journal_mode == "memory"

        # synchronous should be NORMAL (PRAGMA synchronous returns an integer: 1).
        sync_val = db.conn.execute("PRAGMA synchronous").fetchone()[0]
        assert sync_val == 1  # 1 = NORMAL

        # Write data in a transaction and commit.
        with db.transaction():
            db.conn.execute(
                "INSERT INTO notes (id, title) VALUES ('mem1', 'memory_mode')"
            )
    finally:
        db.shutdown()

    # Reopen and verify the row survived.
    db2 = Database(tmp_path / "mem.db")
    try:
        assert db2.journal_mode == "memory"
        row = db2.conn.execute(
            "SELECT title FROM notes WHERE id = 'mem1'"
        ).fetchone()
        assert row is not None
        assert row[0] == "memory_mode"
    finally:
        db2.shutdown()


def test_choose_journal_mode_unsafe_fstype_returns_memory(monkeypatch):
    """When the filesystem is 9p, choose_journal_mode returns 'memory' not 'delete'."""
    fake_mounts = (
        "C:\\ /mnt/c 9p rw,noatime,dirsync 0 0\n"
    )
    monkeypatch.setattr(
        "cognits.storage.fsdetect._read_proc_mounts",
        lambda: fake_mounts,
    )
    assert choose_journal_mode("/mnt/c/test.db") == "memory"
