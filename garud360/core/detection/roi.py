# garud360/core/detection/roi.py
"""Region-of-interest (polygon) filtering for person detections."""
from __future__ import annotations

import threading
from typing import Sequence

import cv2
import numpy as np

MATCH_ANY = "any_overlap"
MATCH_CENTER = "box_center"
MATCH_FOOT = "foot_point"


class RoiMask:
    """Normalised polygon (0..1) rasterised lazily per frame size and cached."""

    def __init__(self, polygon: Sequence[Sequence[float]] | None) -> None:
        pts = [(float(x), float(y)) for x, y in polygon] if polygon else []
        self.polygon: list[tuple[float, float]] | None = pts if len(pts) >= 3 else None
        self._cache: dict[tuple[int, int], np.ndarray] = {}
        self._lock = threading.Lock()

    @property
    def active(self) -> bool:
        return self.polygon is not None

    def mask(self, width: int, height: int) -> np.ndarray | None:
        if self.polygon is None:
            return None
        key = (width, height)
        with self._lock:
            m = self._cache.get(key)
            if m is None:
                m = np.zeros((height, width), np.uint8)
                pts = np.array([[round(x * (width - 1)), round(y * (height - 1))] for x, y in self.polygon], np.int32)
                cv2.fillPoly(m, [pts], 1)
                if len(self._cache) > 4:
                    self._cache.clear()
                self._cache[key] = m
            return m

    def matches(self, box: Sequence[float], frame_shape: tuple[int, ...], mode: str = MATCH_ANY) -> bool:
        """True when the person box counts as inside the region (always True without a polygon)."""
        h, w = int(frame_shape[0]), int(frame_shape[1])
        m = self.mask(w, h)
        if m is None:
            return True
        x1, y1, x2, y2 = box
        x1, x2 = sorted((x1, x2))
        y1, y2 = sorted((y1, y2))
        if mode == MATCH_CENTER:
            return _at(m, (x1 + x2) / 2.0, (y1 + y2) / 2.0)
        if mode == MATCH_FOOT:
            return _at(m, (x1 + x2) / 2.0, y2 - 1)
        ix1, iy1 = max(int(np.floor(x1)), 0), max(int(np.floor(y1)), 0)
        ix2, iy2 = min(int(np.ceil(x2)), w), min(int(np.ceil(y2)), h)
        if ix2 <= ix1 or iy2 <= iy1:
            return False
        return bool(m[iy1:iy2, ix1:ix2].any())


def _at(m: np.ndarray, x: float, y: float) -> bool:
    h, w = m.shape
    xi, yi = int(round(x)), int(round(y))
    if not (0 <= xi < w and 0 <= yi < h):
        return False
    return bool(m[yi, xi])
