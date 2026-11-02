# garud360/ui/context.py
"""Application-wide services handed to every page."""
from __future__ import annotations

from dataclasses import dataclass

from garud360.auth.service import AuthService
from garud360.core.models import User
from garud360.core.runtime import RuntimeManager
from garud360.db.database import Database
from garud360.db.repositories import EventRepository, SettingsStore, SpaceRepository, UserRepository
from garud360.config import defaults as cfg


@dataclass
class AppContext:
    db: Database
    users: UserRepository
    spaces: SpaceRepository
    events: EventRepository
    settings: SettingsStore
    auth: AuthService
    runtime: RuntimeManager
    user: User | None = None

    @property
    def is_admin(self) -> bool:
        return bool(self.user and self.user.role == cfg.ROLE_ADMIN)

    @property
    def username(self) -> str:
        return self.user.username if self.user else ""
