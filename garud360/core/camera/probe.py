# garud360/core/camera/probe.py
"""One-shot camera tests used by the camera editor (Connect / Test button, webcam scan)."""
from __future__ import annotations

import sys
import threading
import time
from typing import Any, Optional

import numpy as np

from garud360.core.camera.reader import open_capture
from garud360.core.camera.source import build_open_specs, mask_url


def probe_source(source_type: str, cfg: dict[str, Any], timeout_s: float = 8.0,
                 stop: Optional[threading.Event] = None) -> tuple[bool, str, Optional[np.ndarray]]:
    """Open the camera, grab one frame, release it. Returns (ok, message, frame)."""
    stop = stop or threading.Event()
    try:
        specs = build_open_specs(source_type, cfg)
    except ValueError as exc:
        return False, str(exc), None
    tried: list[str] = []
    for spec in specs:
        if stop.is_set():
            return False, "Cancelled.", None
        cap = open_capture(spec, timeout_s, stop)
        if cap is None:
            tried.append(spec.label)
            continue
        frame = None
        try:
            end = time.monotonic() + max(3.0, timeout_s / 2)
            while time.monotonic() < end and not stop.is_set():
                ok, f = cap.read()
                if ok and f is not None and f.size:
                    frame = f
                    break
                time.sleep(0.05)
        finally:
            threading.Thread(target=cap.release, daemon=True).start()
        if frame is not None:
            h, w = frame.shape[:2]
            return True, f"Connected ({spec.label}, {w}x{h}).", frame
        tried.append(f"{spec.label} (opened but no picture)")
    hint = ""
    if source_type == "droidcam":
        hint = (" Close other viewers of the stream (DroidCam usually allows one client), check phone and PC are on the "
                "same Wi-Fi, and allow the app through Windows Firewall.")
    return False, f"Could not get a picture from {', '.join(tried) or mask_url(str(cfg))}.{hint}", None


def enumerate_webcams(max_index: int = 6) -> list[int]:
    """Indexes of local cameras that deliver a picture (slow: opens each device)."""
    import cv2
    found: list[int] = []
    for i in range(max_index):
        cap = cv2.VideoCapture(i, cv2.CAP_DSHOW) if sys.platform == "win32" else cv2.VideoCapture(i)
        try:
            if cap.isOpened():
                ok, frame = cap.read()
                if ok and frame is not None:
                    found.append(i)
        finally:
            cap.release()
    return found
