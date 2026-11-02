# garud360/db/repositories.py
"""Data-access layer. Every public method validates its input and is thread-safe."""
from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

from garud360.config import defaults as cfg
from garud360.config import settings_schema as schema
from garud360.core.camera.source import validate_source
from garud360.core.models import Camera, Event, Space, User
from garud360.db.database import Database

log = logging.getLogger(__name__)


class RepoError(ValueError):
    """A user-correctable problem (validation, duplicate name, limit reached)."""


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def local_day(now: datetime | None = None) -> str:
    return (now or datetime.now()).strftime("%Y-%m-%d")


def _loads(text: str | None, default: Any) -> Any:
    if not text:
        return default
    try:
        return json.loads(text)
    except (TypeError, ValueError):
        log.warning("Corrupt JSON in database ignored: %.80s", text)
        return default


# ----------------------------------------------------------------------------- users
class UserRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    @staticmethod
    def _row(r: sqlite3.Row) -> User:
        return User(r["id"], r["username"], r["role"], bool(r["must_change_password"]),
                    bool(r["active"]), r["created_at"], r["last_login_at"])

    def count(self) -> int:
        return self.db.query_one("SELECT COUNT(*) c FROM users")["c"]

    def create(self, username: str, password_hash: str, role: str, must_change: bool) -> User:
        username = username.strip()
        if not (3 <= len(username) <= 40) or not username.replace("_", "").replace(".", "").replace("-", "").isalnum():
            raise RepoError("Username must be 3-40 characters: letters, digits, '.', '_' or '-'.")
        if role not in cfg.ROLES:
            raise RepoError("Unknown role.")
        try:
            cur = self.db.execute(
                "INSERT INTO users(username,password_hash,role,must_change_password,created_at) VALUES(?,?,?,?,?)",
                (username, password_hash, role, int(must_change), utc_now()))
        except sqlite3.IntegrityError:
            raise RepoError(f"User '{username}' already exists.") from None
        return self.get(cur.lastrowid)  # type: ignore[arg-type]

    def get(self, user_id: int) -> User:
        r = self.db.query_one("SELECT * FROM users WHERE id=?", (user_id,))
        if r is None:
            raise RepoError("User not found.")
        return self._row(r)

    def get_by_name(self, username: str) -> tuple[User, str] | None:
        r = self.db.query_one("SELECT * FROM users WHERE username=?", (username.strip(),))
        return (self._row(r), r["password_hash"]) if r else None

    def list(self) -> list[User]:
        return [self._row(r) for r in self.db.query("SELECT * FROM users ORDER BY username")]

    def set_password(self, user_id: int, password_hash: str, must_change: bool) -> None:
        self.db.execute("UPDATE users SET password_hash=?, must_change_password=? WHERE id=?",
                        (password_hash, int(must_change), user_id))

    def set_role(self, user_id: int, role: str) -> None:
        if role not in cfg.ROLES:
            raise RepoError("Unknown role.")
        with self.db.transaction() as c:
            cur = c.execute("SELECT role FROM users WHERE id=?", (user_id,)).fetchone()
            if cur is None:
                raise RepoError("User not found.")
            if cur["role"] == cfg.ROLE_ADMIN and role != cfg.ROLE_ADMIN and self._active_admins(c) <= 1:
                raise RepoError("At least one active administrator is required.")
            c.execute("UPDATE users SET role=? WHERE id=?", (role, user_id))

    def set_active(self, user_id: int, active: bool) -> None:
        with self.db.transaction() as c:
            cur = c.execute("SELECT role FROM users WHERE id=?", (user_id,)).fetchone()
            if cur is None:
                raise RepoError("User not found.")
            if not active and cur["role"] == cfg.ROLE_ADMIN and self._active_admins(c) <= 1:
                raise RepoError("At least one active administrator is required.")
            c.execute("UPDATE users SET active=? WHERE id=?", (int(active), user_id))

    def delete(self, user_id: int) -> None:
        with self.db.transaction() as c:
            cur = c.execute("SELECT role, active FROM users WHERE id=?", (user_id,)).fetchone()
            if cur is None:
                return
            if cur["role"] == cfg.ROLE_ADMIN and cur["active"] and self._active_admins(c) <= 1:
                raise RepoError("At least one active administrator is required.")
            c.execute("DELETE FROM users WHERE id=?", (user_id,))

    def touch_login(self, user_id: int) -> None:
        self.db.execute("UPDATE users SET last_login_at=? WHERE id=?", (utc_now(), user_id))

    @staticmethod
    def _active_admins(conn: sqlite3.Connection) -> int:
        return conn.execute("SELECT COUNT(*) FROM users WHERE role='admin' AND active=1").fetchone()[0]


