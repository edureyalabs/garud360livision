# garud360/ui/dialogs/auth_dialogs.py
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout, QWidget)

from garud360 import APP_NAME, __version__
from garud360.auth.service import AuthError
from garud360.core.models import User
from garud360.ui.context import AppContext
from garud360.ui.util import app_icon, logo_pixmap


class LoginDialog(QDialog):
    def __init__(self, ctx: AppContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.ctx = ctx
        self.user: User | None = None
        self.setWindowTitle(f"{APP_NAME} - Sign in")
        self.setWindowIcon(app_icon())
        self.setFixedWidth(400)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(36, 28, 36, 28)
        lay.setSpacing(12)
        logo = QLabel()
        logo.setPixmap(logo_pixmap(white=True).scaled(120, 120, Qt.AspectRatioMode.KeepAspectRatio,
                                                      Qt.TransformationMode.SmoothTransformation))
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title = QLabel(APP_NAME)
        title.setObjectName("h1")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sub = QLabel("Crane zone safety monitoring")
        sub.setProperty("muted", True)
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(logo)
        lay.addWidget(title)
        lay.addWidget(sub)
        lay.addSpacing(10)
        self.username = QLineEdit()
        self.username.setPlaceholderText("Username")
        self.username.setMaxLength(40)
        self.password = QLineEdit()
        self.password.setPlaceholderText("Password")
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.password.setMaxLength(128)
        self.error = QLabel("")
        self.error.setStyleSheet("color: #F0524F;")
        self.error.setWordWrap(True)
        self.go = QPushButton("Sign in")
        self.go.setObjectName("primary")
        self.go.setDefault(True)
        self.go.clicked.connect(self._submit)
        for w in (self.username, self.password):
            w.returnPressed.connect(self._submit)
        lay.addWidget(self.username)
        lay.addWidget(self.password)
        lay.addWidget(self.error)
        lay.addWidget(self.go)
        ver = QLabel(f"v{__version__}")
        ver.setProperty("muted", True)
        ver.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(ver)
        self.username.setFocus()

    def _submit(self) -> None:
        try:
            self.user = self.ctx.auth.login(self.username.text(), self.password.text())
        except AuthError as exc:
            self.error.setText(str(exc))
            self.password.clear()
            self.password.setFocus()
            return
        self.accept()


class ChangePasswordDialog(QDialog):
    def __init__(self, ctx: AppContext, user: User, forced: bool = False, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.ctx, self.user, self.forced = ctx, user, forced
        self.setWindowTitle("Change password")
        self.setWindowIcon(app_icon())
        self.setMinimumWidth(400)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 20, 24, 20)
        if forced:
            note = QLabel("You are using a temporary password. Please choose a new one to continue.")
            note.setWordWrap(True)
            lay.addWidget(note)
        form = QFormLayout()
        self.old, self.new, self.confirm = QLineEdit(), QLineEdit(), QLineEdit()
        for w in (self.old, self.new, self.confirm):
            w.setEchoMode(QLineEdit.EchoMode.Password)
            w.setMaxLength(128)
        form.addRow("Current password", self.old)
        form.addRow("New password", self.new)
        form.addRow("Repeat new password", self.confirm)
        lay.addLayout(form)
        self.error = QLabel("")
        self.error.setStyleSheet("color: #F0524F;")
        self.error.setWordWrap(True)
        lay.addWidget(self.error)
        row = QHBoxLayout()
        row.addStretch(1)
        cancel = QPushButton("Sign out" if forced else "Cancel")
        cancel.clicked.connect(self.reject)
        ok = QPushButton("Change password")
        ok.setObjectName("primary")
        ok.clicked.connect(self._submit)
        row.addWidget(cancel)
        row.addWidget(ok)
        lay.addLayout(row)

    def _submit(self) -> None:
        if self.new.text() != self.confirm.text():
            self.error.setText("The new passwords do not match.")
            return
        try:
            self.ctx.auth.change_own_password(self.user, self.old.text(), self.new.text())
        except AuthError as exc:
            self.error.setText(str(exc))
            return
        self.accept()
