# tests/fakes.py
"""Test doubles: a scriptable camera reader and a fake detector (no OpenCV capture / YOLO needed)."""
from __future__ import annotations

import threading
import time

import numpy as np

from garud360.core.camera.reader import ReaderHealth
from garud360.core.detection.engine import Detection


def make_frame(person: bool, w: int = 320, h: int = 240) -> np.ndarray:
    f = np.zeros((h, w, 3), np.uint8)
    if person:
        f[0, 0, 0] = 255
    return f


class FakeReader:
    """Delivers frames at ~50 fps; `person`, `connected` and `frozen` can be flipped from the test."""
    instances: list["FakeReader"] = []

    def __init__(self, name, specs, settings_getter):
        self.name = name
        self.person = False
        self.connected = True
        self.frozen = False
        self.x_off = 0
        self._seq = 0
        self._frame = make_frame(False)
        self._t = 0.0
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        FakeReader.instances.append(self)

    def _run(self):
        while not self._stop.wait(0.02):
            if self.connected and not self.frozen:
                self._frame = make_frame(self.person)
                self._seq += 1
                self._t = time.monotonic()

    def start(self):
        self._t = time.monotonic()
        self._thread.start()

    def request_stop(self):
        self._stop.set()

    def join(self, timeout=1.0):
        self._thread.join(timeout)

    def stop(self):
        self.request_stop()
        self.join()

    def latest(self):
        return (self._frame if self._seq else None), self._seq, self._t

    def health(self):
        age = time.monotonic() - self._t if self._t else None
        if not self.connected:
            return ReaderHealth(False, "reconnecting", "Cannot connect", age, 0.0)
        if age is not None and age > 0.6:
            return ReaderHealth(False, "connected", f"No frames for {age:.0f} s", age, 0.0)
        if self._seq == 0:
            return ReaderHealth(False, "connecting", "Connecting ...", age, 0.0)
        return ReaderHealth(True, "connected", "OK", age, 50.0)


class FakeBackend:
    """A 'person' is any frame whose top-left pixel is 255."""

    def __init__(self, cfg=None):
        self.calls = 0
        self.fail = False
        self.delay = 0.0

    def load(self):
        pass

    def predict(self, frames, conf):
        self.calls += 1
        if self.delay:
            time.sleep(self.delay)
        if self.fail:
            raise RuntimeError("boom")
        out = []
        for f in frames:
            out.append([Detection((100.0, 50.0, 200.0, 230.0), 0.9),
                        Detection((10.0, 10.0, 30.0, 30.0), 0.2)] if f[0, 0, 0] == 255 else [])
        return out

    def close(self):
        pass
