# garud360/core/detection/pipeline.py
"""Per-camera pipeline: reader + ROI filtering + trigger/release debounce + live overlay rendering."""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Optional

import cv2
import numpy as np

from garud360.core.camera.reader import CameraReader
from garud360.core.detection.debounce import Debouncer
from garud360.core.detection.engine import Detection
from garud360.core.detection.roi import RoiMask

RED = (60, 60, 235)
GREY = (150, 150, 150)
YELLOW = (0, 215, 255)
GREEN = (80, 200, 90)
WHITE = (255, 255, 255)
FONT = cv2.FONT_HERSHEY_SIMPLEX


@dataclass
class CameraHealth:
    ok: bool
    detail: str


@dataclass
class _Shown:
    det: Detection
    counted: bool          # >= confidence and inside the region


class CameraPipeline:
    """Implements the InferenceClient protocol used by the shared inference service."""

    def __init__(self, camera_id: int, name: str, reader: CameraReader, roi_polygon: Any,
                 settings: dict[str, Any], on_change: Callable[[], None]) -> None:
        self.camera_id = camera_id
        self.name = name
        self.reader = reader
        self.roi = RoiMask(roi_polygon)
        self._on_change = on_change
        self._lock = threading.Lock()
        self.debouncer = Debouncer(3, 15)
        self.conf = 0.40
        self._s: dict[str, Any] = {}
        self.update_settings(settings)
        self._last_seq = 0
        self._last_served = 0.0
        self._last_result_t = 0.0
        self._active = False
        self._activated_t = time.monotonic()
        self._shown: list[_Shown] = []
        self._shape: tuple[int, ...] = (0, 0, 3)
        self._count = 0
        self.inferences = 0
        self.last_error = ""
        self._pending: Optional[np.ndarray] = None
        self._pending_seq = 0

    # -- configuration ----------------------------------------------------------
    def update_settings(self, s: dict[str, Any]) -> None:
        with self._lock:
            self._s = s
            self.conf = float(s["person_conf"])
            self.debouncer.configure(int(s["trigger_frames"]), int(s["release_frames"]))

    # -- InferenceClient ---------------------------------------------------------
    def last_served(self) -> float:
        return self._last_served

    def wants_frame(self, now: float) -> bool:
        if not self._active:
            return False
        interval = 1.0 / max(float(self._s["inference_fps"]), 0.1)
        if now - self._last_served < interval:
            return False
        frame, seq, _ = self.reader.latest()
        return frame is not None and seq != self._last_seq

    def take_frame(self) -> Optional[np.ndarray]:
        frame, seq, _ = self.reader.latest()
        if frame is None or seq == self._last_seq:
            return None
        self._last_seq = seq
        self._last_served = time.monotonic()
        self._pending, self._pending_seq = frame, seq
        return frame

    def deliver(self, detections: Optional[list[Detection]], error: Optional[str], now: float) -> None:
        if not self._active:
            return                                   # result arrived after the camera was deactivated
        if error is not None or detections is None:
            self.last_error = error or "unknown error"
            return                                   # watchdog (health) will notice the missing results
        frame = self._pending
        shape = frame.shape if frame is not None else self._shape
        use_roi = bool(self._s["roi_enabled"]) and self.roi.active
        mode = str(self._s["roi_match_mode"])
        shown: list[_Shown] = []
        count = 0
        for d in detections:
            if d.conf < self.conf:
                continue
            inside = self.roi.matches(d.box, shape, mode) if use_roi else True
            shown.append(_Shown(d, inside))
            count += int(inside)
        hit = count >= int(self._s["min_persons"])
        with self._lock:
            before = self.debouncer.active
            after = self.debouncer.update(hit)
            self._shown, self._shape, self._count = shown, shape, count
            self._last_result_t = now
            self.inferences += 1
            self.last_error = ""
        if after != before:
            self._on_change()

    # -- state ------------------------------------------------------------------
    def set_active(self, active: bool) -> None:
        """Activate/deactivate AI for this camera (pause, no-load gating, stop)."""
        with self._lock:
            if active == self._active:
                return
            self._active = active
            self._activated_t = time.monotonic()
            if not active:
                self.debouncer.reset()
                self._shown, self._count = [], 0
        self._on_change()

    @property
    def ai_active(self) -> bool:
        return self._active

    @property
    def person_active(self) -> bool:
        return self.debouncer.active

    @property
    def person_count(self) -> int:
        return self._count

    def health(self) -> CameraHealth:
        rh = self.reader.health()
        if not rh.ok:
            return CameraHealth(False, f"{rh.detail}")
        if self._active:
            ref = max(self._last_result_t, self._activated_t)
            age = time.monotonic() - ref
            if age > float(self._s["detection_stale_s"]):
                extra = f" ({self.last_error})" if self.last_error else ""
                return CameraHealth(False, f"Detection stalled for {age:.0f} s{extra}")
        return CameraHealth(True, "OK")

    def has_result_since_activation(self) -> bool:
        return self._last_result_t >= self._activated_t

    # -- rendering ---------------------------------------------------------------
    def render(self, max_width: Optional[int] = 640, status_text: str = "") -> np.ndarray:
        frame, _, _ = self.reader.latest()
        hd = self.health()
        if frame is None:
            return _placeholder(self.name, "NO SIGNAL", hd.detail, max_width or 640)
        h, w = frame.shape[:2]
        scale = 1.0
        if max_width and w > max_width:
            scale = max_width / w
            img = cv2.resize(frame, (max_width, max(1, int(round(h * scale)))), interpolation=cv2.INTER_AREA)
        else:
            img = frame.copy()
        with self._lock:
            shown, shape, count = list(self._shown), self._shape, self._count
            active = self.debouncer.active
        sx = img.shape[1] / max(shape[1], 1)
        sy = img.shape[0] / max(shape[0], 1)
        if self.roi.active and bool(self._s["roi_enabled"]):
            pts = np.array([[x * (img.shape[1] - 1), y * (img.shape[0] - 1)] for x, y in self.roi.polygon or []],
                           np.int32)
            cv2.polylines(img, [pts], True, YELLOW, 2, cv2.LINE_AA)
        if bool(self._s["draw_masks"]):
            overlay = img.copy()
            for s in shown:
                if s.det.polygon is not None and s.counted:
                    p = (s.det.polygon * np.array([sx, sy], np.float32)).astype(np.int32)
                    cv2.fillPoly(overlay, [p], RED)
            img = cv2.addWeighted(overlay, 0.35, img, 0.65, 0)
        for s in shown:
            x1, y1, x2, y2 = (int(v) for v in (s.det.box[0] * sx, s.det.box[1] * sy, s.det.box[2] * sx, s.det.box[3] * sy))
            color = RED if s.counted else GREY
            cv2.rectangle(img, (x1, y1), (x2, y2), color, 2)
            cv2.putText(img, f"person {s.det.conf:.2f}", (x1, max(y1 - 6, 12)), FONT, 0.5, color, 1, cv2.LINE_AA)
        _label(img, f"{self.name}  |  Persons: {count}", (8, 22), WHITE, 0.6)
        if not hd.ok:
            _banner(img, f"CAMERA FAULT: {hd.detail}", RED)
        elif status_text:
            _banner(img, status_text, YELLOW)
        elif active:
            _banner(img, "PERSON DETECTED", RED)
        return img


