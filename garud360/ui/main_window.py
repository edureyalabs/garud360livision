# garud360/ui/main_window.py
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QPushButton, QStackedWidget, QVBoxLayout, QWidget)

from garud360 import APP_NAME, __version__
from garud360.ui.context import AppContext
from garud360.ui.dialogs.auth_dialogs import ChangePasswordDialog
from garud360.ui.pages.dashboard import DashboardPage
from garud360.ui.pages.events_page import EventsPage
from garud360.ui.pages.lidar_page import LidarPage
from garud360.ui.pages.settings_page import SettingsPage
from garud360.ui.pages.spaces_page import SpacesPage
from garud360.ui.pages.users_page import UsersPage
from garud360.ui.theme import C
from garud360.ui.util import app_icon, confirm, info_box, logo_pixmap


class MainWindow(QWidget):
    closed = Signal()

    def __init__(self, ctx: AppContext) -> None:
        super().__init__()
        self.ctx = ctx
        self.setObjectName("page")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.exit_reason = "quit"
        self._force_close = False
        self.setWindowTitle(f"{APP_NAME}  v{__version__}")
        self.setWindowIcon(app_icon())
        self.resize(1400, 860)
        self.setMinimumSize(1100, 680)
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        nav = QFrame()
        nav.setObjectName("nav")
        nav.setFixedWidth(220)
        nl = QVBoxLayout(nav)
        nl.setContentsMargins(12, 16, 12, 12)
        logo = QLabel()
        logo.setPixmap(logo_pixmap(white=True).scaled(72, 72, Qt.AspectRatioMode.KeepAspectRatio,
                                                      Qt.TransformationMode.SmoothTransformation))
        name = QLabel("Garud 360\nLi-Vision")
        name.setStyleSheet("font-size: 16px; font-weight: 700;")
        top = QHBoxLayout()
        top.addWidget(logo)
        top.addWidget(name, 1)
        nl.addLayout(top)
        nl.addSpacing(14)

        self.stack = QStackedWidget()
        self.dashboard = DashboardPage(ctx)
        self.spaces = SpacesPage(ctx)
        self.events = EventsPage(ctx)
        self.lidar = LidarPage()
        self.settings = SettingsPage(ctx)
        self.users = UsersPage(ctx)
        self.spaces.changed.connect(self.dashboard.reload)
        pages = [("Dashboard", self.dashboard, False), ("Spaces", self.spaces, True), ("Events", self.events, False),
                 ("LiDAR", self.lidar, False), ("Settings", self.settings, True), ("Users", self.users, True)]
        self.nav_buttons: list[QPushButton] = []
        for label, page, admin_only in pages:
            if admin_only and not ctx.is_admin:
                continue
            idx = self.stack.addWidget(page)
            b = QPushButton(label)
            b.setObjectName("nav")
            b.setCheckable(True)
            b.setAutoExclusive(True)
            b.clicked.connect(lambda _c, i=idx: self.stack.setCurrentIndex(i))
            nl.addWidget(b)
            self.nav_buttons.append(b)
        self.nav_buttons[0].setChecked(True)
        nl.addStretch(1)
        who = QLabel(f"Signed in as\n<b>{ctx.username}</b> ({ctx.user.role if ctx.user else ''})")
        who.setTextFormat(Qt.TextFormat.RichText)
        who.setProperty("muted", True)
        nl.addWidget(who)
        pw = QPushButton("Change password")
        pw.clicked.connect(self._change_pw)
        out = QPushButton("Sign out")
        out.clicked.connect(self._logout)
        nl.addWidget(pw)
        nl.addWidget(out)
        root.addWidget(nav)

        right = QVBoxLayout()
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(0)
        self.alarm = QFrame()
        self.alarm.setStyleSheet(f"background: {C['crit']}; border: none;")
        al = QHBoxLayout(self.alarm)
        al.setContentsMargins(20, 8, 20, 8)
        self.alarm_text = QLabel("")
        self.alarm_text.setStyleSheet("color: white; font-weight: 700; font-size: 14px;")
        self.silence = QPushButton("Silence siren")
        self.silence.clicked.connect(lambda: self.ctx.runtime.siren.mute())
        al.addWidget(self.alarm_text, 1)
        al.addWidget(self.silence)
        self.alarm.setVisible(False)
        right.addWidget(self.alarm)
        right.addWidget(self.stack, 1)
        root.addLayout(right, 1)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._poll_alarms)
        self.timer.start(400)

    # ------------------------------------------------------------------------------
    def _poll_alarms(self) -> None:
        snaps = self.ctx.runtime.snapshots()
        msgs = []
        for s in snaps.values():
            if s.running and (s.alarm or s.siren):
                text = s.status if s.alarm and not (s.plc_error and not s.plc_connected and not s.latched
                                                    and s.status == "CLEAR") else "PLC LINK DOWN"
                if not s.plc_connected and s.running and s.status in ("CLEAR", "PAUSED"):
                    text = "PLC LINK DOWN - crane not interlocked"
                msgs.append(f"{s.name}: {text}")
        self.alarm.setVisible(bool(msgs))
        if msgs:
            self.alarm_text.setText("\u26A0  ALARM  |  " + "   |   ".join(msgs[:3]) + (f"   (+{len(msgs) - 3} more)"
                                                                                 if len(msgs) > 3 else ""))
            self.silence.setVisible(self.ctx.runtime.siren.playing and not self.ctx.runtime.siren.muted)

    def _change_pw(self) -> None:
        if ChangePasswordDialog(self.ctx, self.ctx.user, False, self).exec():  # type: ignore[arg-type]
            info_box(self, "Password", "Your password was changed.")

    def _logout(self) -> None:
        running = bool(self.ctx.runtime.snapshots())
        msg = "Sign out? Monitoring keeps running in the background." if running else "Sign out?"
        if confirm(self, "Sign out", msg):
            self.exit_reason = "logout"
            self._force_close = True
            self.close()

    def closeEvent(self, e) -> None:  # noqa: N802
        if not self._force_close:
            running = bool(self.ctx.runtime.snapshots())
            text = ("Close Garud 360 Li-Vision?\n\nAll running spaces will STOP monitoring. Depending on each space's "
                    "settings, cranes are blocked when monitoring stops." if running else "Close Garud 360 Li-Vision?")
            if not confirm(self, "Exit", text, running):
                e.ignore()
                return
            self.exit_reason = "quit"
        self.timer.stop()
        e.accept()
        self.closed.emit()
