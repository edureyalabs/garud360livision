# tests/test_app_bootstrap.py
"""Start-up / login loop / shutdown, driven headlessly."""
import os

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from garud360 import paths  # noqa: E402
from garud360.app import main  # noqa: E402
from garud360.config import defaults as cfg  # noqa: E402


@pytest.fixture(autouse=True)
def _restore_paths():
    old = paths._override
    yield
    paths._override = old


def test_version_and_reset_admin(tmp_path, capsys):
    assert main(["--version"]) == 0
    assert "Li-Vision" in capsys.readouterr().out
    assert main(["--data-dir", str(tmp_path), "--reset-admin"]) == 0
    from garud360.app import build_services
    ctx = build_services()
    assert ctx.auth.login(cfg.DEFAULT_ADMIN_USERNAME, cfg.DEFAULT_ADMIN_PASSWORD).role == "admin"
    ctx.db.close()


def test_gui_login_logout_login_quit_cycle(tmp_path, monkeypatch):
    """Sign in (forced password change) -> sign out -> sign in again -> close window -> clean shutdown."""
    from PySide6.QtCore import QTimer
    from garud360.ui.dialogs import auth_dialogs
    from garud360.ui.main_window import MainWindow

    events = []
    logins = {"n": 0}

    def fake_login_exec(self):
        logins["n"] += 1
        self.username.setText("admin")
        self.password.setText(cfg.DEFAULT_ADMIN_PASSWORD if logins["n"] == 1 else "Changed#Pass1")
        self._submit()
        return 1 if self.user else 0

    def fake_change_exec(self):
        self.old.setText(cfg.DEFAULT_ADMIN_PASSWORD)
        self.new.setText("Changed#Pass1")
        self.confirm.setText("Changed#Pass1")
        self._submit()
        events.append("changed")
        return 1

    monkeypatch.setattr(auth_dialogs.LoginDialog, "exec", fake_login_exec)
    monkeypatch.setattr(auth_dialogs.ChangePasswordDialog, "exec", fake_change_exec)
    orig_show = MainWindow.show

    def fake_show(self):
        orig_show(self)
        events.append("window")
        if logins["n"] == 1:
            QTimer.singleShot(200, self._logout_now)
        else:
            QTimer.singleShot(200, self._quit_now)

    def _logout_now(self):
        self.exit_reason, self._force_close = "logout", True
        self.close()

    def _quit_now(self):
        self.exit_reason, self._force_close = "quit", True
        self.close()

    monkeypatch.setattr(MainWindow, "show", fake_show)
    monkeypatch.setattr(MainWindow, "_logout_now", _logout_now, raising=False)
    monkeypatch.setattr(MainWindow, "_quit_now", _quit_now, raising=False)
    assert main(["--data-dir", str(tmp_path)]) == 0
    assert events == ["changed", "window", "window"]
    assert logins["n"] == 2
    assert (tmp_path / "garud360.db").exists()
    # lock released: a second start must not be refused
    logins["n"] = 1
    events.clear()
    assert main(["--data-dir", str(tmp_path)]) == 0