def _label(img: np.ndarray, text: str, org: tuple[int, int], color: tuple[int, int, int], scale: float) -> None:
    cv2.putText(img, text, org, FONT, scale, (0, 0, 0), 3, cv2.LINE_AA)
    cv2.putText(img, text, org, FONT, scale, color, 1, cv2.LINE_AA)


def _banner(img: np.ndarray, text: str, color: tuple[int, int, int]) -> None:
    h, w = img.shape[:2]
    cv2.rectangle(img, (0, h - 30), (w, h), color, -1)
    cv2.putText(img, text[: max(10, w // 9)], (8, h - 9), FONT, 0.55, (0, 0, 0), 1, cv2.LINE_AA)


def _placeholder(name: str, title: str, detail: str, width: int) -> np.ndarray:
    w = max(width, 320)
    h = int(w * 9 / 16)
    img = np.full((h, w, 3), 28, np.uint8)
    cv2.putText(img, title, (w // 2 - 90, h // 2 - 5), FONT, 0.9, (80, 80, 230), 2, cv2.LINE_AA)
    cv2.putText(img, detail[: w // 8], (12, h // 2 + 28), FONT, 0.5, (190, 190, 190), 1, cv2.LINE_AA)
    cv2.putText(img, name, (8, 22), FONT, 0.6, WHITE, 1, cv2.LINE_AA)
    return img
