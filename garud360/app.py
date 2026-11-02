# garud360/app.py
"""Application bootstrap: logging, services, login loop, main window."""
from __future__ import annotations

import argparse
import faulthandler
import logging
import logging.handlers
import os
import sys
import threading
import traceback

from garud360 import APP_ID, APP_NAME, __version__, paths

log = logging.getLogger("garud360")


def setup_logging() -> None:
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    for h in list(root.handlers):                    # idempotent: drop handlers from an earlier call
        if getattr(h, "_garud", False):
            root.removeHandler(h)
            h.close()
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    fh = logging.handlers.RotatingFileHandler(paths.logs_dir() / "garud360.log", maxBytes=5_000_000, backupCount=5,
                                              encoding="utf-8")
    fh.setFormatter(fmt)
    fh._garud = True  # type: ignore[attr-defined]
    root.addHandler(fh)
    if sys.stderr is not None:
        sh = logging.StreamHandler(sys.stderr)
        sh.setFormatter(fmt)
        sh._garud = True  # type: ignore[attr-defined]
        root.addHandler(sh)
    try:
        faulthandler.enable(open(paths.logs_dir() / "crash.log", "a"))
    except Exception:  # noqa: BLE001
        pass
    logging.getLogger("asyncua").setLevel(logging.WARNING)
    logging.getLogger("snap7").setLevel(logging.WARNING)


def build_services():
    """Create database, repositories, auth and runtime (no Qt needed)."""
    from garud360.auth.service import AuthService
    from garud360.core.runtime import RuntimeManager
    from garud360.db.database import Database
    from garud360.db.repositories import EventRepository, SettingsStore, SpaceRepository, UserRepository
    from garud360.ui.context import AppContext

    db = Database(paths.db_path())
    users, spaces, events, settings = UserRepository(db), SpaceRepository(db), EventRepository(db), SettingsStore(db)
    auth = AuthService(users, events)
    auth.ensure_default_admin()
    runtime = RuntimeManager(spaces, events, settings, paths.snapshots_dir(), paths.data_dir())
    return AppContext(db, users, spaces, events, settings, auth, runtime)


def _prepare_environment() -> None:
    # RTSP over TCP is far more reliable than UDP on site networks
    os.environ.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS", "rtsp_transport;tcp")
    os.environ.setdefault("OPENCV_LOG_LEVEL", "ERROR")
    if getattr(sys, "frozen", False):
        os.environ.setdefault("YOLO_AUTOINSTALL", "False")       # never pip-install at run time
    os.environ.setdefault("YOLO_OFFLINE_UPDATE_CHECK", "0")
    if os.environ.get("GARUD360_PRELOAD_TORCH", "1") == "1":
        # On Windows PyTorch must be imported BEFORE Qt, otherwise its DLLs can fail to initialise (WinError 1114).
        try:
            import torch  # noqa: F401
        except Exception as exc:  # noqa: BLE001
            log.warning("PyTorch not available yet: %s", exc)


def _install_excepthooks() -> None:
    def hook(exc_type, exc, tb) -> None:
        log.critical("Unhandled exception:\n%s", "".join(traceback.format_exception(exc_type, exc, tb)))

    def thread_hook(args) -> None:
        log.critical("Unhandled exception in thread %s:\n%s", args.thread.name if args.thread else "?",
                     "".join(traceback.format_exception(args.exc_type, args.exc_value, args.exc_traceback)))

    sys.excepthook = hook
    threading.excepthook = thread_hook


def _run_gui() -> int:
    from PySide6.QtCore import QEventLoop, QLockFile
    from PySide6.QtWidgets import QApplication, QMessageBox

    from garud360.ui import theme
    from garud360.ui.dialogs.auth_dialogs import ChangePasswordDialog, LoginDialog
    from garud360.ui.main_window import MainWindow
    from garud360.ui.util import app_icon

    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(f"Garud.{APP_ID}")   # taskbar icon
        except Exception:  # noqa: BLE001
            pass
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setQuitOnLastWindowClosed(False)
    app.setWindowIcon(app_icon())
    theme.apply(app)

    lock = QLockFile(str(paths.lock_path()))
    lock.setStaleLockTime(0)
    if not lock.tryLock(200):
        QMessageBox.warning(None, APP_NAME, "Garud 360 Li-Vision is already running on this PC.\n"
                                            "Two copies must never control the same cranes.")
        return 1

    ctx = build_services()
    ctx.runtime.start()
    code = 0
    try:
        for msg in _autostart(ctx):
            log.warning("Auto-start: %s", msg)
        while True:
            dlg = LoginDialog(ctx)
            if not dlg.exec() or dlg.user is None:
                break
            ctx.user = dlg.user
            if ctx.user.must_change_password:
                if not ChangePasswordDialog(ctx, ctx.user, True).exec():
                    ctx.user = None
                    continue
            win = MainWindow(ctx)
            loop = QEventLoop()
            win.closed.connect(loop.quit)
            win.show()
            loop.exec()
            reason = win.exit_reason
            win.deleteLater()
            ctx.user = None
            if reason != "logout":
                break
    finally:
        log.info("Shutting down ...")
        ctx.runtime.shutdown()
        ctx.db.close()
        lock.unlock()
    return code


def _autostart(ctx) -> list[str]:
    try:
        return ctx.runtime.start_all(only_auto=True)
    except Exception as exc:  # noqa: BLE001
        log.exception("Auto-start failed")
        return [str(exc)]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="garud360", description=f"{APP_NAME} {__version__}")
    parser.add_argument("--version", action="store_true", help="print the version and exit")
    parser.add_argument("--data-dir", help="store database, logs and snapshots in this folder")
    parser.add_argument("--reset-admin", action="store_true",
                        help="restore the factory admin account/password (see garud360/config/defaults.py) and exit")
    args = parser.parse_args(argv)
    if args.version:
        print(f"{APP_NAME} {__version__}")
        return 0
    if args.data_dir:
        paths.set_data_dir(args.data_dir)
    setup_logging()
    _install_excepthooks()
    log.info("%s %s starting (data dir: %s)", APP_NAME, __version__, paths.data_dir())
    if args.reset_admin:
        from garud360.config import defaults as cfg
        ctx = build_services()
        ctx.auth.reset_default_admin()
        print(f"Administrator '{cfg.DEFAULT_ADMIN_USERNAME}' restored to the factory password "
              f"(see garud360/config/defaults.py).")
        return 0
    _prepare_environment()
    return _run_gui()
