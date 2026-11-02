# garud360/core/detection/engine.py
"""Detection model backend and the shared, fair inference scheduler.

One model serves every camera of every running space. Cameras are served oldest-first
(round-robin by waiting time) so no camera can be starved - a starved camera would
otherwise look 'clear' while nobody is actually looking at it.
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Protocol

import numpy as np

log = logging.getLogger(__name__)


@dataclass
class Detection:
    box: tuple[float, float, float, float]          # x1, y1, x2, y2 in frame pixels
    conf: float
    polygon: np.ndarray | None = None               # Nx2 float32 (segment models)


@dataclass(frozen=True)
class ModelConfig:
    task: str = "segment"
    size: str = "n"
    custom_path: str = ""
    device: str = "auto"
    imgsz: int = 640
    half: bool = False

    @classmethod
    def from_settings(cls, s: dict[str, Any]) -> "ModelConfig":
        return cls(str(s["model_task"]), str(s["model_size"]), str(s["custom_model_path"]).strip(),
                   str(s["inference_device"]), int(s["image_size"]), bool(s["half_precision"]))

    def label(self) -> str:
        """Friendly name for the UI (the weights file name stays internal)."""
        if self.custom_path:
            return "custom model"
        return f"{self.task} model (size {self.size})"

    def weights(self) -> str:
        if self.custom_path:
            return self.custom_path
        return f"yolo26{self.size}{'-seg' if self.task == 'segment' else ''}.pt"


class InferenceBackend(Protocol):
    def load(self) -> None: ...
    def predict(self, frames: list[np.ndarray], conf: float) -> list[list[Detection]]: ...
    def close(self) -> None: ...


class YoloBackend:
    """Ultralytics model wrapper. Imports are lazy so the UI starts instantly."""

    def __init__(self, cfg: ModelConfig) -> None:
        self.cfg = cfg
        self.model: Any = None
        self._person_id = 0
        self._device: str | None = None
        self._half = False
        self._precision_key = "half"

    def load(self) -> None:
        try:
            from ultralytics import YOLO, settings  # noqa: WPS433
        except ImportError as exc:  # pragma: no cover - depends on install
            raise RuntimeError("The 'ultralytics' package is not installed.") from exc
        from garud360 import paths
        try:
            settings.update({"weights_dir": str(paths.models_dir()), "sync": False})
        except Exception:  # noqa: BLE001 - settings are optional
            log.debug("Could not update ultralytics settings", exc_info=True)
        try:
            from ultralytics.cfg import DEFAULT_CFG_DICT
            self._precision_key = "quantize" if "quantize" in DEFAULT_CFG_DICT else "half"
        except Exception:  # noqa: BLE001
            self._precision_key = "half"
        kwargs: dict[str, Any] = {}
        local: Any = None
        if self.cfg.custom_path:
            target = self.cfg.custom_path
        else:
            # An absolute path inside our data folder: Ultralytics downloads missing standard weights exactly there
            # (a bare file name would be downloaded into the current directory, which may be read-only).
            local = paths.models_dir() / self.cfg.weights()
            target = str(local)
            kwargs["task"] = "segment" if self.cfg.task == "segment" else "detect"
        log.info("Loading model %s", target)
        try:
            self.model = YOLO(target, **kwargs)
        except Exception:
            if local is None:
                raise
            # A broken / half-downloaded file makes Ultralytics try to resume it and fail (HTTP 416): start clean.
            log.warning("Model %s could not be loaded - removing partial file and downloading again", local)
            for stale in (local, local.with_name(local.name + ".part")):
                try:
                    stale.unlink(missing_ok=True)
                except OSError:
                    pass
            self.model = YOLO(target, **kwargs)
        names = getattr(self.model, "names", None) or {}
        self._person_id = next((int(i) for i, n in dict(names).items() if str(n).lower() == "person"), 0)
        self._device = None if self.cfg.device == "auto" else self.cfg.device
        self._half = bool(self.cfg.half) and self._cuda_selected()
        # warm-up so the first real frame is not slow
        self._run([np.zeros((self.cfg.imgsz, self.cfg.imgsz, 3), np.uint8)], 0.5)
        log.info("Model ready (device=%s, imgsz=%d, fp16=%s)", self._device or "auto", self.cfg.imgsz, self._half)

    def _cuda_selected(self) -> bool:
        if self._device and self._device.startswith("cuda"):
            return True
        if self._device is None:
            try:
                import torch
                return bool(torch.cuda.is_available())
            except Exception:  # noqa: BLE001
                return False
        return False

    def _run(self, frames: list[np.ndarray], conf: float) -> list[Any]:
        extra: dict[str, Any] = {}
        if self._half:                       # newer Ultralytics renamed half -> quantize=16
            extra[self._precision_key] = 16 if self._precision_key == "quantize" else True
        return self.model.predict(frames, imgsz=self.cfg.imgsz, conf=conf, classes=[self._person_id],
                                  device=self._device, verbose=False, **extra)

    def predict(self, frames: list[np.ndarray], conf: float) -> list[list[Detection]]:
        results = self._run(frames, conf)
        out: list[list[Detection]] = []
        for r in results:
            dets: list[Detection] = []
            boxes = r.boxes
            if boxes is not None and len(boxes):
                xyxy = boxes.xyxy.cpu().numpy()
                confs = boxes.conf.cpu().numpy()
                polys = None
                if getattr(r, "masks", None) is not None:
                    polys = r.masks.xy
                    if polys is None or len(polys) != len(xyxy):
                        polys = None
                for i in range(len(xyxy)):
                    poly = None
                    if polys is not None and len(polys[i]) >= 3:
                        poly = np.asarray(polys[i], np.float32)
                    dets.append(Detection(tuple(float(v) for v in xyxy[i]), float(confs[i]), poly))  # type: ignore[arg-type]
            out.append(dets)
        return out

    def close(self) -> None:
        self.model = None


class InferenceClient(Protocol):
    name: str
    conf: float
    def wants_frame(self, now: float) -> bool: ...
    def take_frame(self) -> np.ndarray | None: ...
    def last_served(self) -> float: ...
    def deliver(self, detections: list[Detection] | None, error: str | None, now: float) -> None: ...


@dataclass
class EngineStatus:
    state: str = "idle"          # idle | loading | ready | error
    message: str = ""
    model: str = ""
    ms_per_image: float = 0.0
    clients: int = 0
    demand_fps: float = 0.0


class InferenceService:
    def __init__(self, settings_getter: Callable[[], dict[str, Any]],
                 backend_factory: Callable[[ModelConfig], InferenceBackend] = YoloBackend) -> None:
        self._settings = settings_getter
        self._factory = backend_factory
        self._clients: list[InferenceClient] = []
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._backend: InferenceBackend | None = None
        self._cfg: ModelConfig | None = None
        self._status = EngineStatus()
        self._ema_ms = 0.0
        self._consecutive_fail = 0
        self._retry_at = 0.0

    # -- lifecycle -------------------------------------------------------------
    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="inference", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5.0)
        if self._backend:
            try:
                self._backend.close()
            except Exception:  # noqa: BLE001
                pass
            self._backend = None

    def register(self, client: InferenceClient) -> None:
        with self._lock:
            if client not in self._clients:
                self._clients.append(client)

    def unregister(self, client: InferenceClient) -> None:
        with self._lock:
            if client in self._clients:
                self._clients.remove(client)

    def status(self) -> EngineStatus:
        with self._lock:
            st = EngineStatus(self._status.state, self._status.message, self._status.model, self._ema_ms,
                              len(self._clients), 0.0)
        return st

    def request_reload(self) -> None:
        self._cfg = None
        self._retry_at = 0.0

    # -- internals -------------------------------------------------------------
    def _set_status(self, state: str, message: str = "", model: str = "") -> None:
        with self._lock:
            self._status.state, self._status.message = state, message
            if model:
                self._status.model = model

    def _ensure_backend(self) -> bool:
        wanted = ModelConfig.from_settings(self._settings())
        if self._backend is not None and wanted == self._cfg:
            return True
        now = time.monotonic()
        if now < self._retry_at and wanted == self._cfg:
            return False
        if self._backend is not None:
            try:
                self._backend.close()
            except Exception:  # noqa: BLE001
                pass
            self._backend = None
        self._cfg = wanted
        self._set_status("loading", "", wanted.label())
        try:
            backend = self._factory(wanted)
            backend.load()
        except Exception as exc:  # noqa: BLE001 - surface any load failure to the UI
            log.exception("Model load failed")
            self._set_status("error", f"{type(exc).__name__}: {exc}", wanted.label())
            self._retry_at = time.monotonic() + 15.0
            return False
        self._backend = backend
        self._consecutive_fail = 0
        self._set_status("ready", "", wanted.label())
        return True

    def _collect(self, max_batch: int) -> list[tuple[InferenceClient, np.ndarray]]:
        now = time.monotonic()
        with self._lock:
            clients = list(self._clients)
        due = [c for c in clients if c.wants_frame(now)]
        due.sort(key=lambda c: c.last_served())
        batch: list[tuple[InferenceClient, np.ndarray]] = []
        for c in due[:max_batch]:
            frame = c.take_frame()
            if frame is not None:
                batch.append((c, frame))
        return batch

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                with self._lock:
                    has_clients = bool(self._clients)
                if not has_clients:
                    self._set_status("idle" if self._backend is None else "ready", self._status.message)
                    self._stop.wait(0.2)
                    continue
                if not self._ensure_backend():
                    self._stop.wait(0.5)
                    continue
                batch = self._collect(max(1, int(self._settings()["max_batch_size"])))
                if not batch:
                    self._stop.wait(0.005)
                    continue
                self._infer(batch)
            except Exception:  # noqa: BLE001 - the loop must never die
                log.exception("Inference loop error")
                self._stop.wait(0.5)

    def _infer(self, batch: list[tuple[InferenceClient, np.ndarray]]) -> None:
        assert self._backend is not None
        conf = max(min(c.conf for c, _ in batch) - 0.01, 0.01)
        t0 = time.perf_counter()
        try:
            results = self._backend.predict([f for _, f in batch], conf)
            if len(results) != len(batch):
                raise RuntimeError("backend returned a wrong number of results")
        except Exception:  # noqa: BLE001
            log.exception("Batch inference failed; retrying frame by frame")
            results = []
            ok_any = False
            for c, f in batch:
                try:
                    results.append(self._backend.predict([f], conf)[0])
                    ok_any = True
                except Exception as exc:  # noqa: BLE001
                    results.append(exc)  # type: ignore[arg-type]
            if not ok_any:
                self._consecutive_fail += 1
                if self._consecutive_fail >= 3:
                    first = next((r for r in results if isinstance(r, Exception)), None)
                    self._set_status("error", f"Inference keeps failing: {first}", self._status.model)
                    self._cfg = None            # force a reload
                    self._retry_at = time.monotonic() + 5.0
            else:
                self._consecutive_fail = 0
        else:
            self._consecutive_fail = 0
        per_img = (time.perf_counter() - t0) * 1000.0 / len(batch)
        self._ema_ms = per_img if self._ema_ms == 0 else 0.9 * self._ema_ms + 0.1 * per_img
        now = time.monotonic()
        for (client, _), res in zip(batch, results):
            if isinstance(res, Exception):
                client.deliver(None, f"{type(res).__name__}: {res}", now)
            else:
                client.deliver(res, None, now)
