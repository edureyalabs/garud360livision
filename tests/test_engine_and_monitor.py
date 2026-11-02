# tests/test_engine_and_monitor.py
import time

import pytest

from garud360.core.detection.engine import InferenceService
from garud360.core.models import Camera, Space
from garud360.core.space.interlock import Status
from garud360.core.space.monitor import SpaceMonitor, SpaceStartError
from tests.conftest import eventually
from tests.fakes import FakeBackend, FakeReader


@pytest.fixture()
def rig(repos, tmp_path):
    FakeReader.instances.clear()
    st = repos["settings"]
    st.update({"inference_fps": 30.0, "trigger_frames": 2, "release_frames": 3, "stale_frame_s": 1.0,
               "detection_stale_s": 1.0, "plc_heartbeat_s": 0.2, "plc_input_poll_s": 0.05,
               "snapshot_cooldown_s": 0, "connect_timeout_s": 2.0})
    backend = FakeBackend()
    engine = InferenceService(st.all, backend_factory=lambda cfg: backend)
    engine.start()
    made = []

    def build(n_cams=2, plc=None, overrides=None, roi=None):
        cams = [Camera(i + 1, 1, f"cam{i+1}", "droidcam", {"ip": "10.0.0.5", "port": 4747}, roi if i == 0 else None)
                for i in range(n_cams)]
        space = Space(1, "Bay", plc_config=plc or {"type": "simulated"}, overrides=overrides or {}, cameras=cams)
        mon = SpaceMonitor(space, lambda sp: st.effective(sp.overrides), repos["events"], engine, tmp_path / "snaps",
                           reader_factory=FakeReader)
        made.append(mon)
        return mon

    yield build, engine, backend, repos
    for m in made:
        m.stop()
    engine.stop()


def crane_permit(mon):
    snap = mon.crane()
    return snap.permit if snap else None


def test_full_cycle_person_block_release_and_events(rig):
    build, engine, backend, repos = rig
    mon = build()
    mon.start()
    eventually(lambda: mon.snapshot().status_enum == Status.CLEAR, message="CLEAR after start")
    eventually(lambda: crane_permit(mon) is True, message="crane permitted")
    cam = FakeReader.instances[0]
    cam.person = True
    eventually(lambda: mon.snapshot().status_enum == Status.PERSON, message="PERSON status")
    snap = mon.snapshot()
    assert snap.alarm and snap.siren and not snap.permit and snap.persons >= 1
    eventually(lambda: crane_permit(mon) is False, message="crane physically blocked in the sim")
    cam.person = False
    eventually(lambda: mon.snapshot().status_enum == Status.CLEAR, message="released")
    eventually(lambda: crane_permit(mon) is True)
    kinds = [e.kind for e in repos["events"].search()]
    for k in ("person_violation", "crane_blocked", "crane_released", "space_started"):
        assert k in kinds, kinds
    ev = repos["events"].search(kinds=["person_violation"])[0]
    assert ev.snapshot_path and (mon.snapshots_root / ev.snapshot_path).exists()
    assert ev.camera_name == "cam1"
    mon.stop()
    kinds = [e.kind for e in repos["events"].search()]
    assert "space_stopped" in kinds


def test_low_confidence_detections_do_not_count(rig):
    build, engine, backend, repos = rig
    mon = build(1, overrides={"person_conf": 0.95})
    mon.start()
    eventually(lambda: mon.snapshot().status_enum == Status.CLEAR)
    FakeReader.instances[0].person = True
    time.sleep(0.6)
    assert mon.snapshot().status_enum == Status.CLEAR


def test_camera_fault_blocks_and_recovers(rig):
    build, engine, backend, repos = rig
    mon = build()
    mon.start()
    eventually(lambda: mon.snapshot().status_enum == Status.CLEAR)
    FakeReader.instances[1].connected = False
    eventually(lambda: mon.snapshot().status_enum == Status.CAMERA_FAULT, message="fault status")
    assert not mon.snapshot().permit
    eventually(lambda: crane_permit(mon) is False)
    FakeReader.instances[1].connected = True
    eventually(lambda: mon.snapshot().status_enum == Status.CLEAR, message="recovery")
    kinds = [e.kind for e in repos["events"].search()]
    assert "camera_fault" in kinds and "camera_recovered" in kinds


