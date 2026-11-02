# garud360/ui/widgets/crane_widget.py
"""Animated front-elevation view of the simulated overhead crane."""
from __future__ import annotations

import math
import time

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QLinearGradient, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import QWidget

from garud360.core.sim.crane import PAD_A, PAD_B, CraneSnapshot
from garud360.ui.theme import C


class CraneWidget(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumSize(360, 240)
        self.snap: CraneSnapshot | None = None
        self.running = False
        self.permit: bool | None = None
        self.person = False
        self.status_text = "MONITOR STOPPED"
        self.channel_label = ""

    def set_state(self, snap: CraneSnapshot | None, running: bool, permit: bool | None, person: bool,
                  status_text: str, channel_label: str) -> None:
        self.snap, self.running, self.permit, self.person = snap, running, permit, person
        self.status_text, self.channel_label = status_text, channel_label
        self.update()

    # ------------------------------------------------------------------------------
    def paintEvent(self, _event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        grad = QLinearGradient(0, 0, 0, h)
        grad.setColorAt(0, QColor("#141B33"))
        grad.setColorAt(1, QColor("#0B101E"))
        p.fillRect(self.rect(), grad)

        left, right = w * 0.08, w * 0.92
        girder_y = h * 0.20
        floor_y = h * 0.86
        span = right - left
        blocked = self.running and self.permit is False
        allowed = self.running and self.permit is True
        accent = QColor(C["crit"] if blocked else C["ok"] if allowed else C["off"])
        snap = self.snap

        # floor + pads
        p.setPen(QPen(QColor(C["border"]), 2))
        p.drawLine(QPointF(w * 0.02, floor_y), QPointF(w * 0.98, floor_y))
        for pad in (PAD_A, PAD_B):
            x = left + pad * span
            p.fillRect(QRectF(x - w * 0.07, floor_y, w * 0.14, h * 0.025), QColor("#2A3560"))

        # columns and girder
        steel = QColor("#5C6894")
        for cx in (left - w * 0.02, right + w * 0.02):
            p.fillRect(QRectF(cx - w * 0.012, girder_y, w * 0.024, floor_y - girder_y), QColor("#2B3558"))
        p.fillRect(QRectF(left - w * 0.05, girder_y - h * 0.02, span + w * 0.10, h * 0.045), steel)

        tx = left + (snap.x if snap else 0.5) * span
        z = snap.z if snap else 0.12

        # fall zone below the hook
        zone_w = w * 0.20
        zone = QRectF(tx - zone_w / 2, floor_y - h * 0.035, zone_w, h * 0.06)
        zc = QColor(accent)
        pulse = 0.5 + 0.5 * math.sin(time.monotonic() * 7) if blocked else 0.0
        zc.setAlpha(int(70 + 90 * pulse) if blocked else 70)
        p.setPen(QPen(accent, 2, Qt.PenStyle.DashLine))
        p.setBrush(QBrush(zc))
        p.drawRoundedRect(zone, 6, 6)

        # resting load on a pad
        if snap and snap.load_pad is not None:
            lx = left + snap.load_pad * span
            self._load(p, lx, floor_y - h * 0.06, w * 0.09, h * 0.06)

        # trolley, rope, hook, suspended load
        trolley = QRectF(tx - w * 0.05, girder_y - h * 0.05, w * 0.10, h * 0.06)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#7C8AC4"))
        p.drawRoundedRect(trolley, 4, 4)
        hook_y = girder_y + h * 0.02 + z * (floor_y - girder_y - h * 0.18)
        p.setPen(QPen(QColor("#C7CDE6"), 2))
        p.drawLine(QPointF(tx, trolley.bottom()), QPointF(tx, hook_y))
        p.setBrush(QColor("#E0B84A"))
        p.setPen(QPen(QColor("#8A6D1B"), 1))
        p.drawEllipse(QPointF(tx, hook_y + 4), 6, 6)
        if snap and snap.load_attached:
            p.setPen(QPen(QColor("#C7CDE6"), 1))
            lw, lh = w * 0.09, h * 0.07
            p.drawLine(QPointF(tx, hook_y + 8), QPointF(tx - lw / 2, hook_y + 18))
            p.drawLine(QPointF(tx, hook_y + 8), QPointF(tx + lw / 2, hook_y + 18))
            self._load(p, tx, hook_y + 18, lw, lh)

        # person icon in the zone
        if self.person and self.running:
            self._person(p, tx, floor_y - h * 0.005, h * 0.12)

        # banner
        font = QFont("Segoe UI", 10)
        font.setBold(True)
        p.setFont(font)
        p.setPen(QPen(accent))
        label = "MOVEMENT BLOCKED - holder released" if blocked else \
            "MOVEMENT ALLOWED" if allowed else "NOT RUNNING"
        if snap and snap.watchdog_tripped:
            label = "PLC WATCHDOG: NO HEARTBEAT - crane stopped"
        p.setBrush(accent)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QPointF(18, 20), 6, 6)
        p.setPen(QPen(accent))
        p.drawText(QPointF(32, 25), label)
        small = QFont("Segoe UI", 8)
        p.setFont(small)
        p.setPen(QColor(C["muted"]))
        p.drawText(QPointF(12, h - 10), self.channel_label)
        right_txt = self.status_text
        fm = p.fontMetrics()
        p.drawText(QPointF(w - fm.horizontalAdvance(right_txt) - 12, h - 10), right_txt)
        if snap is None and self.running:
            p.setPen(QColor(C["muted"]))
            p.drawText(QRectF(0, h * 0.3, w, 40), Qt.AlignmentFlag.AlignCenter,
                       "Real PLC output - crane motion is not simulated")
        p.end()

    @staticmethod
    def _load(p: QPainter, cx: float, top: float, lw: float, lh: float) -> None:
        p.setPen(QPen(QColor("#7A5C1E"), 1))
        p.setBrush(QColor("#B8862B"))
        p.drawRect(QRectF(cx - lw / 2, top, lw, lh))
        p.drawLine(QPointF(cx - lw / 2, top + lh / 2), QPointF(cx + lw / 2, top + lh / 2))

    @staticmethod
    def _person(p: QPainter, x: float, foot_y: float, size: float) -> None:
        pen = QPen(QColor("#FFD166"), 3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        head_r = size * 0.13
        top = foot_y - size
        p.drawEllipse(QPointF(x, top + head_r), head_r, head_r)
        body_top, hip = top + head_r * 2, top + size * 0.62
        p.drawLine(QPointF(x, body_top), QPointF(x, hip))
        p.drawLine(QPointF(x - size * 0.2, body_top + size * 0.15), QPointF(x + size * 0.2, body_top + size * 0.15))
        p.drawLine(QPointF(x, hip), QPointF(x - size * 0.15, foot_y))
        p.drawLine(QPointF(x, hip), QPointF(x + size * 0.15, foot_y))
