# garud360/core/plc/modbus.py
"""Modbus TCP driver (Schneider Electric M221/M241/M251/M340/M580 and any Modbus TCP device).

Implemented directly on sockets (function codes 01, 02, 03, 05, 06) - no third-party dependency.

Address formats (protocol / 0-based addresses, exactly as in the Modbus frame):
    C10  or  10     coil 10           (read/write)
    DI5             discrete input 5  (read only)
    HR20.3          bit 3 of holding register 20 (read-modify-write)
"""
from __future__ import annotations

import re
import socket
import struct
import threading

from garud360.core.plc.base import FieldDef, PlcConfig, PlcDriver, PlcError

_ADDR = re.compile(r"^(?:(C|DI|HR)\s*)?(\d{1,5})(?:\.(\d{1,2}))?$", re.IGNORECASE)


def parse_address(address: str) -> tuple[str, int, int | None]:
    m = _ADDR.match(address.strip())
    if not m:
        raise PlcError(f"Invalid Modbus address '{address}'. Use C10, DI5 or HR20.3.")
    kind = (m.group(1) or "C").upper()
    num = int(m.group(2))
    bit = int(m.group(3)) if m.group(3) is not None else None
    if num > 65535:
        raise PlcError("Modbus address must be 0-65535.")
    if kind == "HR":
        if bit is None or not 0 <= bit <= 15:
            raise PlcError("Holding-register bits need a bit number 0-15, e.g. HR20.3")
    elif bit is not None:
        raise PlcError(f"'{address}': only holding registers take a .bit suffix.")
    return kind, num, bit


class ModbusTcpDriver(PlcDriver):
    TYPE = "modbus_tcp"
    LABEL = "Schneider Electric / Modbus TCP"
    DEFAULT_PORT = 502
    ADDRESS_HELP = "Coil: C10 (or just 10). Discrete input: DI5. Bit in a holding register: HR20.3. Addresses are 0-based."
    EXAMPLE_PERMIT = "C100"
    EXTRA_FIELDS = (FieldDef("unit_id", "Unit / slave ID", "int", 1, "Usually 1 (or 255 for some gateways).", minimum=0,
                             maximum=255),)
    NOTES = ("Schneider M221/M241/M251: %M0 is coil 0, %MW0 is holding register 0. "
             "M340/M580: enable the Modbus server and map the bit to a %M address.")

    def __init__(self, cfg: PlcConfig, timeout_s: float = 3.0) -> None:
        super().__init__(cfg, timeout_s)
        self._sock: socket.socket | None = None
        self._tid = 0
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
        return self._sock is not None

    def connect(self) -> None:
        self.close()
        try:
            s = socket.create_connection((self.cfg.host, self.effective_port()), timeout=self.timeout_s)
            s.settimeout(self.timeout_s)
            s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        except OSError as exc:
            raise PlcError(f"Cannot connect to {self.cfg.host}:{self.effective_port()} - {exc}") from None
        self._sock = s

    def close(self) -> None:
        s, self._sock = self._sock, None
        if s is not None:
            try:
                s.close()
            except OSError:
                pass

    # -- protocol -------------------------------------------------------------
    def _recv_exact(self, n: int) -> bytes:
        assert self._sock is not None
        buf = b""
        while len(buf) < n:
            chunk = self._sock.recv(n - len(buf))
            if not chunk:
                raise PlcError("Connection closed by PLC.")
            buf += chunk
        return buf

    def _transact(self, pdu: bytes) -> bytes:
        if self._sock is None:
            raise PlcError("Not connected.")
        unit = self.cfg.extra_int("unit_id", 1) & 0xFF
        with self._lock:
            self._tid = (self._tid + 1) & 0xFFFF
            tid = self._tid
            frame = struct.pack(">HHHB", tid, 0, len(pdu) + 1, unit) + pdu
            try:
                self._sock.sendall(frame)
                while True:   # skip stale responses from earlier timed-out requests
                    hdr = self._recv_exact(7)
                    rtid, proto, length, _unit = struct.unpack(">HHHB", hdr)
                    body = self._recv_exact(length - 1) if length > 1 else b""
                    if rtid == tid and proto == 0:
                        break
            except (OSError, PlcError) as exc:
                self.close()
                raise PlcError(f"Modbus communication error: {exc}") from None
        if not body:
            raise PlcError("Empty Modbus response.")
        if body[0] & 0x80:
            code = body[1] if len(body) > 1 else 0
            raise PlcError(f"Modbus exception {code:#04x} ({_EXC.get(code, 'unknown')}).")
        if body[0] != pdu[0]:
            raise PlcError("Unexpected Modbus function code in response.")
        return body

    def write_bool(self, address: str, value: bool) -> None:
        kind, num, bit = parse_address(address)
        if kind == "C":
            self._transact(struct.pack(">BHH", 0x05, num, 0xFF00 if value else 0x0000))
        elif kind == "HR":
            body = self._transact(struct.pack(">BHH", 0x03, num, 1))
            reg = struct.unpack(">H", body[2:4])[0]
            reg = (reg | (1 << bit)) if value else (reg & ~(1 << bit))  # type: ignore[operator]
            self._transact(struct.pack(">BHH", 0x06, num, reg & 0xFFFF))
        else:
            raise PlcError("Discrete inputs are read-only.")

    def read_bool(self, address: str) -> bool:
        kind, num, bit = parse_address(address)
        if kind in ("C", "DI"):
            body = self._transact(struct.pack(">BHH", 0x01 if kind == "C" else 0x02, num, 1))
            if len(body) < 3:
                raise PlcError("Short Modbus response.")
            return bool(body[2] & 0x01)
        body = self._transact(struct.pack(">BHH", 0x03, num, 1))
        reg = struct.unpack(">H", body[2:4])[0]
        return bool((reg >> bit) & 1)  # type: ignore[operator]


_EXC = {1: "illegal function", 2: "illegal data address", 3: "illegal data value", 4: "device failure",
        6: "device busy", 10: "gateway path unavailable", 11: "gateway target failed to respond"}
