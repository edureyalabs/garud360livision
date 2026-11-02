# tests/test_e2e_real_model.py
"""End-to-end with the REAL YOLO26 model, a real video file source and the simulated crane.

Skipped unless GARUD360_E2E_IMAGE points to a photo that contains at least one person and `ultralytics` is installed
(the first run downloads yolo26n-seg.pt):

    GARUD360_E2E_IMAGE=/path/to/bus.jpg python -m pytest tests/test_e2e_real_model.py -s
"""
import os
import time

import cv2
import numpy as np
import pytest

IMAGE = os.environ.get("GARUD360_E2E_IMAGE")
pytestmark = pytest.mark.skipif(not IMAGE, reason="set GARUD360_E2E_IMAGE to run the real-model test")

from garud360.core.models import Camera, Space  # noqa: E402
from garud360.core.runtime import RuntimeManager  # noqa: E402
from tests.conftest import eventually  # noqa: E402


def make_video(path, frame, n=60):
    h, w = frame.shape[:2]
    vw = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), 15, (w, h))
    for _ in range(n):
        vw.write(frame)
    vw.release()


def test_real_model_blocks_crane_for_person_and_releases_on_empty_scene(repos, tmp_path, monkeypatch):
    pytest.importorskip("ultralytics")
    monkeypatch.setenv("GARUD360_DATA_DIR", str(tmp_path / "data"))
    img = cv2.imread(IMAGE)
    assert img is not None
    make_video(tmp_path / "person.avi", img)
    make_video(tmp_path / "empty.avi", np.full_like(img, 90))
    st = repos["settings"]
    st.update({"inference_device": "cpu", "inference_fps": 5.0, "trigger_frames": 2, "release_frames": 3,
               "stale_frame_s": 5.0, "detection_stale_s": 20.0, "connect_timeout_s": 5.0})
    rt = RuntimeManager(repos["spaces"], repos["events"], st, tmp_path / "snaps", tmp_path)
    rt.start()
    try:
        sp = repos["spaces"].save(Space(0, "Real", plc_config={"type": "simulated"}, cameras=[
            Camera(0, 0, "person-cam", "file", {"path": str(tmp_path / "person.avi")}),
            Camera(0, 0, "empty-cam", "file", {"path": str(tmp_path / "empty.avi")})]))
        rt.start_space(sp.id)
        eventually(lambda: rt.snapshots()[sp.id].status == "PERSON DETECTED", timeout=120, message="person detected")
        snap = rt.snapshots()[sp.id]
        print("\nSTATUS:", snap.status, "| persons:", snap.persons, "| engine:", rt.engine_status())
        assert not snap.permit and snap.persons >= 1
        mon = rt.monitor(sp.id)
        eventually(lambda: mon.crane() is not None and not mon.crane().permit, timeout=10, message="sim crane blocked")
        ev = eventually(lambda: (repos["events"].search(kinds=["person_violation"]) or [None])[0], timeout=10,
                        message="violation event")
        assert ev.camera_name == "person-cam" and ev.snapshot_path
        assert (tmp_path / "snaps" / ev.snapshot_path).exists()
        print("snapshot:", tmp_path / "snaps" / ev.snapshot_path)
        rt.stop_space(sp.id)
        eventually(lambda: not rt.is_running(sp.id), timeout=20)
        # only the empty scene -> must be CLEAR and the crane permitted
        sp2 = repos["spaces"].save(Space(0, "Empty", plc_config={"type": "simulated"}, cameras=[
            Camera(0, 0, "empty-cam", "file", {"path": str(tmp_path / "empty.avi")})]))
        rt.start_space(sp2.id)
        eventually(lambda: rt.snapshots()[sp2.id].status == "CLEAR", timeout=60, message="clear scene")
        mon2 = rt.monitor(sp2.id)
        eventually(lambda: mon2.crane().permit, timeout=10, message="sim crane permitted")
        time.sleep(1.0)
        assert rt.snapshots()[sp2.id].status == "CLEAR"
    finally:
        rt.shutdown()
