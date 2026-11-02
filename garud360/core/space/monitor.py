# garud360/core/space/monitor.py
"""SpaceMonitor: runs ONE space - cameras, detection, interlock decision, PLC output and events."""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import cv2
import numpy as np

from garud360.core.camera.reader import CameraReader
from garud360.core.camera.source import build_open_specs
from garud360.core.detection.engine import InferenceService
from garud360.core.detection.pipeline import CameraPipeline
from garud360.core.models import (EV_BLOCKED, EV_CAM_FAULT, EV_CAM_OK, EV_PAUSED, EV_PERSON, EV_PLC_FAULT, EV_PLC_OK,
                                  EV_RELEASED, EV_RESET, EV_RESUMED, EV_STARTED, EV_STOPPED, SEV_CRIT, SEV_INFO,
                                  SEV_WARN, Space)
from garud360.core.plc.base import PlcConfig, PlcError
from garud360.core.plc.registry import create_driver, driver_class
from garud360.core.plc.simulated import SimulatedPlcDriver
from garud360.core.plc.worker import PlcWorker
from garud360.core.sim.crane import CraneSnapshot
from garud360.core.space.interlock import Interlock, InterlockInputs, InterlockState, Status
from garud360.db.repositories import EventRepository, local_day

log = logging.getLogger(__name__)


class SpaceStartError(Exception):
    """The space cannot be started (bad configuration)."""


def prepare_plc_config(raw: dict[str, Any]) -> PlcConfig:
    """Fill defaults for the built-in simulated channel."""
    cfg = PlcConfig.from_dict(raw)
    if cfg.type == "simulated":
        cfg.permit_address = cfg.permit_address or "SIM_PERMIT"
        cfg.heartbeat_address = cfg.heartbeat_address or "SIM_HB"
        if cfg.extras.get("load_gating"):
            cfg.load_present_address = cfg.load_present_address or "SIM_LOAD"
        else:
            cfg.load_present_address = ""
    return cfg


@dataclass
class CameraStatus:
    camera_id: int
    name: str
    ok: bool
    detail: str
    persons: int
    person_active: bool
    ai_active: bool
    fps: float


@dataclass
class SpaceSnapshot:
    space_id: int
    name: str
    running: bool = False
    stopping: bool = False
    status: str = Status.STOPPED.value
    status_enum: Status = Status.STOPPED
    permit: bool = True
    alarm: bool = False
    siren: bool = False
    reason: str = ""
    latched: bool = False
    pause_remaining_s: float = 0.0
    cameras: list[CameraStatus] = field(default_factory=list)
    plc_type: str = ""
    plc_connected: bool = False
    plc_error: str = ""
    plc_confirmed_permit: bool | None = None
    started_at: float = 0.0

    @property
    def persons(self) -> int:
        return sum(c.persons for c in self.cameras)

    @property
    def camera_faults(self) -> int:
        return sum(1 for c in self.cameras if not c.ok)


