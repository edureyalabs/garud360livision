# tests/test_camera.py
import threading
import time

import cv2
import numpy as np
import pytest

from garud360.core.camera.probe import probe_source
from garud360.core.camera.reader import CameraReader
from garud360.core.camera.source import OpenSpec, build_open_specs, mask_url, validate_source
from tests.conftest import eventually

SET = {"stale_frame_s": 1.0, "connect_timeout_s": 2.0, "reconnect_initial_s": 0.1, "reconnect_max_s": 0.4}


def test_validate_and_build_sources():
    assert validate_source("droidcam", {"ip": "192.168.1.9", "port": 4747}) == []
    assert validate_source("droidcam", {"ip": "", "port": 4747})
    assert validate_source("droidcam", {"ip": "192.168.1.9", "port": 70000})
    assert validate_source("droidcam", {"ip": "bad host", "port": 4747})
    assert validate_source("droidcam", {"ip": "http://1.2.3.4", "port": 4747})        # no scheme allowed
    specs = build_open_specs("droidcam", {"ip": "192.168.1.9", "port": 4747})
    assert [s.target for s in specs] == ["http://192.168.1.9:4747/video", "http://192.168.1.9:4747/mjpegfeed?640x480"]
    assert build_open_specs("webcam", {"index": 1})[0] == OpenSpec("index", 1, "Camera #1")
    assert validate_source("rtsp", {"url": "http://x/y"}) and validate_source("rtsp", {"url": "rtsp://u:p@1.2.3.4/s"}) == []
    assert validate_source("http_mjpeg", {"url": "rtsp://x"}) and validate_source("file", {"path": ""})
    assert validate_source("nope", {})
    with pytest.raises(ValueError):
        build_open_specs("droidcam", {"ip": "", "port": 1})
    assert "secret" not in mask_url("rtsp://admin:secret@10.0.0.1:554/s")


class ScriptedCap:
    def __init__(self, behaviour):
        self.b = behaviour
        self.released = False

    def read(self):
        return self.b()

    def release(self):
        self.released = True


def good():
    time.sleep(0.01)
    return True, np.zeros((24, 32, 3), np.uint8)


def test_reader_connects_reports_health_and_reconnects_after_stall():
    state = {"mode": "good", "opens": 0}

    def behaviour():
        if state["mode"] == "good":
            return good()
        time.sleep(0.02)
        return False, None

    def open_fn(spec, timeout, stop):
        state["opens"] += 1
        return ScriptedCap(behaviour) if state["mode"] != "refuse" else None

    r = CameraReader("t", [OpenSpec("url", "x", "x")], lambda: SET, open_fn)
    r.start()
    try:
        eventually(lambda: r.health().ok, message="connected")
        frame, seq, _ = r.latest()
        assert frame.shape == (24, 32, 3) and seq > 0
        eventually(lambda: r.health().fps > 0, message="fps estimate")
        state["mode"] = "stall"                                    # camera freezes
        eventually(lambda: not r.health().ok, timeout=4, message="stale detected")
        assert "No frames" in r.health().detail or "reconnect" in r.health().detail.lower()
        eventually(lambda: state["opens"] >= 2, timeout=5, message="reconnect attempted")
        state["mode"] = "good"
        eventually(lambda: r.health().ok, timeout=5, message="recovered")
        state["mode"] = "refuse"
        state["opens"] = 0
        r.request_stop()
    finally:
        r.stop()
    assert r.health().state == "stopped"


def test_reader_open_failures_back_off_and_report():
    opens = []

    def open_fn(spec, timeout, stop):
        opens.append(time.monotonic())
        return None

    r = CameraReader("t", [OpenSpec("url", "x", "Cam URL")], lambda: SET, open_fn)
    r.start()
    try:
        eventually(lambda: len(opens) >= 3, timeout=5)
        h = r.health()
        assert not h.ok and "Cannot connect" in h.detail
        gaps = [b - a for a, b in zip(opens, opens[1:])]
        assert gaps[-1] >= gaps[0]                                  # exponential back-off
    finally:
        r.stop()


def test_reader_survives_exceptions_in_open_and_read():
    calls = {"n": 0}

    def open_fn(spec, timeout, stop):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("driver exploded")
        return ScriptedCap(lambda: (_ for _ in ()).throw(RuntimeError("read exploded")) if calls["n"] < 3 else good())

    r = CameraReader("t", [OpenSpec("url", "x", "x")], lambda: SET, open_fn)
    r.start()
    try:
        eventually(lambda: r.health().ok, timeout=8, message="recovered from exceptions")
    finally:
        r.stop()


def test_probe_and_real_opencv_file_reader(tmp_path):
    path = tmp_path / "clip.avi"
    w = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), 25, (160, 120))
    if not w.isOpened():
        pytest.skip("OpenCV build cannot write test video")
    for i in range(30):
        w.write(np.full((120, 160, 3), i * 8, np.uint8))
    w.release()
    ok, msg, frame = probe_source("file", {"path": str(path)}, 3.0)
    assert ok and frame.shape == (120, 160, 3), msg
    ok, msg, frame = probe_source("file", {"path": str(tmp_path / "missing.avi")}, 1.0)
    assert not ok and frame is None
    ok, msg, _ = probe_source("droidcam", {"ip": "", "port": 4747})
    assert not ok
    stop = threading.Event()
    stop.set()
    ok, msg, _ = probe_source("file", {"path": str(path)}, 3.0, stop)
    assert not ok

    from garud360.core.camera.source import build_open_specs as b
    r = CameraReader("file", b("file", {"path": str(path)}), lambda: SET)       # looping real capture
    r.start()
    try:
        eventually(lambda: r.latest()[1] > 40, timeout=6, message="file loops past its 30 frames")
    finally:
        r.stop()
