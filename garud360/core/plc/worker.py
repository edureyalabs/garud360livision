# garud360/core/plc/worker.py
"""Owns one PLC connection: reconnects, writes the crane output, heartbeat, and polls optional inputs."""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable

from garud360.core.plc.base import PlcConfig, PlcDriver, PlcError

log = logging.getLogger(__name__)


@dataclass
class PlcStatus:
    connected: bool = False
    error: str = ""
    confirmed_permit: bool | None = None     # last value written (and verified) to the PLC
    load_present: bool | None = None
    last_ok_t: float = 0.0


class PlcWorker:
    def __init__(self, driver: PlcDriver, cfg: PlcConfig, settings: Callable[[], dict[str, Any]],
                 on_link: Callable[[bool, str], None],
                 on_reset: Callable[[], None], on_pause: Callable[[], None]) -> None:
        self.driver, self.cfg, self._settings = driver, cfg, settings
        self._on_link, self._on_reset, self._on_pause = on_link, on_reset, on_pause
        self._lock = threading.Lock()
        self._desired: bool | None = None
        self._status = PlcStatus()
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="plc-worker", daemon=True)
        self._link_reported: bool | None = None

    # -- public ------------------------------------------------------------------
    def start(self) -> None:
        self._thread.start()

    def set_permit(self, permit: bool) -> None:
        with self._lock:
            if self._desired == permit:
                return
            self._desired = permit
        self._wake.set()

    def status(self) -> PlcStatus:
        with self._lock:
            s = self._status
            return PlcStatus(s.connected, s.error, s.confirmed_permit, s.load_present, s.last_ok_t)

    def shutdown(self, final_permit: bool | None, wait_s: float = 3.0) -> None:
        """Write the final crane state (best effort), then stop."""
        if final_permit is not None and self.status().connected:
            self.set_permit(final_permit)
            end = time.monotonic() + wait_s
            while time.monotonic() < end and self.status().confirmed_permit != final_permit:
                time.sleep(0.02)
        self._stop.set()
        self._wake.set()
        self._thread.join(timeout=3.0)
        self.driver.close()
        dispose = getattr(self.driver, "dispose", None)
        if dispose:
            dispose()

    # -- internals ---------------------------------------------------------------
    def _set_link(self, connected: bool, error: str = "") -> None:
        with self._lock:
            changed = self._status.connected != connected or self._status.error != error
            self._status.connected = connected
            self._status.error = error
            if not connected:
                self._status.confirmed_permit = None
        if self._link_reported != connected:
            self._link_reported = connected
            try:
                self._on_link(connected, error)
            except Exception:  # noqa: BLE001
                log.exception("PLC link callback failed")
        _ = changed

    def _run(self) -> None:
        hb_state = False
        last_written: bool | None = None
        next_refresh = 0.0
        next_poll = 0.0
        next_connect = 0.0
        prev_reset = False
        prev_pause = False
        while not self._stop.is_set():
            now = time.monotonic()
            s = self._settings()
            if not self.driver.connected:
                if now >= next_connect:
                    try:
                        self.driver.connect()
                        last_written = None
                        next_refresh = 0.0
                        self._set_link(True)
                        log.info("PLC connected (%s %s)", self.cfg.type, self.cfg.host)
                    except PlcError as exc:
                        self._set_link(False, str(exc))
                        next_connect = time.monotonic() + float(s["plc_reconnect_s"])
                self._wake.wait(0.2)
                self._wake.clear()
                continue
            try:
                with self._lock:
                    desired = self._desired
                if desired is not None and (desired != last_written or now >= next_refresh):
                    bit = self.cfg.bit_for_permit(desired)
                    self.driver.write_bool(self.cfg.permit_address, bit)
                    if bool(s["plc_verify_writes"]):
                        back = self.driver.read_bool(self.cfg.permit_address)
                        if back != bit:
                            raise PlcError(f"Write verification failed: wrote {int(bit)} to "
                                           f"'{self.cfg.permit_address}' but read back {int(back)}.")
                    if self.cfg.status_address:
                        self.driver.write_bool(self.cfg.status_address, not desired)
                    if self.cfg.heartbeat_address:
                        hb_state = not hb_state
                        self.driver.write_bool(self.cfg.heartbeat_address, hb_state)
                    last_written = desired
                    next_refresh = time.monotonic() + float(s["plc_heartbeat_s"])
                    with self._lock:
                        self._status.confirmed_permit = desired
                        self._status.last_ok_t = time.monotonic()
                        self._status.error = ""
                if now >= next_poll:
                    next_poll = time.monotonic() + float(s["plc_input_poll_s"])
                    if self.cfg.load_present_address:
                        lp = self.driver.read_bool(self.cfg.load_present_address)
                        with self._lock:
                            self._status.load_present = lp
                    if self.cfg.reset_address:
                        cur = self.driver.read_bool(self.cfg.reset_address)
                        if cur and not prev_reset:
                            self._on_reset()
                        prev_reset = cur
                    if self.cfg.pause_address:
                        cur = self.driver.read_bool(self.cfg.pause_address)
                        if cur and not prev_pause:
                            self._on_pause()
                        prev_pause = cur
            except PlcError as exc:
                log.warning("PLC error: %s", exc)
                self.driver.close()
                self._set_link(False, str(exc))
                next_connect = time.monotonic() + float(s["plc_reconnect_s"])
                continue
            except Exception as exc:  # noqa: BLE001 - never let a driver bug kill the worker
                log.exception("Unexpected PLC driver error")
                self.driver.close()
                self._set_link(False, f"{type(exc).__name__}: {exc}")
                next_connect = time.monotonic() + float(s["plc_reconnect_s"])
                continue
            timeout = max(0.005, min(next_refresh, next_poll) - time.monotonic())
            self._wake.wait(min(timeout, 0.25))
            self._wake.clear()
