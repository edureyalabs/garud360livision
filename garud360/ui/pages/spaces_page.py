# garud360/ui/pages/spaces_page.py
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (QAbstractItemView, QHBoxLayout, QHeaderView, QLabel, QPushButton, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

from garud360.config import defaults as cfg
from garud360.core.plc.registry import DRIVERS
from garud360.db.repositories import RepoError
from garud360.ui.context import AppContext
from garud360.ui.dialogs.space_editor import SpaceEditorDialog
from garud360.ui.util import confirm, error_box, local_time


class SpacesPage(QWidget):
    changed = Signal()

    def __init__(self, ctx: AppContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("page")
        self.ctx = ctx
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 20, 24, 16)
        head = QHBoxLayout()
        h = QLabel("Spaces")
        h.setObjectName("h1")
        self.count = QLabel()
        self.count.setProperty("muted", True)
        head.addWidget(h)
        head.addWidget(self.count)
        head.addStretch(1)
        self.new_btn = QPushButton("+ New space")
        self.new_btn.setObjectName("primary")
        self.new_btn.clicked.connect(self._new)
        self.edit_btn = QPushButton("Edit")
        self.edit_btn.clicked.connect(self._edit)
        self.del_btn = QPushButton("Delete")
        self.del_btn.clicked.connect(self._delete)
        for b in (self.new_btn, self.edit_btn, self.del_btn):
            head.addWidget(b)
        lay.addLayout(head)
        note = QLabel("A space is one monitored area: up to 10 cameras plus one crane output channel. "
                      "Stop a space before editing it.")
        note.setProperty("muted", True)
        lay.addWidget(note)
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["Name", "Cameras", "Output channel", "Auto-start", "Status", "Created"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for i in range(1, 6):
            self.table.horizontalHeader().setSectionResizeMode(i, QHeaderView.ResizeMode.ResizeToContents)
        self.table.doubleClicked.connect(lambda _i: self._edit())
        lay.addWidget(self.table, 1)
        self._ids: list[int] = []
        self.reload()

    def reload(self) -> None:
        spaces = self.ctx.spaces.list()
        self._ids = [s.id for s in spaces]
        self.table.setRowCount(len(spaces))
        for r, s in enumerate(spaces):
            plc = DRIVERS[s.plc_config["type"]].LABEL if s.plc_config.get("type") in DRIVERS else "not set"
            running = self.ctx.runtime.is_running(s.id)
            vals = [s.name, f"{len(s.cameras)}/{cfg.MAX_CAMERAS_PER_SPACE}", plc, "Yes" if s.auto_start else "No",
                    "Running" if running else "Stopped", local_time(s.created_at, "%d %b %Y")]
            for c, v in enumerate(vals):
                self.table.setItem(r, c, QTableWidgetItem(v))
        self.count.setText(f"{len(spaces)} / {cfg.MAX_SPACES}")
        self.new_btn.setEnabled(len(spaces) < cfg.MAX_SPACES)

    def showEvent(self, e) -> None:  # noqa: N802
        super().showEvent(e)
        self.reload()

    def _selected(self) -> int | None:
        r = self.table.currentRow()
        return self._ids[r] if 0 <= r < len(self._ids) else None

    def _new(self) -> None:
        dlg = SpaceEditorDialog(self.ctx, None, self)
        if dlg.exec():
            self.reload()
            self.changed.emit()

    def _edit(self) -> None:
        sid = self._selected()
        if sid is None:
            return
        if self.ctx.runtime.is_running(sid):
            error_box(self, "Space is running", "Stop this space (Dashboard) before editing it.")
            return
        dlg = SpaceEditorDialog(self.ctx, self.ctx.spaces.get(sid), self)
        if dlg.exec():
            self.reload()
            self.changed.emit()

    def _delete(self) -> None:
        sid = self._selected()
        if sid is None:
            return
        if self.ctx.runtime.is_running(sid):
            error_box(self, "Space is running", "Stop this space before deleting it.")
            return
        sp = self.ctx.spaces.get(sid)
        if confirm(self, "Delete space", f"Delete '{sp.name}' and its {len(sp.cameras)} camera(s)?\n"
                                          "The event history is kept.", True):
            try:
                self.ctx.spaces.delete(sid)
                self.ctx.events.log_audit(self.ctx.username, "space_deleted", sp.name)
            except RepoError as exc:
                error_box(self, "Delete", str(exc))
            self.reload()
            self.changed.emit()