class SpaceMonitor:
    def __init__(self, space: Space, settings_getter: Callable[[Space], dict[str, Any]], events: EventRepository,
                 engine: InferenceService, snapshots_root: Path,
                 reader_factory: Callable[..., CameraReader] = CameraReader,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.space = space
        self._get_settings = settings_getter
        self.events = events
        self.engine = engine
        self.snapshots_root = snapshots_root
        self._reader_factory = reader_factory
        self._clock = clock
        self._eff = settings_getter(space)
        self.plc_cfg = prepare_plc_config(space.plc_config)
        self.pipelines: dict[int, CameraPipeline] = {}
        self._interlock = Interlock()
        self._state = InterlockState(Status.STARTING, False, False, True, "Starting")
        self._lock = threading.RLock()
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._plc: PlcWorker | None = None
        self._driver: Any = None
        self._started_t = 0.0
        self._ready = False
        self._running = False
        self._prev_person: dict[int, bool] = {}
        self._prev_ok: dict[int, bool] = {}
        self._last_snapshot_t: dict[int, float] = {}
        self._prev_permit: bool | None = None
        self._prev_status: Status | None = None
        self._reset_result: bool | None = None
        self._reset_done = threading.Event()
        self._last_plc_fault_logged = False

    # ============================================================== lifecycle ==
    def start(self) -> None:
        cams = [c for c in self.space.cameras if c.enabled]
        if not cams:
            raise SpaceStartError("This space has no enabled cameras.")
        try:
            errs = driver_class(self.plc_cfg.type).validate_config(self.plc_cfg)
        except PlcError as exc:
            errs = [str(exc)]
        if errs:
            raise SpaceStartError(f"Output channel: {errs[0]}")
        try:
            specs = {c.id: build_open_specs(c.source_type, c.source_config) for c in cams}
        except ValueError as exc:
            raise SpaceStartError(str(exc)) from None
        with self._lock:
            self._started_t = self._clock()
            self._running = True
            self._ready = False
            self._stop.clear()
            sget = lambda: self._eff  # noqa: E731
            for c in cams:
                reader = self._reader_factory(f"{self.space.name}/{c.name}", specs[c.id], sget)
                self.pipelines[c.id] = CameraPipeline(c.id, c.name, reader, c.roi, self._eff, self._wake.set)
            driver = create_driver(self.plc_cfg, float(self._eff["plc_timeout_s"]))
            self._driver = driver
            self._plc = PlcWorker(driver, self.plc_cfg, sget, self._on_plc_link, self._on_plc_reset,
                                  self._on_plc_pause)
            self._plc.set_permit(False)           # fail-safe: blocked until the cameras are proven healthy
            self._plc.start()
            for p in self.pipelines.values():
                p.reader.start()
                p.set_active(True)
                self.engine.register(p)
        self._thread = threading.Thread(target=self._loop, name=f"space-{self.space.id}", daemon=True)
        self._thread.start()
        self._log(EV_STARTED, f"Monitoring started ({len(cams)} camera(s), output: {self.plc_cfg.type}).")

    def stop(self, reason: str = "Stopped by operator") -> None:
        with self._lock:
            if not self._running:
                return
            self._running = False
        self._stop.set()
        self._wake.set()
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=3.0)
        for p in self.pipelines.values():
            self.engine.unregister(p)
            p.set_active(False)
        for p in self.pipelines.values():
            p.reader.request_stop()
        final = None if self._plc is None else (not bool(self._eff["block_on_stop"]))
        if self._plc is not None:
            self._plc.shutdown(final)
        for p in self.pipelines.values():
            p.reader.join(2.0)
        self._log(EV_STOPPED, f"Monitoring stopped. {reason}. Crane output: "
                              f"{'released' if final else 'blocked' if final is not None else 'unchanged'}.")
        with self._lock:
            self._state = InterlockState(Status.STOPPED, bool(final), False, False, reason)

    @property
    def running(self) -> bool:
        return self._running

    # ================================================================ commands ==
    def pause(self, minutes: float, user: str = "") -> float:
        limit = float(self._eff["max_pause_minutes"])
        minutes = max(1.0, min(float(minutes), limit))
        self._interlock.pause(minutes * 60.0, self._clock())
        self._wake.set()
        self._log(EV_PAUSED, f"AI paused for {minutes:g} min{self._by(user)}.", SEV_WARN)
        return minutes

    def resume(self, user: str = "") -> None:
        self._interlock.resume()
        self._wake.set()

    def reset(self, user: str = "") -> bool:
        """Manual reset of a latched violation. Returns True when accepted."""
        was_latched = self._state.latched
        self._reset_done.clear()
        self._reset_result = None
        self._interlock.request_reset()
        self._wake.set()
        self._reset_done.wait(1.5)
        ok = was_latched and bool(self._reset_result)
        why = "accepted" if ok else ("rejected - zone is not clear" if was_latched else "ignored - nothing is latched")
        self._log(EV_RESET, f"Manual reset {why}{self._by(user)}.", SEV_INFO if ok else SEV_WARN)
        return ok

    def apply_settings(self) -> None:
        self._eff = self._get_settings(self.space)
        for p in self.pipelines.values():
            p.update_settings(self._eff)
        self._wake.set()

    # ================================================================= reading ==
    def snapshot(self) -> SpaceSnapshot:
        with self._lock:
            st = self._state
            cams: list[CameraStatus] = []
            for p in self.pipelines.values():
                h = p.health()
                detail = h.detail if h.ok or not h.detail.startswith("Detection stalled") \
                    else h.detail + self._engine_note()
                cams.append(CameraStatus(p.camera_id, p.name, h.ok, detail, p.person_count,
                                         p.person_active, p.ai_active, p.reader.health().fps))
            ps = self._plc.status() if self._plc else None
            plc_down = bool(self._running and ps is not None and not ps.connected
                            and self._clock() - self._started_t > 4.0)
            siren = (st.alarm and bool(self._eff["siren_enabled"])) or \
                    (plc_down and bool(self._eff["siren_on_plc_fault"]) and bool(self._eff["siren_enabled"]))
            return SpaceSnapshot(
                self.space.id, self.space.name, self._running, False, st.status.value, st.status, st.permit,
                st.alarm or plc_down, siren, st.reason, st.latched, st.pause_remaining_s, cams,
                self.plc_cfg.type, bool(ps and ps.connected), ps.error if ps else "",
                ps.confirmed_permit if ps else None, self._started_t)

    def render_camera(self, camera_id: int, max_width: int | None = 640) -> np.ndarray | None:
        p = self.pipelines.get(camera_id)
        if p is None:
            return None
        st = self._state.status
        text = {Status.PAUSED: "AI PAUSED - crane permitted", Status.NO_LOAD: "NO LOAD - AI OFF",
                Status.STARTING: "CHECKING CAMERAS ..."}.get(st, "")
        return p.render(max_width, text)

    def crane(self) -> CraneSnapshot | None:
        d = self._driver
        return d.snapshot() if isinstance(d, SimulatedPlcDriver) else None

    # ================================================================ internals ==
    def _engine_note(self) -> str:
        """Why detection is not running, when the engine itself is the problem."""
        st = self.engine.status()
        if st.state == "error":
            return f" | Detection engine ERROR: {st.message}"
        if st.state == "loading":
            return f" | Detection engine is loading the model ({st.model}) ..."
        return ""

    def _by(self, user: str) -> str:
        return f" by {user}" if user else ""

    def _log(self, kind: str, message: str, severity: str = SEV_INFO, camera_id: int | None = None,
             camera_name: str = "", snapshot: str | None = None) -> None:
        try:
            self.events.add(kind, message, severity=severity, space_id=self.space.id, space_name=self.space.name,
                            camera_id=camera_id, camera_name=camera_name, snapshot_path=snapshot)
        except Exception:  # noqa: BLE001 - a full disk must not stop the interlock
            log.exception("Could not write event")

    def _on_plc_link(self, connected: bool, error: str) -> None:
        if connected:
            if self._last_plc_fault_logged:
                self._log(EV_PLC_OK, "PLC link restored.", SEV_INFO)
            self._last_plc_fault_logged = False
        else:
            self._last_plc_fault_logged = True
            self._log(EV_PLC_FAULT, f"PLC link lost - crane NOT interlocked. {error}", SEV_CRIT)
        self._wake.set()

    def _on_plc_reset(self) -> None:
        self._interlock.request_reset()
        self._reset_done.clear()
        self._wake.set()
        self._log(EV_RESET, "Reset requested from crane remote / PLC input.", SEV_INFO)

    def _on_plc_pause(self) -> None:
        self.pause(float(self._eff["pause_minutes"]), "crane remote")

    def _loop(self) -> None:
        while not self._stop.is_set():
            self._wake.wait(0.1)
            self._wake.clear()
            if self._stop.is_set():
                break
            try:
                self._tick()
            except Exception:  # noqa: BLE001
                log.exception("Interlock tick failed - blocking crane (fail-safe)")
                if self._plc:
                    self._plc.set_permit(False)
                self._stop.wait(0.2)

    def _tick(self) -> None:
        now = self._clock()
        s = self._eff
        healths = {cid: p.health() for cid, p in self.pipelines.items()}
        if not self._ready:
            all_ok = all(h.ok for h in healths.values()) and all(
                p.has_result_since_activation() for p in self.pipelines.values() if p.ai_active)
            grace = float(s["connect_timeout_s"]) + float(s["detection_stale_s"]) + 5.0
            if all_ok or now - self._started_t > grace:
                self._ready = True
        fault = any(not h.ok for h in healths.values())
        person = any(p.person_active for p in self.pipelines.values())
        ps = self._plc.status() if self._plc else None
        gating = bool(self.plc_cfg.load_present_address)
        load = ps.load_present if (ps and gating and ps.connected) else None
        inputs = InterlockInputs(person_active=person, fault_active=fault, starting=not self._ready,
                                 load_present=load, load_gating=gating,
                                 latch_until_reset=bool(s["latch_until_reset"]),
                                 fault_blocks_crane=bool(s["camera_fault_blocks_crane"]))
        state = self._interlock.evaluate(inputs, now)
        if self._reset_result is None and not self._reset_done.is_set():
            self._reset_result = not state.reset_rejected and not state.latched
            self._reset_done.set()
        with self._lock:
            self._state = state
        for p in self.pipelines.values():
            p.set_active(state.ai_active)
        if self._plc:
            self._plc.set_permit(state.permit)
        self._emit_events(state, healths, now)

    def _emit_events(self, state: InterlockState, healths: dict, now: float) -> None:
        s = self._eff
        in_grace = not self._ready
        for cid, p in self.pipelines.items():
            prev = self._prev_person.get(cid, False)
            cur = p.person_active
            if cur and not prev:
                snap = self._save_snapshot(p, now) if bool(s["snapshot_on_violation"]) else None
                self._log(EV_PERSON, f"Person detected ({p.person_count}) - crane blocked.", SEV_CRIT, cid, p.name, snap)
            self._prev_person[cid] = cur
            ok = healths[cid].ok
            prev_ok = self._prev_ok.get(cid, True)
            if not ok and prev_ok and not in_grace:
                d = healths[cid].detail
                if d.startswith("Detection stalled"):
                    d += self._engine_note()
                self._log(EV_CAM_FAULT, f"Camera fault: {d}", SEV_CRIT, cid, p.name)
                self._prev_ok[cid] = False
            elif ok and not prev_ok:
                self._log(EV_CAM_OK, "Camera recovered.", SEV_INFO, cid, p.name)
                self._prev_ok[cid] = True
            elif not ok and in_grace:
                self._prev_ok.setdefault(cid, True)
        if self._prev_permit is not None and state.permit != self._prev_permit:
            if state.permit:
                self._log(EV_RELEASED, f"Crane released ({state.status.value}).", SEV_INFO)
            else:
                self._log(EV_BLOCKED, f"Crane BLOCKED: {state.reason}.", SEV_CRIT)
        elif self._prev_permit is None and not state.permit and state.status != Status.STARTING:
            self._log(EV_BLOCKED, f"Crane BLOCKED: {state.reason}.", SEV_CRIT)
        self._prev_permit = state.permit
        if self._prev_status == Status.PAUSED and state.status != Status.PAUSED:
            self._log(EV_RESUMED, "AI monitoring resumed.", SEV_INFO)
        self._prev_status = state.status

    def _save_snapshot(self, p: CameraPipeline, now: float) -> str | None:
        cooldown = float(self._eff["snapshot_cooldown_s"])
        if now - self._last_snapshot_t.get(p.camera_id, -1e9) < cooldown:
            return None
        try:
            img = p.render(max_width=None)
            rel = f"{local_day()}/s{self.space.id}_c{p.camera_id}_{time.strftime('%H%M%S')}.jpg"
            path = self.snapshots_root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            ok = cv2.imwrite(str(path), img, [cv2.IMWRITE_JPEG_QUALITY, int(self._eff["snapshot_quality"])])
            if ok:
                self._last_snapshot_t[p.camera_id] = now
                return rel.replace("\\", "/")
        except Exception:  # noqa: BLE001
            log.exception("Snapshot failed")
        return None
