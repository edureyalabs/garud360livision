# garud360/core/plc/simulated.py
"""Built-in PLC channel: a simulated crane. Behaves like a real PLC, including a heartbeat watchdog."""
from __future__ import annotations

import threading
import time

from garud360.core.plc.base import FieldDef, PlcConfig, PlcDriver, PlcError
from garud360.core.sim.crane import CraneModel, CraneSnapshot

SIM_WATCHDOG_S = 5.0


class SimulatedPlcDriver(PlcDriver):
    TYPE = "simulated"
    LABEL = "Simulated crane (built-in)"
    NEEDS_HOST = False
    ADDRESS_HELP = "Addresses are free text. Defaults: SIM_PERMIT, SIM_HB, SIM_LOAD."
    EXAMPLE_PERMIT = "SIM_PERMIT"
    EXTRA_FIELDS = (FieldDef("load_gating", "Monitor only while the crane carries a load", "bool", False,
                             "Demonstrates the client's 'AI disabled when no suspended load' behaviour."),)
    NOTES = "Runs entirely inside the app - ideal for testing cameras and settings without a real PLC."

    @classmethod
    def validate_config(cls, cfg: PlcConfig) -> list[str]:
        return []

    def __init__(self, cfg: PlcConfig, timeout_s: float = 3.0) -> None:
        super().__init__(cfg, timeout_s)
        self.model = CraneModel()
        self._bits: dict[str, bool] = {}
        self._connected = False
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._hb_last_change = time.monotonic()
        self._hb_value: bool | None = None

    # -- driver contract --------------------------------------------------------
    @property
    def connected(self) -> bool:
        return self._connected

    def connect(self) -> None:
        self._connected = True
        self._hb_last_change = time.monotonic()
        if self._thread is None or not self._thread.is_alive():
            self._stop.clear()
            self._thread = threading.Thread(target=self._run, name="sim-crane", daemon=True)
            self._thread.start()

    def close(self) -> None:
        self._connected = False

    def dispose(self) -> None:
        self._connected = False
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=1.0)

    def write_bool(self, address: str, value: bool) -> None:
        if not self._connected:
            raise PlcError("Not connected.")
        with self._lock:
            if address == self.cfg.heartbeat_address and self._hb_value != value:
                self._hb_value = value
                self._hb_last_change = time.monotonic()
            self._bits[address] = bool(value)

    def read_bool(self, address: str) -> bool:
        if not self._connected:
            raise PlcError("Not connected.")
        with self._lock:
            if address == self.cfg.load_present_address and address:
                return self.model.load_present
            return self._bits.get(address, False)

    # -- simulation thread ------------------------------------------------------
    def _permit_now(self) -> bool:
        bit = self._bits.get(self.cfg.permit_address)
        if bit is None:
            return False                       # nothing written yet: stay blocked
        return bit if self.cfg.bit_for_permit(True) else (not bit)

    def _run(self) -> None:
        last = time.monotonic()
        while not self._stop.wait(1 / 40):
            now = time.monotonic()
            with self._lock:
                watchdog_ok = True
                if self.cfg.heartbeat_address and self._hb_value is not None:
                    watchdog_ok = (now - self._hb_last_change) < SIM_WATCHDOG_S
                self.model.set_permit(self._permit_now(), watchdog_ok)
                self.model.step(now - last)
            last = now

    def snapshot(self) -> CraneSnapshot:
        with self._lock:
            return self.model.snapshot()
