# garud360/core/plc/base.py
"""PLC driver contract and the configuration model shared by all PLC families."""
from __future__ import annotations

import ipaddress
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

POLARITY_PERMIT_HIGH = "permit_high"   # bit = 1 while crane may move; 0 = holder knob released / blocked
POLARITY_BLOCK_HIGH = "block_high"     # bit = 1 commands a halt; 0 = crane may move


class PlcError(Exception):
    """Communication or configuration failure talking to a PLC."""


@dataclass
class FieldDef:
    """Describes one extra, driver-specific form field (used to build the UI)."""
    key: str
    label: str
    kind: str = "str"            # str | int | bool | choice
    default: Any = ""
    help: str = ""
    choices: tuple[str, ...] = ()
    minimum: int = 0
    maximum: int = 65535


@dataclass
class PlcConfig:
    type: str = "simulated"
    host: str = ""
    port: int = 0
    permit_address: str = ""
    polarity: str = POLARITY_PERMIT_HIGH
    heartbeat_address: str = ""
    status_address: str = ""           # optional: written 1 while the app is blocking (for lamp / horn)
    load_present_address: str = ""     # optional input: AI only active while a load is suspended
    reset_address: str = ""            # optional input: rising edge = manual reset (crane remote / tab)
    pause_address: str = ""            # optional input: rising edge = pause AI (attach/detach load)
    extras: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: dict[str, Any] | None) -> "PlcConfig":
        d = dict(d or {})
        known = {"type", "host", "port", "permit_address", "polarity", "heartbeat_address", "status_address",
                 "load_present_address", "reset_address", "pause_address"}
        kw = {k: d[k] for k in known if k in d}
        c = cls(**kw)
        c.extras = dict(d.get("extras") or {})
        try:
            c.port = int(c.port or 0)
        except (TypeError, ValueError):
            c.port = 0
        for k in ("host", "permit_address", "heartbeat_address", "status_address", "load_present_address",
                  "reset_address", "pause_address"):
            setattr(c, k, str(getattr(c, k) or "").strip())
        return c

    def to_dict(self) -> dict[str, Any]:
        return {"type": self.type, "host": self.host, "port": self.port, "permit_address": self.permit_address,
                "polarity": self.polarity, "heartbeat_address": self.heartbeat_address,
                "status_address": self.status_address, "load_present_address": self.load_present_address,
                "reset_address": self.reset_address, "pause_address": self.pause_address,
                "extras": dict(self.extras)}

    def bit_for_permit(self, permit: bool) -> bool:
        """Translate 'crane may move' to the value written to the output bit."""
        return permit if self.polarity == POLARITY_PERMIT_HIGH else (not permit)

    def extra_int(self, key: str, default: int) -> int:
        try:
            return int(self.extras.get(key, default))
        except (TypeError, ValueError):
            return default


_HOST_RE = re.compile(r"^[A-Za-z0-9]([A-Za-z0-9.\-]{0,251}[A-Za-z0-9])?$")


def valid_host(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return bool(_HOST_RE.match(host))


class PlcDriver(ABC):
    """One synchronous connection to a PLC. All calls are made from a single worker thread."""

    TYPE: str = ""
    LABEL: str = ""
    DEFAULT_PORT: int = 0
    NEEDS_HOST: bool = True
    ADDRESS_HELP: str = ""
    EXAMPLE_PERMIT: str = ""
    EXTRA_FIELDS: tuple[FieldDef, ...] = ()
    NOTES: str = ""

    def __init__(self, cfg: PlcConfig, timeout_s: float = 3.0) -> None:
        self.cfg = cfg
        self.timeout_s = timeout_s

    # connection
    @abstractmethod
    def connect(self) -> None: ...

    @abstractmethod
    def close(self) -> None: ...

    @property
    @abstractmethod
    def connected(self) -> bool: ...

    # I/O
    @abstractmethod
    def write_bool(self, address: str, value: bool) -> None: ...

    @abstractmethod
    def read_bool(self, address: str) -> bool: ...

    # validation
    @classmethod
    def validate_address(cls, address: str) -> str | None:
        """Return an error message if the address is malformed, else None. Override per driver."""
        return None

    @classmethod
    def validate_config(cls, cfg: PlcConfig) -> list[str]:
        errs: list[str] = []
        if cls.NEEDS_HOST and not valid_host(cfg.host):
            errs.append("Enter the PLC IP address or host name.")
        if cfg.port and not (1 <= cfg.port <= 65535):
            errs.append("Port must be between 1 and 65535.")
        if not cfg.permit_address:
            errs.append("The crane output address is required.")
        for label, addr in (("Crane output", cfg.permit_address), ("Heartbeat", cfg.heartbeat_address),
                            ("Status", cfg.status_address), ("Load present", cfg.load_present_address),
                            ("Reset", cfg.reset_address), ("Pause", cfg.pause_address)):
            if addr:
                msg = cls.validate_address(addr)
                if msg:
                    errs.append(f"{label} address: {msg}")
        if cfg.polarity not in (POLARITY_PERMIT_HIGH, POLARITY_BLOCK_HIGH):
            errs.append("Unknown output logic.")
        return errs

    def effective_port(self) -> int:
        return self.cfg.port or self.DEFAULT_PORT
