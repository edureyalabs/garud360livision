# tests/conftest.py
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from garud360.db.database import Database  # noqa: E402
from garud360.db.repositories import EventRepository, SettingsStore, SpaceRepository, UserRepository  # noqa: E402


@pytest.fixture()
def db(tmp_path):
    d = Database(tmp_path / "test.db")
    yield d
    d.close()


@pytest.fixture()
def repos(db):
    return {"users": UserRepository(db), "spaces": SpaceRepository(db), "events": EventRepository(db),
            "settings": SettingsStore(db)}


def eventually(predicate, timeout: float = 5.0, interval: float = 0.02, message: str = "condition"):
    end = time.monotonic() + timeout
    last = None
    while time.monotonic() < end:
        last = predicate()
        if last:
            return last
        time.sleep(interval)
    raise AssertionError(f"Timed out waiting for {message}")
