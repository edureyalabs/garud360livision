# garud360/ui/util.py
"""Small Qt helpers shared by pages and dialogs."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np
from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal
from PySide6.QtGui import QIcon, QImage, QPixmap
from PySide6.QtWidgets import QMessageBox, QWidget

from garud360 import paths


def bgr_to_qimage(bgr: np.ndarray) -> QImage:
    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    h, w, _ = rgb.shape
    return QImage(rgb.data, w, h, 3 * w, QImage.Format.Format_RGB888).copy()


def bgr_to_pixmap(bgr: np.ndarray) -> QPixmap:
    return QPixmap.fromImage(bgr_to_qimage(bgr))


def app_icon() -> QIcon:
    p = paths.resource_path("assets/icon.ico")
    if not p.exists():
        p = paths.resource_path("assets/logo.png")
    return QIcon(str(p))


def logo_pixmap(white: bool = False) -> QPixmap:
    return QPixmap(str(paths.resource_path("assets/logo_white.png" if white else "assets/logo.png")))


def local_time(iso_utc: str, fmt: str = "%d %b %H:%M:%S") -> str:
    try:
        dt = datetime.strptime(iso_utc, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc)
        return dt.astimezone().strftime(fmt)
    except ValueError:
        return iso_utc


def error_box(parent: QWidget | None, title: str, text: str) -> None:
    QMessageBox.warning(parent, title, text)


def info_box(parent: QWidget | None, title: str, text: str) -> None:
    QMessageBox.information(parent, title, text)


def confirm(parent: QWidget | None, title: str, text: str, danger: bool = False) -> bool:
    box = QMessageBox(QMessageBox.Icon.Warning if danger else QMessageBox.Icon.Question, title, text,
                      QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, parent)
    box.setDefaultButton(QMessageBox.StandardButton.No)
    return box.exec() == QMessageBox.StandardButton.Yes


def snapshot_file(rel: str | None) -> Path | None:
    if not rel:
        return None
    p = (paths.snapshots_dir() / rel).resolve()
    try:
        p.relative_to(paths.snapshots_dir().resolve())      # never follow a path outside the snapshot folder
    except ValueError:
        return None
    return p if p.exists() else None


class _Signals(QObject):
    done = Signal(object)
    failed = Signal(str)


class Task(QRunnable):
    """Run a blocking function on the global thread pool and report back on the GUI thread."""

    def __init__(self, fn, *args) -> None:
        super().__init__()
        self.fn, self.args = fn, args
        self.signals = _Signals()

    def run(self) -> None:
        try:
            self.signals.done.emit(self.fn(*self.args))
        except Exception as exc:  # noqa: BLE001
            self.signals.failed.emit(f"{type(exc).__name__}: {exc}")


def run_task(fn, on_done, on_fail=None, *args) -> Task:
    t = Task(fn, *args)
    t.setAutoDelete(False)
    t.signals.done.connect(on_done)
    if on_fail:
        t.signals.failed.connect(on_fail)
    QThreadPool.globalInstance().start(t)
    return t
