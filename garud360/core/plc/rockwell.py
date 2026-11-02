# garud360/core/plc/rockwell.py
"""Rockwell / Allen-Bradley driver (ControlLogix, CompactLogix) over EtherNet/IP using pycomm3.

Addresses are symbolic controller tags (BOOL):
    Crane_Permit            controller-scoped BOOL tag
    Crane.Permit            BOOL member of a UDT
    MyProgram:Perm_Bit      program-scoped tag (use Program:Name.Tag)
    DINT_Tag.5              bit 5 of a DINT tag
Tags must be created in Studio 5000 first (External Access: Read/Write).
"""
from __future__ import annotations

import re
import threading
from typing import Any

from garud360.core.plc.base import FieldDef, PlcConfig, PlcDriver, PlcError

_TAG = re.compile(r"^[A-Za-z_][A-Za-z0-9_:\.\[\]]{0,200}$")


class RockwellCipDriver(PlcDriver):
    TYPE = "rockwell_cip"
    LABEL = "Rockwell / Allen-Bradley (EtherNet/IP)"
    DEFAULT_PORT = 44818
    ADDRESS_HELP = "Tag name of a BOOL, e.g. Crane_Permit, Crane.Permit or Program:Main.Permit. Bit of a DINT: Tag.5"
    EXAMPLE_PERMIT = "Crane_Permit"
    EXTRA_FIELDS = (FieldDef("slot", "CPU slot", "int", 0, "Slot of the controller in the chassis (0 for CompactLogix).",
                             minimum=0, maximum=16),)
    NOTES = "Create the tags as BOOL with External Access = Read/Write. Not for MicroLogix/SLC (use Modbus or CIP-PCCC)."

    def __init__(self, cfg: PlcConfig, timeout_s: float = 3.0) -> None:
        super().__init__(cfg, timeout_s)
        self._plc: Any = None
        self._lock = threading.Lock()

    @classmethod
    def validate_address(cls, address: str) -> str | None:
        return None if _TAG.match(address.strip()) else \
            "Use a tag name such as Crane_Permit (letters, digits, '_', '.', ':')."

    @property
    def connected(self) -> bool:
        p = self._plc
        try:
            return p is not None and bool(p.connected)
        except Exception:  # noqa: BLE001
            return False

    def connect(self) -> None:
        self.close()
        try:
            from pycomm3 import LogixDriver
        except ImportError as exc:  # pragma: no cover
            raise PlcError("The 'pycomm3' package is not installed.") from exc
        slot = self.cfg.extra_int("slot", 0)
        path = f"{self.cfg.host}/{slot}" if slot else self.cfg.host
        plc = LogixDriver(path, init_tags=True, init_program_tags=False, socket_timeout=self.timeout_s)
        try:
            if not plc.open():
                raise PlcError(f"Could not open EtherNet/IP session to {self.cfg.host}.")
        except PlcError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise PlcError(f"Cannot connect to Rockwell PLC {self.cfg.host}: {exc}") from None
        self._plc = plc

    def close(self) -> None:
        p, self._plc = self._plc, None
        if p is not None:
            try:
                p.close()
            except Exception:  # noqa: BLE001
                pass

    def write_bool(self, address: str, value: bool) -> None:
        if self._plc is None:
            raise PlcError("Not connected.")
        with self._lock:
            try:
                res = self._plc.write((address.strip(), bool(value)))
            except Exception as exc:  # noqa: BLE001
                self.close()
                raise PlcError(f"CIP write failed: {exc}") from None
        if getattr(res, "error", None):
            raise PlcError(f"CIP write error for '{address}': {res.error}")

    def read_bool(self, address: str) -> bool:
        if self._plc is None:
            raise PlcError("Not connected.")
        with self._lock:
            try:
                res = self._plc.read(address.strip())
            except Exception as exc:  # noqa: BLE001
                self.close()
                raise PlcError(f"CIP read failed: {exc}") from None
        if getattr(res, "error", None):
            raise PlcError(f"CIP read error for '{address}': {res.error}")
        return bool(res.value)
