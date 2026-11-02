# garud360/ui/dialogs/camera_dialogs.py
"""Camera editor (with live connection test) and the region-of-interest polygon editor."""
from __future__ import annotations

import threading
from typing import Any

import cv2
import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
                               QPushButton, QSpinBox, QStackedWidget, QVBoxLayout, QWidget)

from garud360.core.camera.probe import enumerate_webcams, probe_source
from garud360.core.camera.source import validate_source
from garud360.core.models import (SOURCE_LABELS, SRC_DROIDCAM, SRC_FILE, SRC_HTTP, SRC_RTSP, SRC_WEBCAM, Camera)
from garud360.ui.theme import C
from garud360.ui.util import app_icon, bgr_to_qimage, error_box, run_task

SOURCE_ORDER = [SRC_DROIDCAM, SRC_WEBCAM, SRC_RTSP, SRC_HTTP, SRC_FILE]


class RoiCanvas(QWidget):
    changed = Signal()

    def __init__(self, image: np.ndarray | None, polygon: list[tuple[float, float]] | None, parent=None) -> None:
        super().__init__(parent)
        self.setMinimumSize(640, 360)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.image = bgr_to_qimage(image) if image is not None else None
        self.points: list[tuple[float, float]] = list(polygon or [])
        self.closed = len(self.points) >= 3

    def _rect(self) -> QRectF:
        ar = (self.image.width() / self.image.height()) if self.image else 16 / 9
        w = self.width()
        h = w / ar
        if h > self.height():
            h = self.height()
            w = h * ar
        return QRectF((self.width() - w) / 2, (self.height() - h) / 2, w, h)

    def mousePressEvent(self, e) -> None:  # noqa: N802
        r = self._rect()
        pos = e.position()
        if e.button() == Qt.MouseButton.RightButton:
            if self.points:
                self.points.pop()
                self.closed = False
                self.changed.emit()
                self.update()
            return
        if e.button() == Qt.MouseButton.LeftButton and r.contains(pos):
            if self.closed:
                self.points, self.closed = [], False          # click after closing starts a new polygon
            self.points.append((min(max((pos.x() - r.x()) / r.width(), 0.0), 1.0),
                                min(max((pos.y() - r.y()) / r.height(), 0.0), 1.0)))
            self.changed.emit()
            self.update()

    def mouseDoubleClickEvent(self, e) -> None:  # noqa: N802
        if len(self.points) >= 3:
            self.points.pop()                                   # the 2nd click of the double-click added a point
            self.closed = True
            self.changed.emit()
            self.update()

    def clear(self) -> None:
        self.points, self.closed = [], False
        self.changed.emit()
        self.update()

    def close_polygon(self) -> None:
        if len(self.points) >= 3:
            self.closed = True
            self.update()

    def paintEvent(self, _e) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = self._rect()
        if self.image:
            p.drawImage(r, self.image)
        else:
            p.fillRect(r, QColor("#10162B"))
            p.setPen(QColor(C["muted"]))
            p.drawText(r, Qt.AlignmentFlag.AlignCenter, "No picture - use 'Test connection' in the camera dialog first")
        pts = [QPointF(r.x() + x * r.width(), r.y() + y * r.height()) for x, y in self.points]
        if len(pts) >= 2:
            if self.closed and len(pts) >= 3:
                p.setBrush(QColor(255, 215, 0, 60))
                p.setPen(QPen(QColor("#FFD700"), 2))
                p.drawPolygon(QPolygonF(pts))
            else:
                p.setPen(QPen(QColor("#FFD700"), 2))
                p.drawPolyline(QPolygonF(pts))
        p.setBrush(QColor("#FFD700"))
        p.setPen(QPen(QColor("#000000"), 1))
        for pt in pts:
            p.drawEllipse(pt, 5, 5)