def test_frozen_stream_and_stalled_detector_are_faults(rig):
    build, engine, backend, repos = rig
    mon = build(1)
    mon.start()
    eventually(lambda: mon.snapshot().status_enum == Status.CLEAR)
    FakeReader.instances[0].frozen = True
    eventually(lambda: mon.snapshot().status_enum == Status.CAMERA_FAULT, message="frozen stream")
    FakeReader.instances[0].frozen = False
    eventually(lambda: mon.snapshot().status_enum == Status.CLEAR)
    backend.fail = True                         # detector keeps failing -> watchdog must block the crane
    eventually(lambda: mon.snapshot().status_enum == Status.CAMERA_FAULT, timeout=6, message="detector watchdog")
    backend.fail = False
    eventually(lambda: mon.snapshot().status_enum == Status.CLEAR, timeout=8)


def test_fault_blocking_disabled_per_space(rig):
    build, engine, backend, repos = rig
    mon = build(1, overrides={"camera_fault_blocks_crane": False})
    mon.start()
    eventually(lambda: mon.snapshot().status_enum == Status.CLEAR)
    FakeReader.instances[0].connected = False
    eventually(lambda: mon.snapshot().status_enum == Status.CAMERA_FAULT)
    assert mon.snapshot().permit


def test_latch_pause_and_reset(rig):
    build, engine, backend, repos = rig
    mon = build(1, overrides={"latch_until_reset": True})
    mon.start()
    eventually(lambda: mon.snapshot().status_enum == Status.CLEAR)
    cam = FakeReader.instances[0]
    cam.person = True
    eventually(lambda: mon.snapshot().status_enum == Status.LATCHED)
    assert mon.reset("tester") is False         # person still there
    cam.person = False
    time.sleep(0.4)
    assert mon.snapshot().status_enum == Status.LATCHED
    assert mon.reset("tester") is True
    eventually(lambda: mon.snapshot().status_enum == Status.CLEAR)
    # pause: person present but crane permitted, AI off
    cam.person = True
    eventually(lambda: mon.snapshot().status_enum == Status.LATCHED)
    mon.pause(1, "tester")
    eventually(lambda: mon.snapshot().status_enum == Status.PAUSED)
    assert mon.snapshot().permit and not mon.snapshot().alarm
    eventually(lambda: crane_permit(mon) is True)
    assert all(not c.ai_active for c in mon.snapshot().cameras)
    mon.resume("tester")
    eventually(lambda: mon.snapshot().status_enum in (Status.LATCHED, Status.PERSON))
    kinds = [e.kind for e in repos["events"].search()]
    assert "paused" in kinds and "resumed" in kinds and "reset" in kinds


def test_roi_excludes_person_outside_zone(rig):
    build, engine, backend, repos = rig
    # person box is x 100..200 of 320 -> zone on the far right (x>0.8) must ignore him
    mon = build(1, roi=[(0.8, 0.0), (1.0, 0.0), (1.0, 1.0), (0.8, 1.0)])
    mon.start()
    eventually(lambda: mon.snapshot().status_enum == Status.CLEAR)
    FakeReader.instances[0].person = True
    time.sleep(0.6)
    assert mon.snapshot().status_enum == Status.CLEAR
    mon.apply_settings()
    assert mon.render_camera(1) is not None


def test_stop_blocks_crane_by_default_and_can_release(rig):
    build, engine, backend, repos = rig
    for block, expect in ((True, False), (False, True)):
        FakeReader.instances.clear()
        mon = build(1, overrides={"block_on_stop": block})
        mon.start()
        eventually(lambda: mon.snapshot().status_enum == Status.CLEAR)
        driver = mon._driver
        mon.stop()
        assert driver.snapshot().permit is expect or driver._bits.get("SIM_PERMIT") is expect


def test_start_validation(rig):
    build, *_ = rig
    mon = build(0)
    with pytest.raises(SpaceStartError, match="no enabled cameras"):
        mon.start()
    mon = build(1, plc={"type": "modbus_tcp", "host": "", "permit_address": "C1"})
    with pytest.raises(SpaceStartError, match="Output channel"):
        mon.start()


def test_scheduler_is_fair_and_skips_inactive(rig):
    build, engine, backend, repos = rig
    backend.delay = 0.02
    mon = build(6)
    mon.start()
    eventually(lambda: all(p.inferences >= 5 for p in mon.pipelines.values()), timeout=8, message="all cams served")
    counts = [p.inferences for p in mon.pipelines.values()]
    assert max(counts) <= 3 * max(min(counts), 1), counts      # nobody starved
    mon.pause(1)
    eventually(lambda: mon.snapshot().status_enum == Status.PAUSED)
    before = [p.inferences for p in mon.pipelines.values()]
    time.sleep(0.5)
    assert [p.inferences for p in mon.pipelines.values()] == before   # AI really off while paused
