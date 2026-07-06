"""Filesystem detection for SQLite journal-mode selection.

WAL mode is unsafe on network/non-local filesystems (the wal-index lives in
shared memory that cannot be reliably shared over 9P/CIFS/NFS/FUSE). On such
filesystems we fall back to a rollback journal (DELETE) so committed
transactions are not stranded in a WAL that never checkpoints correctly.
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
VALID_JOURNAL_MODES = {"wal", "delete", "truncate", "persist"}


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
      1. COGNITS_JOURNAL_MODE env var (one of wal/delete/truncate/persist) — wins.
      2. Auto-detect: DELETE if the path is on a WAL-unsafe fstype, else WAL.
    """
    forced = os.environ.get("COGNITS_JOURNAL_MODE", "").strip().lower()
    if forced in VALID_JOURNAL_MODES:
        return forced
    if is_wal_unsafe_fstype(fstype_of(db_path)):
        return "delete"
    return "wal"


def synchronous_for(mode: str) -> str:
    """Pair the right synchronous setting with the journal mode."""
    return "EXTRA" if mode == "delete" else "NORMAL"
