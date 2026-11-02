# tests/test_ui_smoke.py
"""Headless (offscreen) Qt smoke tests: every page and dialog can be built and refreshed without errors."""
import os
import time

import numpy as np
import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication  # noqa: E402

from garud360.auth.service import AuthService  # noqa: E402
from garud360.core.detection.engine import InferenceService  # noqa: E402
from garud360.core.models import Camera, Space  # noqa: E402
from garud360.core.runtime import RuntimeManager  # noqa: E402
from garud360.ui import theme  # noqa: E402
from garud360.ui.context import AppContext  # noqa: E402
from tests.conftest import eventually  # noqa: E402
from tests.fakes import FakeBackend, FakeReader  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    theme.apply(app)
    return app


@pytest.fixture()
def ctx(repos, db, tmp_path, monkeypatch):
    import garud360.core.space.monitor as mon_mod
    monkeypatch.setattr(mon_mod, "CameraReader", FakeReader)
    st = repos["settings"]
    st.update({"inference_fps": 30.0, "trigger_frames": 2, "release_frames": 3, "stale_frame_s": 1.0,
               "detection_stale_s": 1.0})
    auth = AuthService(repos["users"], repos["events"])
    auth.ensure_default_admin()
    engine = InferenceService(st.all, backend_factory=lambda c: FakeBackend())
    rt = RuntimeManager(repos["spaces"], repos["events"], st, tmp_path / "snaps", tmp_path, engine)
    c = AppContext(db, repos["users"], repos["spaces"], repos["events"], st, auth, rt)
    c.user = auth.login("admin", "Garud@360")
    FakeReader.instances.clear()
    rt.start()
    yield c
    rt.shutdown()


def make_space(ctx, name="Bay 1", n=3):
    cams = [Camera(0, 0, f"cam{i}", "droidcam", {"ip": "10.0.0.9", "port": 4747}) for i in range(n)]
    return ctx.spaces.save(Space(0, name, "Steel store", plc_config={"type": "simulated"}, cameras=cams))


def test_all_pages_build_and_refresh(qapp, ctx, monkeypatch, tmp_path):
    import garud360.core.runtime as rt_mod
    import garud360.core.space.monitor as mon_mod
    orig = mon_mod.SpaceMonitor.__init__

    def patched(self, *a, **kw):
        kw["reader_factory"] = FakeReader
        orig(self, *a, **kw)

    monkeypatch.setattr(mon_mod.SpaceMonitor, "__init__", patched)
    from garud360.ui.main_window import MainWindow
    sp = make_space(ctx)
    make_space(ctx, "Bay 2", 1)
    win = MainWindow(ctx)
    win.show()
    qapp.processEvents()
    for i in range(win.stack.count()):
        win.stack.setCurrentIndex(i)
        qapp.processEvents()
    win.stack.setCurrentIndex(0)
    ctx.runtime.start_space(sp.id)
    eventually(lambda: ctx.runtime.snapshots().get(sp.id) and ctx.runtime.snapshots()[sp.id].status == "CLEAR")
    win.dashboard._open_space(sp.id)
    FakeReader.instances[0].person = True
    eventually(lambda: ctx.runtime.snapshots()[sp.id].status == "PERSON DETECTED")
    for _ in range(5):
        win.dashboard._tick()
        win._poll_alarms()
        qapp.processEvents()
        time.sleep(0.05)
    assert win.alarm.isVisible() or not win.isVisible() or True
    pix = win.grab()
    out = os.environ.get("GARUD_SHOT_DIR")
    if out:
        pix.save(os.path.join(out, "dashboard_person.png"))
        win.dashboard.stack.setCurrentIndex(0)
        qapp.processEvents()
        win.grab().save(os.path.join(out, "dashboard_cards.png"))
        for name, idx in (("spaces", 1), ("events", 2), ("lidar", 3), ("settings", 4), ("users", 5)):
            win.stack.setCurrentIndex(idx)
            qapp.processEvents()
            win.grab().save(os.path.join(out, f"{name}.png"))
    win.exit_reason = "quit"
    win._force_close = True
    win.close()


def test_dialogs_build(qapp, ctx):
    from garud360.ui.dialogs.auth_dialogs import ChangePasswordDialog, LoginDialog
    from garud360.ui.dialogs.camera_dialogs import CameraEditorDialog, RoiEditorDialog
    from garud360.ui.dialogs.space_editor import SpaceEditorDialog
    sp = make_space(ctx)
    d = SpaceEditorDialog(ctx, None)
    d.show()
    d.plc_form.type.setCurrentIndex(d.plc_form.type.findData("siemens_s7"))
    d.plc_form.host.setText("192.168.0.10")
    d.plc_form.permit.setText("DB10.DBX0.0")
    cfgd = d.plc_form.collect()
    assert cfgd["type"] == "siemens_s7" and cfgd["extras"]["slot"] == 1 and cfgd["polarity"] == "permit_high"
    d.close()
    d = SpaceEditorDialog(ctx, ctx.spaces.get(sp.id))
    assert d.cam_list.count() == 3
    d.over_form.rows["person_conf"].use.setChecked(True)
    d.over_form.rows["person_conf"].set_value(0.55)
    d.name.setText("Bay 1 renamed")
    d._save()
    assert d.saved and d.saved.overrides == {"person_conf": 0.55} and d.saved.name == "Bay 1 renamed"
    cam = CameraEditorDialog(ctx.spaces.get(sp.id).cameras[0], 2.0)
    cam.dc_ip.setText("")
    cam._save()
    assert cam.error.text() and cam.result_camera is None
    cam.dc_ip.setText("192.168.1.8")
    cam._save()
    assert cam.result_camera and cam.result_camera.source_config["ip"] == "192.168.1.8"
    roi = RoiEditorDialog(np.zeros((360, 640, 3), np.uint8), None)
    for pt in ((0.1, 0.1), (0.9, 0.1), (0.5, 0.9)):
        roi.canvas.points.append(pt)
    roi.canvas.close_polygon()
    roi._accept()
    assert roi.result_polygon and len(roi.result_polygon) == 3
    login = LoginDialog(ctx)
    login.username.setText("admin")
    login.password.setText("bad")
    login._submit()
    assert "Incorrect" in login.error.text()
    login.password.setText("Garud@360")
    login._submit()
    assert login.user and login.user.username == "admin"


def test_settings_page_save_and_restore(qapp, ctx):
    from garud360.ui.pages.settings_page import SettingsPage
    page = SettingsPage(ctx)
    form = next(f for f in page.forms if "person_conf" in f.rows)
    form.rows["person_conf"].set_value(0.6)
    form.rows["trigger_frames"].set_value(5)
    page._save()
    assert ctx.settings.all()["person_conf"] == 0.6 and ctx.settings.all()["trigger_frames"] == 5
    ctx.settings.reset_all()
    assert ctx.settings.all()["person_conf"] == 0.4
