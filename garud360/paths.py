# garud360/paths.py
"""Filesystem locations. All mutable data lives in a per-user data directory."""
from __future__ import annotations

import os
import sys
from pathlib import Path

from garud360 import APP_ID

_override: Path | None = None


def set_data_dir(path: str | os.PathLike[str]) -> None:
    """Force a data directory (used by --data-dir and by the tests)."""
    global _override
    _override = Path(path).expanduser().resolve()


def data_dir() -> Path:
    if _override is not None:
        base = _override
    elif os.environ.get("GARUD360_DATA_DIR"):
        base = Path(os.environ["GARUD360_DATA_DIR"]).expanduser().resolve()
    elif sys.platform == "win32":
        root = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        base = Path(root) / APP_ID
    else:
        root = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
        base = Path(root) / APP_ID
    base.mkdir(parents=True, exist_ok=True)
    return base


def _sub(name: str) -> Path:
    p = data_dir() / name
    p.mkdir(parents=True, exist_ok=True)
    return p


def db_path() -> Path:
    return data_dir() / "garud360.db"


def logs_dir() -> Path:
    return _sub("logs")


def snapshots_dir() -> Path:
    return _sub("snapshots")


def models_dir() -> Path:
    return _sub("models")


def lock_path() -> Path:
    return data_dir() / "garud360.lock"


def resource_path(relative: str) -> Path:
    """Locate a bundled resource both from source and from a PyInstaller build."""
    if getattr(sys, "frozen", False):
        base = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    else:
        base = Path(__file__).resolve().parent.parent
    return base / relative