# ---------------------------------------------------------------------------- spaces
class SpaceRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    # -- reading
    def _camera(self, r: sqlite3.Row) -> Camera:
        roi = _loads(r["roi"], None)
        return Camera(r["id"], r["space_id"], r["name"], r["source_type"], _loads(r["source_config"], {}),
                      [tuple(p) for p in roi] if roi else None, bool(r["enabled"]), r["position"])

    def _space(self, r: sqlite3.Row, cams: list[Camera]) -> Space:
        return Space(r["id"], r["name"], r["description"], _loads(r["plc_config"], {}),
                     _loads(r["overrides"], {}), bool(r["auto_start"]), r["created_at"], r["updated_at"], cams)

    def list(self) -> list[Space]:
        cams: dict[int, list[Camera]] = {}
        for r in self.db.query("SELECT * FROM cameras ORDER BY position, id"):
            cams.setdefault(r["space_id"], []).append(self._camera(r))
        return [self._space(r, cams.get(r["id"], [])) for r in self.db.query("SELECT * FROM spaces ORDER BY name")]

    def get(self, space_id: int) -> Space:
        r = self.db.query_one("SELECT * FROM spaces WHERE id=?", (space_id,))
        if r is None:
            raise RepoError("Space not found.")
        cams = [self._camera(c) for c in
                self.db.query("SELECT * FROM cameras WHERE space_id=? ORDER BY position, id", (space_id,))]
        return self._space(r, cams)

    def count(self) -> int:
        return self.db.query_one("SELECT COUNT(*) c FROM spaces")["c"]

    # -- validation
    @staticmethod
    def _clean_overrides(overrides: dict[str, Any]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for k, v in (overrides or {}).items():
            if k not in schema.PER_SPACE_KEYS:
                raise RepoError(f"'{k}' cannot be overridden per space.")
            try:
                out[k] = schema.coerce(k, v)
            except ValueError as exc:
                raise RepoError(str(exc)) from None
        return out

    @staticmethod
    def _validate_cameras(cameras: Iterable[Camera]) -> list[Camera]:
        cams = list(cameras)
        if len(cams) > cfg.MAX_CAMERAS_PER_SPACE:
            raise RepoError(f"A space supports at most {cfg.MAX_CAMERAS_PER_SPACE} cameras.")
        names = set()
        for c in cams:
            nm = c.name.strip()
            if not nm:
                raise RepoError("Every camera needs a name.")
            if nm.lower() in names:
                raise RepoError(f"Duplicate camera name '{nm}' in this space.")
            names.add(nm.lower())
            errs = validate_source(c.source_type, c.source_config)
            if errs:
                raise RepoError(f"Camera '{nm}': {errs[0]}")
            if c.roi is not None:
                if len(c.roi) < 3 or any(not (0.0 <= x <= 1.0 and 0.0 <= y <= 1.0) for x, y in c.roi):
                    raise RepoError(f"Camera '{nm}': region of interest needs 3+ points inside the picture.")
        return cams

    @staticmethod
    def _validate_name(name: str) -> str:
        name = name.strip()
        if not (1 <= len(name) <= 60):
            raise RepoError("Space name must be 1-60 characters.")
        return name

    # -- writing
    def save(self, space: Space) -> Space:
        """Insert (id == 0) or update a space together with its cameras, atomically."""
        name = self._validate_name(space.name)
        overrides = self._clean_overrides(space.overrides)
        cams = self._validate_cameras(space.cameras)
        now = utc_now()
        try:
            with self.db.transaction() as c:
                if space.id == 0:
                    if c.execute("SELECT COUNT(*) FROM spaces").fetchone()[0] >= cfg.MAX_SPACES:
                        raise RepoError(f"The maximum of {cfg.MAX_SPACES} spaces has been reached.")
                    cur = c.execute(
                        "INSERT INTO spaces(name,description,plc_config,overrides,auto_start,created_at,updated_at)"
                        " VALUES(?,?,?,?,?,?,?)",
                        (name, space.description.strip(), json.dumps(space.plc_config), json.dumps(overrides),
                         int(space.auto_start), now, now))
                    sid = int(cur.lastrowid)
                else:
                    sid = space.id
                    cur = c.execute(
                        "UPDATE spaces SET name=?,description=?,plc_config=?,overrides=?,auto_start=?,updated_at=?"
                        " WHERE id=?",
                        (name, space.description.strip(), json.dumps(space.plc_config), json.dumps(overrides),
                         int(space.auto_start), now, sid))
                    if cur.rowcount == 0:
                        raise RepoError("Space not found.")
                keep = [cam.id for cam in cams if cam.id]
                if keep:
                    c.execute(f"DELETE FROM cameras WHERE space_id=? AND id NOT IN ({','.join('?' * len(keep))})",
                              (sid, *keep))
                else:
                    c.execute("DELETE FROM cameras WHERE space_id=?", (sid,))
                for pos, cam in enumerate(cams):
                    roi = json.dumps([list(p) for p in cam.roi]) if cam.roi else None
                    if cam.id:
                        c.execute("UPDATE cameras SET name=?,source_type=?,source_config=?,roi=?,enabled=?,position=?"
                                  " WHERE id=? AND space_id=?",
                                  (cam.name.strip(), cam.source_type, json.dumps(cam.source_config), roi,
                                   int(cam.enabled), pos, cam.id, sid))
                    else:
                        c.execute("INSERT INTO cameras(space_id,name,source_type,source_config,roi,enabled,position)"
                                  " VALUES(?,?,?,?,?,?,?)",
                                  (sid, cam.name.strip(), cam.source_type, json.dumps(cam.source_config), roi,
                                   int(cam.enabled), pos))
        except sqlite3.IntegrityError:
            raise RepoError(f"A space named '{name}' already exists.") from None
        return self.get(sid)

    def delete(self, space_id: int) -> None:
        self.db.execute("DELETE FROM spaces WHERE id=?", (space_id,))


# ---------------------------------------------------------------------------- events
class EventRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    def add(self, kind: str, message: str, *, severity: str = "info", space_id: int | None = None,
            space_name: str = "", camera_id: int | None = None, camera_name: str = "",
            snapshot_path: str | None = None) -> int:
        cur = self.db.execute(
            "INSERT INTO events(ts,day,space_id,space_name,camera_id,camera_name,kind,severity,message,snapshot_path)"
            " VALUES(?,?,?,?,?,?,?,?,?,?)",
            (utc_now(), local_day(), space_id, space_name, camera_id, camera_name, kind, severity, message,
             snapshot_path))
        return int(cur.lastrowid)

    @staticmethod
    def _row(r: sqlite3.Row) -> Event:
        return Event(r["id"], r["ts"], r["day"], r["space_id"], r["space_name"], r["camera_id"], r["camera_name"],
                     r["kind"], r["severity"], r["message"], r["snapshot_path"])

    def search(self, *, space_id: int | None = None, kinds: Iterable[str] | None = None, day: str | None = None,
               severity: str | None = None, with_snapshot: bool = False, limit: int = 500) -> list[Event]:
        where, params = ["1=1"], []
        if space_id is not None:
            where.append("space_id=?")
            params.append(space_id)
        kinds = list(kinds or [])
        if kinds:
            where.append(f"kind IN ({','.join('?' * len(kinds))})")
            params += kinds
        if day:
            where.append("day=?")
            params.append(day)
        if severity:
            where.append("severity=?")
            params.append(severity)
        if with_snapshot:
            where.append("snapshot_path IS NOT NULL")
        params.append(max(1, min(int(limit), 5000)))
        rows = self.db.query(f"SELECT * FROM events WHERE {' AND '.join(where)} ORDER BY id DESC LIMIT ?", params)
        return [self._row(r) for r in rows]

    def last_id(self) -> int:
        return self.db.query_one("SELECT COALESCE(MAX(id),0) m FROM events")["m"]

    def daily_summary(self, days: int = 7) -> list[dict[str, Any]]:
        """Violations per local day for the last N days (oldest first, zero-filled)."""
        start = (datetime.now() - timedelta(days=days - 1)).strftime("%Y-%m-%d")
        rows = self.db.query(
            "SELECT day, kind, COUNT(*) n FROM events WHERE day>=? AND kind IN ('person_violation','camera_fault') "
            "GROUP BY day, kind", (start,))
        table: dict[str, dict[str, Any]] = {}
        for i in range(days):
            d = (datetime.now() - timedelta(days=days - 1 - i)).strftime("%Y-%m-%d")
            table[d] = {"day": d, "person": 0, "camera": 0}
        for r in rows:
            if r["day"] in table:
                table[r["day"]]["person" if r["kind"] == "person_violation" else "camera"] = r["n"]
        return list(table.values())

    def per_space_today(self) -> dict[int, int]:
        rows = self.db.query("SELECT space_id, COUNT(*) n FROM events WHERE day=? AND kind='person_violation' "
                             "AND space_id IS NOT NULL GROUP BY space_id", (local_day(),))
        return {r["space_id"]: r["n"] for r in rows}

    def purge_older_than(self, days: int) -> int:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        return self.db.execute("DELETE FROM events WHERE ts<?", (cutoff,)).rowcount

    def log_audit(self, username: str, action: str, detail: str = "") -> None:
        self.db.execute("INSERT INTO audit_log(ts,username,action,detail) VALUES(?,?,?,?)",
                        (utc_now(), username, action, detail))


# --------------------------------------------------------------------------- settings
class SettingsStore:
    """Global defaults stored in the DB; per-space overrides are layered on top."""

    def __init__(self, db: Database) -> None:
        self.db = db
        self.version = 0
        self._cache: dict[str, Any] | None = None

    def all(self) -> dict[str, Any]:
        if self._cache is None:
            values = schema.defaults()
            for r in self.db.query("SELECT key,value FROM settings"):
                if r["key"] in schema.BY_KEY:
                    try:
                        values[r["key"]] = schema.coerce(r["key"], _loads(r["value"], schema.BY_KEY[r["key"]].default))
                    except ValueError:
                        log.warning("Invalid stored setting %s ignored", r["key"])
            self._cache = values
        return dict(self._cache)

    def update(self, changes: dict[str, Any]) -> None:
        clean = {}
        for k, v in changes.items():
            try:
                clean[k] = schema.coerce(k, v)
            except ValueError as exc:
                raise RepoError(str(exc)) from None
        if clean.get("siren_low_hz") is not None or clean.get("siren_high_hz") is not None:
            cur = {**self.all(), **clean}
            if cur["siren_low_hz"] >= cur["siren_high_hz"]:
                raise RepoError("Siren low tone must be lower than the high tone.")
        with self.db.transaction() as c:
            for k, v in clean.items():
                c.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                          (k, json.dumps(v)))
        self._cache = None
        self.version += 1

    def reset_all(self) -> None:
        self.db.execute("DELETE FROM settings")
        self._cache = None
        self.version += 1

    def effective(self, overrides: dict[str, Any] | None = None) -> dict[str, Any]:
        eff = self.all()
        for k, v in (overrides or {}).items():
            if k in schema.PER_SPACE_KEYS:
                try:
                    eff[k] = schema.coerce(k, v)
                except ValueError:
                    pass
        return eff
