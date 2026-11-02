# garud360/core/camera/reader.py
"""Background camera reader: latest-frame-only, auto-reconnect, stale-stream detection."""
from __future__ import annotations

import logging
import sys
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Optional, Protocol

import numpy as np

from garud360.core.camera.source import OpenSpec, mask_url

log = logging.getLogger(__name__)


class FrameSource(Protocol):
    def read(self) -> tuple[bool, Optional[np.ndarray]]: ...
    def release(self) -> None: ...


OpenFn = Callable[[OpenSpec, float, threading.Event], Optional[FrameSource]]


def open_capture(spec: OpenSpec, timeout_s: float, stop: threading.Event) -> Optional[FrameSource]:
    """Open an OpenCV capture on a helper thread so a hung network open can never freeze the reader."""
    import cv2

    box: dict[str, Any] = {}
    abandoned = threading.Event()

    def worker() -> None:
        try:
            if spec.kind == "index":
                cap = None
                if sys.platform == "win32":
                    cap = cv2.VideoCapture(int(spec.target), cv2.CAP_DSHOW)
                    if not cap.isOpened():
                        cap.release()
                        cap = cv2.VideoCapture(int(spec.target))
                else:
                    cap = cv2.VideoCapture(int(spec.target))
                try:
                    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                except Exception:  # noqa: BLE001
                    pass
            elif spec.kind == "url":
                ms = int(timeout_s * 1000)
                cap = cv2.VideoCapture(str(spec.target), cv2.CAP_FFMPEG,
                                       [cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, ms, cv2.CAP_PROP_READ_TIMEOUT_MSEC, ms])
            else:
                cap = cv2.VideoCapture(str(spec.target))
            if abandoned.is_set():
                cap.release()
                return
            box["cap"] = cap
        except Exception as exc:  # noqa: BLE001
            box["error"] = exc

    t = threading.Thread(target=worker, name="cam-open", daemon=True)
    t.start()
    deadline = time.monotonic() + timeout_s + 2.0
    while t.is_alive() and time.monotonic() < deadline and not stop.is_set():
        t.join(0.1)
    cap = box.get("cap")
    if cap is not None and cap.isOpened():
        if spec.kind == "file":
            return _LoopingFile(cap)
        return cap
    abandoned.set()
    if cap is not None:
        cap.release()
    return None


class _LoopingFile:
    """Plays a video file at its native speed, forever (for testing without a camera)."""

    def __init__(self, cap: Any) -> None:
        import cv2
        self._cv2 = cv2
        self._cap = cap
        fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
        self._interval = 1.0 / min(max(fps, 1.0), 60.0)
        self._next = time.monotonic()

    def read(self) -> tuple[bool, Optional[np.ndarray]]:
        delay = self._next - time.monotonic()
        if delay > 0:
            time.sleep(delay)
        self._next = max(self._next + self._interval, time.monotonic() - 1.0)
        ok, frame = self._cap.read()
        if not ok:
            self._cap.set(self._cv2.CAP_PROP_POS_FRAMES, 0)
            ok, frame = self._cap.read()
        return ok, frame

    def release(self) -> None:
        self._cap.release()


@dataclass
class ReaderHealth:
    ok: bool
    state: str                # connecting | connected | reconnecting | stopped
    detail: str
    frame_age: float | None
    fps: float


