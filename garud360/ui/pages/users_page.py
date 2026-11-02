# garud360/ui/pages/users_page.py
from __future__ import annotations

from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QDialog, QFormLayout, QHBoxLayout, QHeaderView, QInputDialog,
                               QLabel, QLineEdit, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from garud360.auth.service import AuthError
from garud360.config import defaults as cfg
from garud360.ui.context import AppContext
from garud360.ui.dialogs.auth_dialogs import ChangePasswordDialog
from garud360.ui.util import app_icon, confirm, error_box, info_box, local_time


class NewUserDialog(QDialog):
    def __init__(self, ctx: AppContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.ctx = ctx
        self.setWindowTitle("New user")
        self.setWindowIcon(app_icon())
        self.setMinimumWidth(380)
        lay = QVBoxLayout(self)
        form = QFormLayout()
        self.name, self.pw = QLineEdit(), QLineEdit()
        self.pw.setEchoMode(QLineEdit.EchoMode.Password)
        self.role = QComboBox()
        self.role.addItem("Operator (monitor, pause, reset)", cfg.ROLE_OPERATOR)
        self.role.addItem("Administrator (everything)", cfg.ROLE_ADMIN)
        form.addRow("Username", self.name)
        form.addRow("Temporary password", self.pw)
        form.addRow("Role", self.role)
        lay.addLayout(form)
        self.err = QLabel("")
        self.err.setStyleSheet("color:#F0524F;")
        self.err.setWordWrap(True)
        lay.addWidget(self.err)
        row = QHBoxLayout()
        row.addStretch(1)
        c = QPushButton("Cancel")
        c.clicked.connect(self.reject)
        ok = QPushButton("Create user")
        ok.setObjectName("primary")
        ok.clicked.connect(self._ok)
        row.addWidget(c)
        row.addWidget(ok)
        lay.addLayout(row)

    def _ok(self) -> None:
        try:
            self.ctx.auth.create_user(self.ctx.user, self.name.text(), self.pw.text(), self.role.currentData())  # type: ignore[arg-type]
        except AuthError as exc:
            self.err.setText(str(exc))
            return
        self.accept()


class UsersPage(QWidget):
    def __init__(self, ctx: AppContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("page")
        self.ctx = ctx
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 20, 24, 16)
        head = QHBoxLayout()
        h = QLabel("Users")
        h.setObjectName("h1")
        head.addWidget(h)
        head.addStretch(1)
        self.btns: list[QPushButton] = []
        for text, fn, name in (("+ New user", self._new, "primary"), ("Reset password", self._reset_pw, ""),
                               ("Change role", self._role, ""), ("Enable / disable", self._toggle, ""),
                               ("Delete", self._delete, ""), ("My password", self._mine, "")):
            b = QPushButton(text)
            if name:
                b.setObjectName(name)
            b.clicked.connect(fn)
            head.addWidget(b)
        lay.addLayout(head)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Username", "Role", "Active", "Last sign-in", "Password"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        lay.addWidget(self.table, 1)
        self._ids: list[int] = []
        self.reload()

    def showEvent(self, e) -> None:  # noqa: N802
        super().showEvent(e)
        self.reload()

    def reload(self) -> None:
        users = self.ctx.users.list()
        self._ids = [u.id for u in users]
        self.table.setRowCount(len(users))
        for r, u in enumerate(users):
            vals = [u.username, u.role.capitalize(), "Yes" if u.active else "No",
                    local_time(u.last_login_at) if u.last_login_at else "never",
                    "must change" if u.must_change_password else "ok"]
            for c, v in enumerate(vals):
                self.table.setItem(r, c, QTableWidgetItem(v))

    def _sel(self) -> int | None:
        r = self.table.currentRow()
        return self._ids[r] if 0 <= r < len(self._ids) else None

    def _do(self, fn) -> None:
        try:
            fn()
        except AuthError as exc:
            error_box(self, "Users", str(exc))
        self.reload()

    def _new(self) -> None:
        NewUserDialog(self.ctx, self).exec()
        self.reload()

    def _reset_pw(self) -> None:
        uid = self._sel()
        if uid is None:
            return
        pw, ok = QInputDialog.getText(self, "Reset password", "New temporary password (user must change it at next sign-in):",
                                      QLineEdit.EchoMode.Password)
        if ok:
            self._do(lambda: self.ctx.auth.admin_set_password(self.ctx.user, uid, pw))  # type: ignore[arg-type]

    def _role(self) -> None:
        uid = self._sel()
        if uid is None:
            return
        cur = self.ctx.users.get(uid).role
        new = cfg.ROLE_OPERATOR if cur == cfg.ROLE_ADMIN else cfg.ROLE_ADMIN
        if confirm(self, "Change role", f"Change role to {new}?"):
            self._do(lambda: self.ctx.auth.set_role(self.ctx.user, uid, new))  # type: ignore[arg-type]

    def _toggle(self) -> None:
        uid = self._sel()
        if uid is not None:
            active = self.ctx.users.get(uid).active
            self._do(lambda: self.ctx.auth.set_active(self.ctx.user, uid, not active))  # type: ignore[arg-type]

    def _delete(self) -> None:
        uid = self._sel()
        if uid is not None and confirm(self, "Delete user", "Delete this user permanently?", True):
            self._do(lambda: self.ctx.auth.delete_user(self.ctx.user, uid))  # type: ignore[arg-type]

    def _mine(self) -> None:
        if ChangePasswordDialog(self.ctx, self.ctx.user, False, self).exec():  # type: ignore[arg-type]
            info_box(self, "Password", "Your password was changed.")
