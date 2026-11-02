# garud360/core/plc/siemens.py
"""Siemens S7 driver (S7-1200 / S7-1500 / S7-300 / S7-400) using python-snap7 (S7 protocol, ISO-on-TCP port 102).

Address formats:
    DB10.DBX0.0    bit 0 of byte 0 in data block 10
    M10.2          merker bit
    Q0.1           process-image output bit (write/read)
    I0.0           process-image input bit (read only)

Bits are written with a true single-bit S7 write, so neighbouring bits in the same byte are never touched.

PLC preparation for S7-1200/1500 (TIA Portal):
    * CPU properties > Protection & Security > Connection mechanisms: tick "Permit access with PUT/GET ...".
    * The data block must have "Optimized block access" switched OFF.
"""
from __future__ import annotations

import re
import threading
from typing import Any

from garud360.core.plc.base import FieldDef, PlcConfig, PlcDriver, PlcError

_DB = re.compile(r"^DB\s*(\d{1,5})\s*\.\s*DBX\s*(\d{1,6})\s*\.\s*([0-7])$", re.IGNORECASE)
_MQ = re.compile(r"^([MQI])\s*(\d{1,6})\s*\.\s*([0-7])$", re.IGNORECASE)


def parse_address(address: str) -> tuple[str, int, int, int]:
    """Return (area, db_number, byte, bit) with area in {'DB','M','Q','I'}."""
    a = address.strip()
    m = _DB.match(a)
    if m:
        return "DB", int(m.group(1)), int(m.group(2)), int(m.group(3))
    m = _MQ.match(a)
    if m:
        return m.group(1).upper(), 0, int(m.group(2)), int(m.group(3))
    raise PlcError(f"Invalid Siemens address '{address}'. Use DB10.DBX0.0, M10.2, Q0.1 or I0.0.")


class SiemensS7Driver(PlcDriver):
    TYPE = "siemens_s7"
    LABEL = "Siemens S7 (S7-1200 / 1500 / 300)"
    DEFAULT_PORT = 102
    ADDRESS_HELP = "DB10.DBX0.0 (data block bit), M10.2 (merker), Q0.1 (output), I0.0 (input, read only)."
    EXAMPLE_PERMIT = "DB10.DBX0.0"
    EXTRA_FIELDS = (
        FieldDef("rack", "Rack", "int", 0, "0 for S7-1200/1500.", minimum=0, maximum=7),
        FieldDef("slot", "Slot", "int", 1, "1 for S7-1200/1500, 2 for S7-300.", minimum=0, maximum=31),
    )
    NOTES = ("Enable 'Permit access with PUT/GET' in the CPU and turn OFF 'Optimized block access' "
             "for the data block (TIA Portal).")

    def __init__(self, cfg: PlcConfig, timeout_s: float = 3.0) -> None:
        super().__init__(cfg, timeout_s)
        self._client: Any = None
        self._lock = threading.Lock()

    @classmethod
    def validate_address(cls, address: str) -> str | None:
        try:
            parse_address(address)
        except PlcError as exc:
            return str(exc)
        return None

    @property
    def connected(self) -> bool:
        c = self._client
        try:
            return c is not None and bool(c.get_connected())
        except Exception:  # noqa: BLE001
            return False

    def connect(self) -> None:
        self.close()
        try:
            import snap7
            from snap7.type import Parameter
        except ImportError as exc:  # pragma: no cover
            raise PlcError("The 'python-snap7' package is not installed.") from exc
        client = snap7.Client()
        try:
            for p in ("RecvTimeout", "SendTimeout", "PingTimeout"):
                try:
                    client.set_param(getattr(Parameter, p), int(self.timeout_s * 1000))
                except Exception:  # noqa: BLE001 - optional tuning
                    pass
            client.connect(self.cfg.host, self.cfg.extra_int("rack", 0), self.cfg.extra_int("slot", 1),
                           self.effective_port())
        except Exception as exc:  # noqa: BLE001
            try:
                client.disconnect()
            except Exception:  # noqa: BLE001
                pass
            raise PlcError(f"Cannot connect to Siemens PLC {self.cfg.host}: {exc}") from None
        self._client = client

    def close(self) -> None:
        c, self._client = self._client, None
        if c is not None:
            try:
                c.disconnect()
            except Exception:  # noqa: BLE001
                pass

    def _area(self, area: str) -> Any:
        from snap7.type import Area
        return {"DB": Area.DB, "M": Area.MK, "Q": Area.PA, "I": Area.PE}[area]

    def write_bool(self, address: str, value: bool) -> None:
        area, db, byte, bit = parse_address(address)
        if area == "I":
            raise PlcError("Inputs (I) are read-only.")
        if self._client is None:
            raise PlcError("Not connected.")
        from snap7.type import WordLen
        with self._lock:
            try:
                self._client.write_area(self._area(area), db, byte * 8 + bit,
                                        bytearray([1 if value else 0]), WordLen.Bit)
            except Exception as exc:  # noqa: BLE001
                self.close()
                raise PlcError(f"S7 write failed: {exc}") from None

    def read_bool(self, address: str) -> bool:
        area, db, byte, bit = parse_address(address)
        if self._client is None:
            raise PlcError("Not connected.")
        from snap7.type import WordLen
        with self._lock:
            try:
                data = self._client.read_area(self._area(area), db, byte * 8 + bit, 1, WordLen.Bit)
            except Exception as exc:  # noqa: BLE001
                self.close()
                raise PlcError(f"S7 read failed: {exc}") from None
        return bool(data[0] & 0x01)
