"""Rutas de datos y configuración.

Los datos viven en cwd/.cognits (antes cwd/.learnit, era del backend Go).
Durante la transición ambos nombres son válidos: si solo existe .learnit se
usa in place, sin renombrar, para que el binario Go legado pueda seguir
abriendo los mismos datos hasta que se retire.
"""

import os
import sys
from pathlib import Path

DATA_DIR_NAME = ".cognits"
LEGACY_DATA_DIR_NAME = ".learnit"


def data_dir(create: bool = True) -> Path:
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
    """Base de datos en base/cognits.db; si solo existe el learnit.db del
    backend Go se sigue usando in place (mismo esquema)."""
    target = base / DB_FILE_NAME
    legacy = base / LEGACY_DB_FILE_NAME
    if not target.exists() and legacy.exists():
        return legacy
    return target


def user_config_dir() -> Path:
    # Clon de os.UserConfigDir de Go: en Windows usa APPDATA (Roaming), que es
    # donde el backend Go dejó la clave; platformdirs usaría LocalAppData y la
    # perdería.
    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA")
        if not appdata:
            raise RuntimeError("APPDATA no está definido")
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
    """Donde el backend Go guardaba la clave (~/.config/learnit/...)."""
    return user_config_dir() / "learnit" / "encryption.key"
