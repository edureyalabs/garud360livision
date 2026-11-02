# garud360/core/runtime.py
"""RuntimeManager: owns the shared inference engine, siren and every running SpaceMonitor."""
from __future__ import annotations

import logging
import shutil
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from garud360.core.alerts.siren import SirenController
from garud360.core.detection.engine import EngineStatus, InferenceService
from garud360.core.models import Space
from garud360.core.space.monitor import SpaceMonitor, SpaceSnapshot, SpaceStartError
from garud360.db.repositories import EventRepository, SettingsStore, SpaceRepository

log = logging.getLogger(__name__)


class RuntimeManager:
    def __init__(self, spaces: SpaceRepository, events: EventRepository, settings: SettingsStore,
                 snapshots_root: Path, work_dir: Path, engine: InferenceService | None = None) -> None:
        self.spaces, self.events, self.settings = spaces, events, settings
        self.snapshots_root = snapshots_root
        self.engine = engine or InferenceService(settings.all)
        self.siren = SirenController(settings.all, work_dir)
        self._monitors: dict[int, SpaceMonitor] = {}
        self._stopping: dict[int, threading.Thread] = {}
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._seen_version = settings.version
        self._last_maintenance = 0.0

    # ------------------------------------------------------------------ lifecycle
    def start(self) -> None:
        self.engine.start()
        self._thread = threading.Thread(target=self._housekeeping, name="runtime", daemon=True)
        self._thread.start()

    def shutdown(self) -> None:
        """Stop every space (applying each space's 'block on stop' rule), then the engine."""
        with self._lock:
            ids = list(self._monitors)
        threads = [self._stop_async(i, "Application closing") for i in ids]
        for t in threads:
            if t:
                t.join(timeout=15.0)
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2.0)
        self.siren.close()
        self.engine.stop()

    # ---------------------------------------------------------------------- spaces
    def is_running(self, space_id: int) -> bool:
        with self._lock:
            m = self._monitors.get(space_id)
            return bool(m and m.running) or space_id in self._stopping

    def monitor(self, space_id: int) -> SpaceMonitor | None:
        with self._lock:
            return self._monitors.get(space_id)

    def start_space(self, space_id: int) -> None:
        with self._lock:
            if space_id in self._stopping:
                raise SpaceStartError("This space is still stopping - try again in a moment.")
            if space_id in self._monitors and self._monitors[space_id].running:
                return
            space = self.spaces.get(space_id)
            mon = SpaceMonitor(space, lambda sp: self.settings.effective(sp.overrides), self.events, self.engine,
                               self.snapshots_root)
            mon.start()
            self._monitors[space_id] = mon

    def stop_space(self, space_id: int, reason: str = "Stopped by operator") -> None:
        self._stop_async(space_id, reason)

    def _stop_async(self, space_id: int, reason: str) -> threading.Thread | None:
        with self._lock:
            mon = self._monitors.get(space_id)
            if mon is None or space_id in self._stopping:
                return self._stopping.get(space_id)

            def work() -> None:
                try:
                    mon.stop(reason)
                except Exception:  # noqa: BLE001
                    log.exception("Error stopping space %s", space_id)
                finally:
                    with self._lock:
                        self._monitors.pop(space_id, None)
                        self._stopping.pop(space_id, None)

            t = threading.Thread(target=work, name=f"stop-{space_id}", daemon=True)
            self._stopping[space_id] = t
            t.start()
            return t

    def start_all(self, only_auto: bool = False) -> list[str]:
        errors: list[str] = []
        for sp in self.spaces.list():
            if only_auto and not sp.auto_start:
                continue
            try:
                self.start_space(sp.id)
            except SpaceStartError as exc:
                errors.append(f"{sp.name}: {exc}")
            except Exception as exc:  # noqa: BLE001
                log.exception("Failed to start %s", sp.name)
                errors.append(f"{sp.name}: {exc}")
        return errors

    def stop_all(self) -> None:
        with self._lock:
            ids = list(self._monitors)
        for i in ids:
            self.stop_space(i)

    # --------------------------------------------------------------------- reading
    def snapshots(self) -> dict[int, SpaceSnapshot]:
        with self._lock:
            mons = dict(self._monitors)
            stopping = set(self._stopping)
        out = {}
        for sid, m in mons.items():
            snap = m.snapshot()
            snap.stopping = sid in stopping
            out[sid] = snap
        return out

    def engine_status(self) -> EngineStatus:
        st = self.engine.status()
        with self._lock:
            mons = list(self._monitors.values())
        demand = 0.0
        for m in mons:
            fps_cap = float(m._eff["inference_fps"])  # noqa: SLF001 - same package
            for p in m.pipelines.values():
                if p.ai_active:
                    demand += min(fps_cap, max(p.reader.health().fps, 0.0) or fps_cap)
        st.demand_fps = demand
        return st

    # ----------------------------------------------------------------- housekeeping
    def _housekeeping(self) -> None:
        while not self._stop.wait(0.5):
            try:
                alarmed = {sid for sid, snap in self.snapshots().items() if snap.siren and snap.running}
                self.siren.update(alarmed)
                if self.settings.version != self._seen_version:
                    self._seen_version = self.settings.version
                    with self._lock:
                        mons = list(self._monitors.values())
                    for m in mons:
                        m.apply_settings()
                if time.monotonic() - self._last_maintenance > 6 * 3600 or self._last_maintenance == 0:
                    self._last_maintenance = time.monotonic()
                    self.run_maintenance()
            except Exception:  # noqa: BLE001
                log.exception("Housekeeping error")

    def run_maintenance(self) -> None:
        """Delete old snapshots and events according to the retention settings."""
        s = self.settings.all()
        try:
            n = self.events.purge_older_than(int(s["event_retention_days"]))
            if n:
                log.info("Purged %d old events", n)
            cutoff = datetime.now() - timedelta(days=int(s["snapshot_retention_days"]))
            if self.snapshots_root.exists():
                for d in self.snapshots_root.iterdir():
                    try:
                        if d.is_dir() and datetime.strptime(d.name, "%Y-%m-%d") < cutoff:
                            shutil.rmtree(d, ignore_errors=True)
                    except ValueError:
                        continue
        except Exception:  # noqa: BLE001
            log.exception("Maintenance failed")
