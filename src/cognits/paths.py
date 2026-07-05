"""Data and configuration paths.

Data lives in cwd/.cognits (formerly cwd/.learnit, from the Go backend).
During the transition both names are valid: if only .learnit exists it is
used in place, without renaming, so the legacy Go binary can keep opening
the same data until it is retired.
"""

import os
import sys
from pathlib import Path

DATA_DIR_NAME = ".cognits"
LEGACY_DATA_DIR_NAME = ".learnit"


def data_dir(create: bool = True) -> Path:
    env = os.environ.get("COGNITS_DATA_DIR")
    if env:
        target = Path(env)
        if create:
            target.mkdir(parents=True, exist_ok=True)
        return target

    cwd = Path.cwd()
    target = cwd / DATA_DIR_NAME
    legacy = cwd / LEGACY_DATA_DIR_NAME
    if not target.exists() and legacy.is_dir():
        return legacy
    if create:
        target.mkdir(parents=True, exist_ok=True)
    return target


DB_FILE_NAME = "cognits.db"
LEGACY_DB_FILE_NAME = "learnit.db"


def db_path(base: Path) -> Path:
    """Database at base/cognits.db; if only the Go backend's learnit.db
    exists it is used in place (same schema)."""
    target = base / DB_FILE_NAME
    legacy = base / LEGACY_DB_FILE_NAME
    if not target.exists() and legacy.exists():
        return legacy
    return target


def user_config_dir() -> Path:
    # Clone of Go's os.UserConfigDir: on Windows it uses APPDATA (Roaming),
    # which is where the Go backend stored the key; platformdirs would use
    # LocalAppData and lose it.
    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA")
        if not appdata:
            raise RuntimeError("APPDATA is not set")
        return Path(appdata)
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support"
    xdg = os.environ.get("XDG_CONFIG_HOME")
    if xdg:
        return Path(xdg)
    return Path.home() / ".config"


def encryption_key_path() -> Path:
    return user_config_dir() / "cognits" / "encryption.key"


def go_encryption_key_path() -> Path:
    """Where the Go backend stored the key (~/.config/learnit/...)."""
    return user_config_dir() / "learnit" / "encryption.key"


def traces_dir() -> Path:
    return data_dir() / "traces"


def rag_dir() -> Path:
    return data_dir() / "rag"


def fastembed_cache_dir() -> Path:
    import os
    return Path(os.environ.get("FASTEMBED_CACHE_DIR", str(Path.home() / ".cache" / "fastembed")))
