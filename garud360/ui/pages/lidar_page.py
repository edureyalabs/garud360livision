# garud360/ui/pages/lidar_page.py
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from garud360.ui.util import logo_pixmap


class LidarPage(QWidget):
    """Placeholder for the 3D LiDAR integration."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("page")
        lay = QVBoxLayout(self)
        lay.setAlignment(Qt.AlignmentFlag.AlignCenter)
        logo = QLabel()
        logo.setPixmap(logo_pixmap(white=True).scaled(140, 140, Qt.AspectRatioMode.KeepAspectRatio,
                                                      Qt.TransformationMode.SmoothTransformation))
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        h = QLabel("3D LiDAR")
        h.setObjectName("h1")
        h.setAlignment(Qt.AlignmentFlag.AlignCenter)
        t = QLabel("LiDAR sensing will be added in a future release.\n"
                   "Camera-based detection is fully active in the meantime.")
        t.setProperty("muted", True)
        t.setAlignment(Qt.AlignmentFlag.AlignCenter)
        for w in (logo, h, t):
            lay.addWidget(w)
