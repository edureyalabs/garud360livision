# garud360/core/plc/mitsubishi.py
"""Mitsubishi MELSEC driver using the MC protocol (3E frame, binary) via pymcprotocol.

Works with iQ-R, iQ-F (FX5U/FX5UC), Q and L series CPUs / Ethernet modules.

Address formats (bit devices):
    M100    internal relay      Y10   output (hex)     X20  input (hex)
    L50     latch relay         B1F   link relay (hex)

PLC preparation (GX Works): open the Ethernet port for MC protocol - protocol TCP, binary code, port number
(for example 5000) - and enable "Write at RUN" so that bit devices can be written while the CPU runs.
"""
from __future__ import annotations

import re
import threading
from typing import Any

from garud360.core.plc.base import FieldDef, PlcConfig, PlcDriver, PlcError

_DEV = re.compile(r"^(M|L|X|Y|B|F|V|S|SM|SB|DX|DY|TS|TC|SS|SC|CS|CC)\s*([0-9A-Fa-f]{1,6})$", re.IGNORECASE)


class MitsubishiMcDriver(PlcDriver):
    TYPE = "mitsubishi_mc"
    LABEL = "Mitsubishi MELSEC (MC protocol)"
    DEFAULT_PORT = 5000
    ADDRESS_HELP = "Bit device: M100, L50, Y10, X20, B1F ... (X, Y, B are hexadecimal)."
    EXAMPLE_PERMIT = "M100"
    EXTRA_FIELDS = (FieldDef("series", "CPU series", "choice", "Q", "Select the family of your CPU.",
                             choices=("Q", "L", "QnA", "iQ-L", "iQ-R")),)
    NOTES = "Open the Ethernet port for MC protocol (TCP, binary) in GX Works and enable 'Write at RUN'."

    def __init__(self, cfg: PlcConfig, timeout_s: float = 3.0) -> None:
        super().__init__(cfg, timeout_s)
        self._c: Any = None
        self._lock = threading.Lock()

    @classmethod
    def validate_address(cls, address: str) -> str | None:
        return None if _DEV.match(address.strip()) else "Use a bit device such as M100, Y10 or X20."

    @property
    def connected(self) -> bool:
        return self._c is not None

    def connect(self) -> None:
        self.close()
        try:
            import pymcprotocol
        except ImportError as exc:  # pragma: no cover
            raise PlcError("The 'pymcprotocol' package is not installed.") from exc
        series = str(self.cfg.extras.get("series", "Q"))
        try:
            c = pymcprotocol.Type3E(plctype=series)
            c.setaccessopt(commtype="binary")
            c.soc_timeout = self.timeout_s
            c.connect(self.cfg.host, self.effective_port())
        except Exception as exc:  # noqa: BLE001
            raise PlcError(f"Cannot connect to Mitsubishi PLC {self.cfg.host}:{self.effective_port()}: {exc}") from None
        self._c = c

    def close(self) -> None:
        c, self._c = self._c, None
        if c is not None:
            try:
                c.close()
            except Exception:  # noqa: BLE001
                pass

    def write_bool(self, address: str, value: bool) -> None:
        if self._c is None:
            raise PlcError("Not connected.")
        with self._lock:
            try:
                self._c.batchwrite_bitunits(headdevice=address.strip().upper(), values=[1 if value else 0])
            except Exception as exc:  # noqa: BLE001
                self.close()
                raise PlcError(f"MC write failed: {exc}") from None

    def read_bool(self, address: str) -> bool:
        if self._c is None:
            raise PlcError("Not connected.")
        with self._lock:
            try:
                vals = self._c.batchread_bitunits(headdevice=address.strip().upper(), readsize=1)
            except Exception as exc:  # noqa: BLE001
                self.close()
                raise PlcError(f"MC read failed: {exc}") from None
        return bool(vals[0])