class CameraReader:
    def __init__(self, name: str, specs: list[OpenSpec], settings_getter: Callable[[], dict[str, Any]],
                 open_fn: OpenFn = open_capture) -> None:
        self.name = name
        self._specs = specs
        self._settings = settings_getter
        self._open = open_fn
        self._lock = threading.Lock()
        self._frame: Optional[np.ndarray] = None
        self._seq = 0
        self._last_frame_t = 0.0
        self._started_t = 0.0
        self._state = "connecting"
        self._detail = "Starting ..."
        self._fps = 0.0
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name=f"cam-{name}", daemon=True)

    # -- public ---------------------------------------------------------------
    def start(self) -> None:
        self._started_t = time.monotonic()
        self._thread.start()

    def request_stop(self) -> None:
        self._stop.set()

    def join(self, timeout: float = 3.0) -> None:
        if self._thread.is_alive():
            self._thread.join(timeout=timeout)
        with self._lock:
            self._state, self._detail = "stopped", "Stopped"

    def stop(self) -> None:
        self.request_stop()
        self.join()

    def latest(self) -> tuple[Optional[np.ndarray], int, float]:
        """(frame, sequence number, monotonic timestamp). The frame must be treated as read-only."""
        with self._lock:
            return self._frame, self._seq, self._last_frame_t

    def health(self) -> ReaderHealth:
        now = time.monotonic()
        stale_s = float(self._settings()["stale_frame_s"])
        with self._lock:
            state, detail, fps = self._state, self._detail, self._fps
            last = self._last_frame_t
        age = (now - last) if last else None
        if state == "connected":
            if age is not None and age <= stale_s:
                return ReaderHealth(True, state, "OK", age, fps)
            return ReaderHealth(False, state, f"No frames for {age:.0f} s" if age is not None else "No frames yet",
                                age, fps)
        return ReaderHealth(False, state, detail, age, fps)

    # -- thread ---------------------------------------------------------------
    def _set(self, state: str, detail: str) -> None:
        with self._lock:
            self._state, self._detail = state, detail

    def _sleep(self, seconds: float) -> None:
        self._stop.wait(seconds)

    def _run(self) -> None:
        backoff = float(self._settings()["reconnect_initial_s"])
        first = True
        while not self._stop.is_set():
            s = self._settings()
            self._set("connecting" if first else "reconnecting", "Connecting ...")
            cap, errors = None, []
            for spec in self._specs:
                if self._stop.is_set():
                    break
                log.info("[%s] opening %s", self.name, mask_url(str(spec.target)))
                try:
                    cap = self._open(spec, float(s["connect_timeout_s"]), self._stop)
                except Exception as exc:  # noqa: BLE001
                    log.exception("[%s] open failed", self.name)
                    cap, errors = None, errors + [str(exc)]
                if cap is not None:
                    break
                errors.append(f"{spec.label} not reachable")
            if self._stop.is_set():
                if cap is not None:
                    self._release(cap)
                break
            if cap is None:
                self._set("reconnecting", "Cannot connect: " + "; ".join(dict.fromkeys(errors)))
                self._sleep(backoff)
                backoff = min(backoff * 2.0, float(self._settings()["reconnect_max_s"]))
                first = False
                continue
            log.info("[%s] connected", self.name)
            self._set("connected", "OK")
            backoff = float(self._settings()["reconnect_initial_s"])
            first = False
            self._pump(cap)
            self._release(cap)
            if not self._stop.is_set():
                self._set("reconnecting", "Stream lost - reconnecting")
                self._sleep(min(backoff, 1.0))

    def _pump(self, cap: FrameSource) -> None:
        last_ok = time.monotonic()
        prev = 0.0
        while not self._stop.is_set():
            try:
                ok, frame = cap.read()
            except Exception:  # noqa: BLE001
                log.exception("[%s] read error", self.name)
                ok, frame = False, None
            now = time.monotonic()
            if ok and frame is not None and getattr(frame, "size", 0) > 0:
                with self._lock:
                    self._frame = frame
                    self._seq += 1
                    self._last_frame_t = now
                    if prev:
                        inst = 1.0 / max(now - prev, 1e-6)
                        self._fps = inst if self._fps == 0 else 0.9 * self._fps + 0.1 * inst
                prev = now
                last_ok = now
            else:
                if now - last_ok > float(self._settings()["stale_frame_s"]):
                    log.warning("[%s] no frames for %.1fs - reconnecting", self.name, now - last_ok)
                    return
                self._sleep(0.05)

    @staticmethod
    def _release(cap: FrameSource) -> None:
        # release() can block on dead network streams, so never do it on the reader thread
        threading.Thread(target=cap.release, daemon=True).start()
