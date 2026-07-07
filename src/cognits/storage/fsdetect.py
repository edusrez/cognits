"""Filesystem detection for SQLite journal-mode selection.

WAL mode is unsafe on network/non-local filesystems (the wal-index lives in
shared memory that cannot be reliably shared over 9P/CIFS/NFS/FUSE). On such
filesystems we fall back to MEMORY journal mode (rollback journal in RAM)
because DELETE also fails on DrvFs/9p (read-only after ~41s). MEMORY keeps
the journal in RAM with zero file I/O for the journal.
"""
from __future__ import annotations

import os
from pathlib import Path

# Filesystems where SQLite WAL is unsafe (shared-memory/locking unreliable).
WAL_UNSAFE_FSTYPES = {
    "9p", "drvfs", "virtio-plan9", "virtiofs",
    "cifs", "smb2", "smb3", "smb",
    "nfs", "nfs4",
    "fuse", "davfs",
}
VALID_JOURNAL_MODES = {"wal", "delete", "truncate", "persist", "memory"}


def _read_proc_mounts() -> str:
    try:
        return Path("/proc/mounts").read_text()
    except OSError:
        return ""


def fstype_of(path: str | Path) -> str | None:
    """Return the fstype of the mount containing `path` (longest-prefix match
    on /proc/mounts). None if it cannot be determined (non-Linux, or no match)."""
    try:
        target = str(Path(path).resolve())
    except OSError:
        target = str(path)
    best: str | None = None
    best_len = -1
    for line in _read_proc_mounts().splitlines():
        parts = line.split()
        if len(parts) < 3:
            continue
        _dev, mnt, fstype = parts[0], parts[1], parts[2]
        mnt_norm = mnt.rstrip("/") or "/"
        if target == mnt_norm or target.startswith(mnt_norm.rstrip("/") + "/"):
            if len(mnt_norm) > best_len:
                best, best_len = fstype, len(mnt_norm)
    return best


def is_wal_unsafe_fstype(fstype: str | None) -> bool:
    if not fstype:
        return False
    if fstype in WAL_UNSAFE_FSTYPES:
        return True
    return fstype.startswith("fuse.")


def choose_journal_mode(db_path: str | Path) -> str:
    """Decide the SQLite journal mode for `db_path`.

    Precedence:
      1. COGNITS_JOURNAL_MODE env var (one of wal/delete/truncate/persist/memory) — wins.
      2. Auto-detect: MEMORY if the path is on a WAL-unsafe fstype, else WAL.
    """
    forced = os.environ.get("COGNITS_JOURNAL_MODE", "").strip().lower()
    if forced in VALID_JOURNAL_MODES:
        return forced
    if is_wal_unsafe_fstype(fstype_of(db_path)):
        return "memory"
    return "wal"


def synchronous_for(mode: str) -> str:
    """Pair the right synchronous setting with the journal mode."""
    if mode == "memory":
        return "NORMAL"  # fsync at commit so 9p flushes to Windows side
    if mode == "delete":
        return "EXTRA"
    return "NORMAL"
