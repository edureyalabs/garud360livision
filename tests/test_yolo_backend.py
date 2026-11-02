# tests/test_yolo_backend.py
"""YoloBackend wiring tested against a stand-in 'ultralytics' module (the real model is covered by the install check)."""
import sys
import types

import numpy as np

from garud360.core.detection.engine import ModelConfig, YoloBackend


class _T:
    def __init__(self, a):
        self.a = np.asarray(a)

    def cpu(self):
        return self

    def numpy(self):
        return self.a


class _Boxes:
    def __init__(self, xyxy, conf):
        self.xyxy, self.conf = _T(xyxy), _T(conf)

    def __len__(self):
        return len(self.conf.a)


class _Masks:
    def __init__(self, xy):
        self.xy = xy


class _Result:
    def __init__(self, n, masks=True):
        self.boxes = _Boxes([[10 * i, 10, 10 * i + 50, 100] for i in range(n)], [0.9 - 0.1 * i for i in range(n)])
        self.masks = _Masks([np.array([[0, 0], [5, 0], [5, 5]], np.float32) for _ in range(n)]) if masks and n else None


def install_fake(monkeypatch, record):
    class FakeYOLO:
        def __init__(self, name, **kw):
            record["init"] = (name, kw)
            self.names = {0: "person", 1: "bicycle"}

        def predict(self, frames, **kw):
            record.setdefault("calls", []).append(kw)
            return [_Result(len(frames) % 3 + (1 if f[0, 0, 0] else 0), masks=kw.get("conf", 0) < 0.99) for f in frames]

    mod = types.ModuleType("ultralytics")
    mod.YOLO = FakeYOLO
    mod.settings = types.SimpleNamespace(update=lambda d: record.setdefault("settings", d))
    monkeypatch.setitem(sys.modules, "ultralytics", mod)


def test_weights_naming():
    assert ModelConfig("segment", "n").weights() == "yolo26n-seg.pt"
    assert ModelConfig("detect", "x").weights() == "yolo26x.pt"
    assert ModelConfig("segment", "s", custom_path="C:/m/best.pt").weights() == "C:/m/best.pt"


def test_load_predict_conversion(monkeypatch, tmp_path):
    rec = {}
    install_fake(monkeypatch, rec)
    monkeypatch.setenv("GARUD360_DATA_DIR", str(tmp_path))
    be = YoloBackend(ModelConfig("segment", "n", "", "auto", 640, False))
    be.load()
    assert rec["init"][0] == "yolo26n-seg.pt" and rec["init"][1] == {"task": "segment"}
    assert rec["settings"]["sync"] is False and rec["settings"]["weights_dir"].startswith(str(tmp_path))
    warm = rec["calls"][0]
    assert warm["classes"] == [0] and warm["imgsz"] == 640 and warm["verbose"] is False and warm["device"] is None
    frames = [np.zeros((48, 64, 3), np.uint8), np.zeros((48, 64, 3), np.uint8)]
    out = be.predict(frames, 0.39)
    assert len(out) == 2 and all(len(d) >= 1 for d in out)
    d = out[0][0]
    assert d.box == (0.0, 10.0, 50.0, 100.0) and abs(d.conf - 0.9) < 1e-6 and d.polygon is not None
    assert rec["calls"][-1]["conf"] == 0.39
    assert be.predict(frames, 0.995)[0][0].polygon is None          # no masks (detect model) -> boxes only


def test_custom_model_has_no_forced_task_and_device_passthrough(monkeypatch, tmp_path):
    rec = {}
    install_fake(monkeypatch, rec)
    monkeypatch.setenv("GARUD360_DATA_DIR", str(tmp_path))
    be = YoloBackend(ModelConfig("segment", "n", "D:/models/crane_openvino_model", "intel:gpu", 960, True))
    be.load()
    assert rec["init"] == ("D:/models/crane_openvino_model", {})
    assert rec["calls"][-1]["device"] == "intel:gpu" and rec["calls"][-1]["imgsz"] == 960
    assert rec["calls"][-1]["half"] is False                         # half only with CUDA
