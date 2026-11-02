# garud360/auth/service.py
"""Local username/password authentication (bcrypt). No cloud providers."""
from __future__ import annotations

import logging
import threading
import time

import bcrypt

from garud360.config import defaults as cfg
from garud360.core.models import User
from garud360.db.repositories import EventRepository, RepoError, UserRepository

log = logging.getLogger(__name__)


class AuthError(Exception):
    """Raised with a message that is safe to show to the user."""


class AuthService:
    def __init__(self, users: UserRepository, audit: EventRepository) -> None:
        self.users = users
        self.audit = audit
        self._fail: dict[str, tuple[int, float]] = {}   # username -> (count, locked_until)
        self._lock = threading.Lock()

    # -- hashing ---------------------------------------------------------------
    @staticmethod
    def hash_password(password: str) -> str:
        return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("ascii")

    @staticmethod
    def verify_password(password: str, hashed: str) -> bool:
        try:
            return bcrypt.checkpw(password.encode("utf-8")[: cfg.MAX_PASSWORD_BYTES], hashed.encode("ascii"))
        except (ValueError, TypeError):
            return False

    @staticmethod
    def validate_new_password(password: str) -> None:
        if len(password) < cfg.MIN_PASSWORD_LENGTH:
            raise AuthError(f"Password must be at least {cfg.MIN_PASSWORD_LENGTH} characters.")
        if len(password.encode("utf-8")) > cfg.MAX_PASSWORD_BYTES:
            raise AuthError(f"Password is too long (maximum {cfg.MAX_PASSWORD_BYTES} bytes).")

    # -- first run -------------------------------------------------------------
    def ensure_default_admin(self) -> bool:
        """Create the factory admin when there are no users. Returns True if created."""
        if self.users.count() > 0:
            return False
        self.users.create(cfg.DEFAULT_ADMIN_USERNAME, self.hash_password(cfg.DEFAULT_ADMIN_PASSWORD),
                          cfg.ROLE_ADMIN, cfg.FORCE_PASSWORD_CHANGE_ON_FIRST_LOGIN)
        log.warning("Created default administrator '%s'.", cfg.DEFAULT_ADMIN_USERNAME)
        return True

    def reset_default_admin(self) -> None:
        """Recovery: restore the factory admin account and password (CLI --reset-admin)."""
        found = self.users.get_by_name(cfg.DEFAULT_ADMIN_USERNAME)
        h = self.hash_password(cfg.DEFAULT_ADMIN_PASSWORD)
        if found is None:
            self.users.create(cfg.DEFAULT_ADMIN_USERNAME, h, cfg.ROLE_ADMIN, cfg.FORCE_PASSWORD_CHANGE_ON_FIRST_LOGIN)
        else:
            user, _ = found
            self.users.set_password(user.id, h, cfg.FORCE_PASSWORD_CHANGE_ON_FIRST_LOGIN)
            self.users.set_active(user.id, True)
            self.users.set_role(user.id, cfg.ROLE_ADMIN)
        self.audit.log_audit("system", "reset_admin", cfg.DEFAULT_ADMIN_USERNAME)

    # -- login -----------------------------------------------------------------
    def login(self, username: str, password: str) -> User:
        key = username.strip().lower()
        now = time.monotonic()
        with self._lock:
            count, until = self._fail.get(key, (0, 0.0))
            if until > now:
                raise AuthError(f"Too many failed attempts. Try again in {int(until - now) + 1} s.")
        found = self.users.get_by_name(username) if username.strip() else None
        # Always run a hash comparison so timing does not reveal whether the user exists.
        stored = found[1] if found else "$2b$12$" + "." * 53
        ok = self.verify_password(password, stored) and found is not None and found[0].active
        if not ok:
            with self._lock:
                count += 1
                until = now + cfg.LOGIN_LOCKOUT_SECONDS if count >= cfg.LOGIN_MAX_ATTEMPTS else 0.0
                self._fail[key] = (0 if until else count, until)
            self.audit.log_audit(username.strip() or "?", "login_failed")
            raise AuthError("Incorrect username or password.")
        with self._lock:
            self._fail.pop(key, None)
        user = found[0]  # type: ignore[index]
        self.users.touch_login(user.id)
        self.audit.log_audit(user.username, "login")
        return user

    # -- password changes ------------------------------------------------------
    def change_own_password(self, user: User, old: str, new: str) -> None:
        found = self.users.get_by_name(user.username)
        if found is None or not self.verify_password(old, found[1]):
            raise AuthError("Current password is incorrect.")
        self.validate_new_password(new)
        if self.verify_password(new, found[1]):
            raise AuthError("The new password must be different from the current one.")
        self.users.set_password(user.id, self.hash_password(new), False)
        self.audit.log_audit(user.username, "password_changed")

    def admin_set_password(self, actor: User, target_id: int, new: str, must_change: bool = True) -> None:
        self._require_admin(actor)
        self.validate_new_password(new)
        self.users.set_password(target_id, self.hash_password(new), must_change)
        self.audit.log_audit(actor.username, "password_reset", f"user_id={target_id}")

    # -- user management (admin only) -----------------------------------------
    def create_user(self, actor: User, username: str, password: str, role: str) -> User:
        self._require_admin(actor)
        self.validate_new_password(password)
        try:
            user = self.users.create(username, self.hash_password(password), role, True)
        except RepoError as exc:
            raise AuthError(str(exc)) from None
        self.audit.log_audit(actor.username, "user_created", f"{user.username} ({role})")
        return user

    def delete_user(self, actor: User, target_id: int) -> None:
        self._require_admin(actor)
        if actor.id == target_id:
            raise AuthError("You cannot delete your own account.")
        try:
            self.users.delete(target_id)
        except RepoError as exc:
            raise AuthError(str(exc)) from None
        self.audit.log_audit(actor.username, "user_deleted", f"user_id={target_id}")

    def set_role(self, actor: User, target_id: int, role: str) -> None:
        self._require_admin(actor)
        try:
            self.users.set_role(target_id, role)
        except RepoError as exc:
            raise AuthError(str(exc)) from None
        self.audit.log_audit(actor.username, "role_changed", f"user_id={target_id} -> {role}")

    def set_active(self, actor: User, target_id: int, active: bool) -> None:
        self._require_admin(actor)
        if actor.id == target_id and not active:
            raise AuthError("You cannot disable your own account.")
        try:
            self.users.set_active(target_id, active)
        except RepoError as exc:
            raise AuthError(str(exc)) from None
        self.audit.log_audit(actor.username, "user_active", f"user_id={target_id} -> {active}")

    @staticmethod
    def _require_admin(actor: User) -> None:
        if actor.role != cfg.ROLE_ADMIN:
            raise AuthError("Administrator rights are required.")
