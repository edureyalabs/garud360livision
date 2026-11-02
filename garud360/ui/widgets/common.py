# garud360/ui/widgets/common.py
"""Reusable small widgets: status badge, camera tile, stat tile, bar chart."""
from __future__ import annotations

import numpy as np
from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QFrame, QLabel, QSizePolicy, QVBoxLayout, QWidget

from garud360.ui.theme import C
from garud360.ui.util import bgr_to_pixmap


class StatusBadge(QLabel):
    def __init__(self, text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.set_status(text, "off")

    def set_status(self, text: str, color_hex_or_key: str) -> None:
        col = C.get(color_hex_or_key, color_hex_or_key)
        self.setText(text)
        self.setStyleSheet(f"background: {col}33; color: {col}; border: 1px solid {col}; border-radius: 10px; "
                           f"padding: 2px 10px; font-weight: 600; font-size: 11px;")


class StatTile(QFrame):
    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("panel")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 10, 14, 10)
        lay.setSpacing(0)
        self.value = QLabel("0")
        self.value.setStyleSheet("font-size: 26px; font-weight: 700;")
        self.title = QLabel(title)
        self.title.setProperty("muted", True)
        lay.addWidget(self.value)
        lay.addWidget(self.title)

    def set_value(self, v: int | str, color_key: str | None = None) -> None:
        self.value.setText(str(v))
        self.value.setStyleSheet(f"font-size: 26px; font-weight: 700; color: {C[color_key] if color_key else C['text']};")


class CameraTile(QFrame):
    clicked = Signal(int)

    def __init__(self, camera_id: int, name: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.camera_id = camera_id
        self.setObjectName("panel")
        self.setMinimumSize(220, 140)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(3, 3, 3, 3)
        self.view = QLabel(name)
        self.view.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.view.setMinimumSize(200, 120)
        self.view.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        self.view.setStyleSheet(f"background: #070A14; border-radius: 8px; color: {C['muted']};")
        lay.addWidget(self.view)
        self._pix: QPixmap | None = None
        self.border_state = "off"

    def set_frame(self, bgr: np.ndarray | None, placeholder: str = "") -> None:
        if bgr is None:
            self._pix = None
            self.view.setPixmap(QPixmap())
            self.view.setText(placeholder)
            return
        self._pix = bgr_to_pixmap(bgr)
        self._rescale()

    def set_alert(self, state: str) -> None:
        if state != self.border_state:
            self.border_state = state
            col = {"crit": C["crit"], "warn": C["warn"], "ok": C["border"]}.get(state, C["border"])
            self.setStyleSheet(f"QFrame#panel {{ border: 2px solid {col}; }}")

    def _rescale(self) -> None:
        if self._pix is not None:
            self.view.setPixmap(self._pix.scaled(self.view.size(), Qt.AspectRatioMode.KeepAspectRatio,
                                                 Qt.TransformationMode.SmoothTransformation))

    def resizeEvent(self, e) -> None:  # noqa: N802
        super().resizeEvent(e)
        self._rescale()

    def mouseDoubleClickEvent(self, e) -> None:  # noqa: N802
        self.clicked.emit(self.camera_id)


class BarChart(QWidget):
    """Stacked daily bars: person violations (red) and camera faults (amber)."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(150)
        self.data: list[dict] = []

    def set_data(self, data: list[dict]) -> None:
        self.data = data
        self.update()

    def paintEvent(self, _e) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        if not self.data:
            return
        top, bottom, left = 20, 28, 30
        peak = max([d["person"] + d["camera"] for d in self.data] + [1])
        n = len(self.data)
        slot = (w - left - 10) / n
        bw = min(slot * 0.55, 46)
        p.setPen(QPen(QColor(C["border"]), 1))
        base = h - bottom
        p.drawLine(left, int(base), w - 6, int(base))
        f = QFont("Segoe UI", 8)
        p.setFont(f)
        p.setPen(QColor(C["muted"]))
        p.drawText(QRectF(0, top - 8, left - 4, 14), Qt.AlignmentFlag.AlignRight, str(peak))
        p.drawText(QRectF(0, base - 14, left - 4, 14), Qt.AlignmentFlag.AlignRight, "0")
        for i, d in enumerate(self.data):
            x = left + slot * i + (slot - bw) / 2
            avail = base - top
            hp = avail * d["person"] / peak
            hc = avail * d["camera"] / peak
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(C["crit"]))
            p.drawRoundedRect(QRectF(x, base - hp, bw, hp), 3, 3)
            p.setBrush(QColor(C["warn"]))
            p.drawRoundedRect(QRectF(x, base - hp - hc, bw, hc), 3, 3)
            p.setPen(QColor(C["text"]))
            tot = d["person"] + d["camera"]
            if tot:
                p.drawText(QRectF(x - 10, base - hp - hc - 15, bw + 20, 14), Qt.AlignmentFlag.AlignCenter, str(tot))
            p.setPen(QColor(C["muted"]))
            p.drawText(QRectF(x - 14, base + 4, bw + 28, 16), Qt.AlignmentFlag.AlignCenter, d["day"][5:])
