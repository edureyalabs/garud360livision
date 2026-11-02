# garud360/ui/pages/events_page.py
"""Event log, violation snapshots and daily violation summary."""
from __future__ import annotations

import csv

from PySide6.QtCore import QDate, Qt, QTimer
from PySide6.QtGui import QColor, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDateEdit, QFileDialog, QHBoxLayout, QHeaderView,
                               QLabel, QPushButton, QSplitter, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from garud360.core import models as m
from garud360.ui.context import AppContext
from garud360.ui.theme import C
from garud360.ui.util import error_box, local_time, snapshot_file
from garud360.ui.widgets.common import BarChart

KIND_FILTERS = {
    "All events": None,
    "Person violations": [m.EV_PERSON],
    "Camera faults": [m.EV_CAM_FAULT, m.EV_CAM_OK],
    "Crane block / release": [m.EV_BLOCKED, m.EV_RELEASED],
    "PLC link": [m.EV_PLC_FAULT, m.EV_PLC_OK],
    "Operator actions": [m.EV_PAUSED, m.EV_RESUMED, m.EV_RESET],
    "Start / stop": [m.EV_STARTED, m.EV_STOPPED],
}
SEV_COLOR = {m.SEV_CRIT: C["crit"], m.SEV_WARN: C["warn"], m.SEV_INFO: C["text"]}


def _safe(v: str) -> str:
    """Neutralise spreadsheet formula injection (cells starting with = + - @)."""
    return "'" + v if v[:1] in ("=", "+", "-", "@", "\t", "\r") else v


class EventsPage(QWidget):
    def __init__(self, ctx: AppContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("page")
        self.ctx = ctx
        self._last_id = -1
        self._events: list[m.Event] = []
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 20, 24, 16)
        h = QLabel("Events & violations")
        h.setObjectName("h1")
        lay.addWidget(h)
        sumrow = QHBoxLayout()
        self.chart = BarChart()
        sumrow.addWidget(self.chart, 1)
        self.legend = QLabel()
        self.legend.setTextFormat(Qt.TextFormat.RichText)
        sumrow.addWidget(self.legend)
        lay.addWidget(QLabel("Daily violation summary (last 7 days)"))
        lay.addLayout(sumrow)
        bar = QHBoxLayout()
        self.space = QComboBox()
        self.kind = QComboBox()
        self.kind.addItems(list(KIND_FILTERS))
        self.use_day = QCheckBox("Day:")
        self.day = QDateEdit(QDate.currentDate())
        self.day.setCalendarPopup(True)
        self.snap_only = QCheckBox("With snapshot only")
        export = QPushButton("Export CSV")
        export.clicked.connect(self._export)
        for w in (self.space, self.kind, self.use_day, self.day, self.snap_only):
            bar.addWidget(w)
        bar.addStretch(1)
        bar.addWidget(export)
        lay.addLayout(bar)
        for sig in (self.space.currentIndexChanged, self.kind.currentIndexChanged, self.use_day.toggled,
                    self.snap_only.toggled, self.day.dateChanged):
            sig.connect(lambda *_: self.refresh(force=True))
        split = QSplitter(Qt.Orientation.Horizontal)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Time", "Space", "Camera", "Event", "Details"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        for i in range(4):
            hh.setSectionResizeMode(i, QHeaderView.ResizeMode.ResizeToContents)
        self.table.itemSelectionChanged.connect(self._show_snapshot)
        split.addWidget(self.table)
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(8, 0, 0, 0)
        rl.addWidget(QLabel("Violation snapshot"))
        self.img = QLabel("Select an event with a snapshot")
        self.img.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.img.setMinimumWidth(360)
        self.img.setStyleSheet("background:#070A14; border-radius:8px;")
        rl.addWidget(self.img, 1)
        split.addWidget(right)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 2)
        lay.addWidget(split, 1)
        self.timer = QTimer(self)
        self.timer.timeout.connect(lambda: self.refresh())

    def showEvent(self, e) -> None:  # noqa: N802
        super().showEvent(e)
        self._fill_spaces()
        self.refresh(force=True)
        self.timer.start(1500)

    def hideEvent(self, e) -> None:  # noqa: N802
        super().hideEvent(e)
        self.timer.stop()

    def _fill_spaces(self) -> None:
        cur = self.space.currentData()
        self.space.blockSignals(True)
        self.space.clear()
        self.space.addItem("All spaces", None)
        for s in self.ctx.spaces.list():
            self.space.addItem(s.name, s.id)
        i = self.space.findData(cur)
        self.space.setCurrentIndex(max(i, 0))
        self.space.blockSignals(False)

    def refresh(self, force: bool = False) -> None:
        last = self.ctx.events.last_id()
        if last == self._last_id and not force:
            return
        self._last_id = last
        day = self.day.date().toString("yyyy-MM-dd") if self.use_day.isChecked() else None
        self._events = self.ctx.events.search(space_id=self.space.currentData(), kinds=KIND_FILTERS[self.kind.currentText()],
                                              day=day, with_snapshot=self.snap_only.isChecked(), limit=500)
        self.table.setRowCount(len(self._events))
        for r, e in enumerate(self._events):
            vals = [local_time(e.ts), e.space_name, e.camera_name, e.kind.replace("_", " "), e.message]
            for c, v in enumerate(vals):
                it = QTableWidgetItem(v)
                it.setForeground(QColor(SEV_COLOR.get(e.severity, C["text"])))
                self.table.setItem(r, c, it)
        summary = self.ctx.events.daily_summary(7)
        self.chart.set_data(summary)
        self.legend.setText(f"<span style='color:{C['crit']}'>&#9632;</span> Person violations: "
                            f"<b>{sum(d['person'] for d in summary)}</b><br>"
                            f"<span style='color:{C['warn']}'>&#9632;</span> Camera faults: "
                            f"<b>{sum(d['camera'] for d in summary)}</b><br>"
                            f"Today: <b>{summary[-1]['person']}</b> violation(s)")

    def _show_snapshot(self) -> None:
        r = self.table.currentRow()
        if not (0 <= r < len(self._events)):
            return
        p = snapshot_file(self._events[r].snapshot_path)
        if p is None:
            self.img.setPixmap(QPixmap())
            self.img.setText("No snapshot for this event")
            return
        pix = QPixmap(str(p))
        self.img.setPixmap(pix.scaled(self.img.size(), Qt.AspectRatioMode.KeepAspectRatio,
                                      Qt.TransformationMode.SmoothTransformation))

    def _export(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Export events", "garud360_events.csv", "CSV (*.csv)")
        if not path:
            return
        try:
            with open(path, "w", newline="", encoding="utf-8-sig") as f:
                w = csv.writer(f)
                w.writerow(["time", "day", "space", "camera", "event", "severity", "message", "snapshot"])
                for e in self._events:
                    w.writerow([_safe(v) for v in (local_time(e.ts, "%Y-%m-%d %H:%M:%S"), e.day, e.space_name,
                                                   e.camera_name, e.kind, e.severity, e.message,
                                                   e.snapshot_path or "")])
        except OSError as exc:
            error_box(self, "Export failed", str(exc))