class RoiEditorDialog(QDialog):
    def __init__(self, image: np.ndarray | None, polygon: list[tuple[float, float]] | None, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Draw monitored zone")
        self.setWindowIcon(app_icon())
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("Click to place corners of the danger zone (the area under the suspended load). "
                             "Double-click or press 'Close shape' to finish. Right-click removes the last point. "
                             "Only people inside this zone will block the crane."))
        lay.itemAt(0).widget().setWordWrap(True)
        self.canvas = RoiCanvas(image, polygon)
        lay.addWidget(self.canvas, 1)
        row = QHBoxLayout()
        for text, fn in (("Close shape", self.canvas.close_polygon), ("Clear zone", self.canvas.clear)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            row.addWidget(b)
        row.addStretch(1)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        ok = QPushButton("Use this zone")
        ok.setObjectName("primary")
        ok.clicked.connect(self._accept)
        row.addWidget(cancel)
        row.addWidget(ok)
        lay.addLayout(row)
        self.result_polygon: list[tuple[float, float]] | None = polygon
        self.resize(900, 620)

    def _accept(self) -> None:
        pts = self.canvas.points
        if 0 < len(pts) < 3:
            error_box(self, "Zone", "A zone needs at least 3 points (or clear it to watch the whole picture).")
            return
        self.result_polygon = [(round(x, 4), round(y, 4)) for x, y in pts] if len(pts) >= 3 else None
        self.accept()


class CameraEditorDialog(QDialog):
    probed = Signal(bool, str, object)
    scanned = Signal(object)

    def __init__(self, camera: Camera | None, connect_timeout_s: float = 8.0, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Camera")
        self.setWindowIcon(app_icon())
        self.setMinimumWidth(560)
        self._timeout = connect_timeout_s
        self._stop = threading.Event()
        self._task = None
        self._frame: np.ndarray | None = None
        self._roi: list[tuple[float, float]] | None = camera.roi if camera else None
        self._cam_id = camera.id if camera else 0
        self._cam_pos = camera.position if camera else 0
        self.result_camera: Camera | None = None

        lay = QVBoxLayout(self)
        form = QFormLayout()
        self.name = QLineEdit(camera.name if camera else "")
        self.name.setMaxLength(60)
        self.name.setPlaceholderText("e.g. North gate")
        self.type = QComboBox()
        for t in SOURCE_ORDER:
            self.type.addItem(SOURCE_LABELS[t], t)
        form.addRow("Camera name", self.name)
        form.addRow("Camera type", self.type)
        lay.addLayout(form)

        self.stack = QStackedWidget()
        # DroidCam
        w = QWidget()
        f = QFormLayout(w)
        self.dc_ip = QLineEdit()
        self.dc_ip.setPlaceholderText("192.168.1.25")
        self.dc_port = QSpinBox()
        self.dc_port.setRange(1, 65535)
        self.dc_port.setValue(4747)
        f.addRow("Phone IP address", self.dc_ip)
        f.addRow("Port", self.dc_port)
        hint = QLabel("Open DroidCam on the phone, note the IP and port shown, then press Connect. Phone and PC must be "
                      "on the same Wi-Fi. Close any browser tab showing the stream.")
        hint.setWordWrap(True)
        hint.setProperty("muted", True)
        f.addRow(hint)
        self.stack.addWidget(w)
        # Webcam
        w = QWidget()
        f = QFormLayout(w)
        row = QHBoxLayout()
        self.wc_index = QSpinBox()
        self.wc_index.setRange(0, 31)
        self.scan_btn = QPushButton("Scan for cameras")
        self.scan_btn.clicked.connect(self._scan)
        row.addWidget(self.wc_index)
        row.addWidget(self.scan_btn)
        f.addRow("Camera number", row)
        self.scan_lbl = QLabel("0 is normally the built-in laptop camera; USB cameras follow.")
        self.scan_lbl.setProperty("muted", True)
        self.scan_lbl.setWordWrap(True)
        f.addRow(self.scan_lbl)
        self.stack.addWidget(w)
        # RTSP / HTTP
        self.rtsp_url = QLineEdit()
        self.rtsp_url.setPlaceholderText("rtsp://user:password@192.168.1.64:554/Streaming/Channels/101")
        w = QWidget()
        f = QFormLayout(w)
        f.addRow("RTSP URL", self.rtsp_url)
        self.stack.addWidget(w)
        self.http_url = QLineEdit()
        self.http_url.setPlaceholderText("http://192.168.1.50:8080/video")
        w = QWidget()
        f = QFormLayout(w)
        f.addRow("Stream URL", self.http_url)
        self.stack.addWidget(w)
        # File
        w = QWidget()
        f = QFormLayout(w)
        row = QHBoxLayout()
        self.file_path = QLineEdit()
        browse = QPushButton("Browse ...")
        browse.clicked.connect(self._browse)
        row.addWidget(self.file_path, 1)
        row.addWidget(browse)
        f.addRow("Video file", row)
        self.stack.addWidget(w)
        lay.addWidget(self.stack)
        self.type.currentIndexChanged.connect(self.stack.setCurrentIndex)

        row = QHBoxLayout()
        self.test_btn = QPushButton("Connect / Test")
        self.test_btn.setObjectName("primary")
        self.test_btn.clicked.connect(self._test)
        self.roi_btn = QPushButton("Draw monitored zone ...")
        self.roi_btn.clicked.connect(self._edit_roi)
        row.addWidget(self.test_btn)
        row.addWidget(self.roi_btn)
        row.addStretch(1)
        lay.addLayout(row)
        self.roi_lbl = QLabel()
        self.roi_lbl.setProperty("muted", True)
        lay.addWidget(self.roi_lbl)
        self.result = QLabel("")
        self.result.setWordWrap(True)
        lay.addWidget(self.result)
        self.preview = QLabel()
        self.preview.setFixedHeight(200)
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setStyleSheet("background: #070A14; border-radius: 8px;")
        lay.addWidget(self.preview)
        self.enabled = QCheckBox("Camera enabled")
        self.enabled.setChecked(camera.enabled if camera else True)
        lay.addWidget(self.enabled)
        self.error = QLabel("")
        self.error.setStyleSheet("color: #F0524F;")
        self.error.setWordWrap(True)
        lay.addWidget(self.error)
        row = QHBoxLayout()
        row.addStretch(1)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        save = QPushButton("Save camera")
        save.setObjectName("primary")
        save.clicked.connect(self._save)
        row.addWidget(cancel)
        row.addWidget(save)
        lay.addLayout(row)
        self.probed.connect(self._on_probed)
        self.scanned.connect(self._on_scanned)
        self._load(camera)
        self._update_roi_label()

    # -- load / collect ---------------------------------------------------------------
    def _load(self, cam: Camera | None) -> None:
        if cam is None:
            return
        idx = max(0, SOURCE_ORDER.index(cam.source_type)) if cam.source_type in SOURCE_ORDER else 0
        self.type.setCurrentIndex(idx)
        c = cam.source_config
        self.dc_ip.setText(str(c.get("ip", "")))
        self.dc_port.setValue(int(c.get("port", 4747) or 4747))
        self.wc_index.setValue(int(c.get("index", 0) or 0))
        self.rtsp_url.setText(str(c.get("url", "")) if cam.source_type == SRC_RTSP else "")
        self.http_url.setText(str(c.get("url", "")) if cam.source_type == SRC_HTTP else "")
        self.file_path.setText(str(c.get("path", "")))

    def _config(self) -> tuple[str, dict[str, Any]]:
        t = self.type.currentData()
        if t == SRC_DROIDCAM:
            return t, {"ip": self.dc_ip.text().strip(), "port": self.dc_port.value()}
        if t == SRC_WEBCAM:
            return t, {"index": self.wc_index.value()}
        if t == SRC_RTSP:
            return t, {"url": self.rtsp_url.text().strip()}
        if t == SRC_HTTP:
            return t, {"url": self.http_url.text().strip()}
        return t, {"path": self.file_path.text().strip()}

    # -- actions ------------------------------------------------------------------------
    def _browse(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Choose a video file", "",
                                              "Video (*.mp4 *.avi *.mkv *.mov *.wmv);;All files (*)")
        if path:
            self.file_path.setText(path)

    def _test(self) -> None:
        t, cfg = self._config()
        errs = validate_source(t, cfg)
        if errs:
            self.result.setText(f"<span style='color:{C['crit']}'>{errs[0]}</span>")
            return
        self.test_btn.setEnabled(False)
        self.result.setText("Connecting ...")
        self._stop.clear()

        def work() -> None:
            ok, msg, frame = probe_source(t, cfg, self._timeout, self._stop)
            self.probed.emit(ok, msg, frame)

        threading.Thread(target=work, daemon=True).start()

    def _on_probed(self, ok: bool, msg: str, frame: object) -> None:
        self.test_btn.setEnabled(True)
        col = C["ok"] if ok else C["crit"]
        self.result.setText(f"<span style='color:{col}'>{msg}</span>")
        if ok and isinstance(frame, np.ndarray):
            self._frame = frame
            from garud360.ui.util import bgr_to_pixmap
            self.preview.setPixmap(bgr_to_pixmap(frame).scaled(self.preview.size(), Qt.AspectRatioMode.KeepAspectRatio,
                                                               Qt.TransformationMode.SmoothTransformation))

    def _scan(self) -> None:
        self.scan_btn.setEnabled(False)
        self.scan_lbl.setText("Scanning ... (this can take a few seconds)")
        threading.Thread(target=lambda: self.scanned.emit(enumerate_webcams()), daemon=True).start()

    def _on_scanned(self, found: object) -> None:
        self.scan_btn.setEnabled(True)
        lst = list(found) if isinstance(found, list) else []
        if lst:
            self.scan_lbl.setText("Cameras found: " + ", ".join(f"#{i}" for i in lst))
            self.wc_index.setValue(lst[0])
        else:
            self.scan_lbl.setText("No camera found. Check privacy settings (Windows: Settings > Privacy > Camera).")

    def _edit_roi(self) -> None:
        dlg = RoiEditorDialog(self._frame, self._roi, self)
        if dlg.exec():
            self._roi = dlg.result_polygon
            self._update_roi_label()

    def _update_roi_label(self) -> None:
        self.roi_lbl.setText(f"Zone: {len(self._roi)} points drawn - only people inside count." if self._roi
                             else "Zone: whole picture is monitored.")

    def _save(self) -> None:
        t, cfg = self._config()
        name = self.name.text().strip()
        if not name:
            self.error.setText("Please give the camera a name.")
            return
        errs = validate_source(t, cfg)
        if errs:
            self.error.setText(errs[0])
            return
        self.result_camera = Camera(self._cam_id, 0, name, t, cfg, self._roi, self.enabled.isChecked(), self._cam_pos)
        self.accept()

    def done(self, r: int) -> None:  # noqa: N802
        self._stop.set()
        super().done(r)
