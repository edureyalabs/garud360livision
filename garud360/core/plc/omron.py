# garud360/core/plc/omron.py
"""Omron driver: FINS over UDP (CJ/CP/CS/CK and NJ/NX with FINS enabled). Pure-Python, no dependencies.

Address formats (bit access):
    CIO100.00   core I/O area         W10.05  work area
    H5.01       holding area          A20.03  auxiliary area
    D100.07     data memory (bit 0-15 of word D100)
"""
from __future__ import annotations

import re
import socket
import threading

from garud360.core.plc.base import FieldDef, PlcConfig, PlcDriver, PlcError

# FINS memory area codes for BIT access
_AREAS = {"CIO": 0x30, "W": 0x31, "H": 0x32, "A": 0x33, "D": 0x02, "DM": 0x02}
_ADDR = re.compile(r"^(CIO|DM|D|W|H|A)\s*(\d{1,5})\.(\d{1,2})$", re.IGNORECASE)

_END_CODES = {0x0001: "Local node not in network", 0x0002: "Token timeout", 0x0003: "Retries failed",
              0x0101: "Local node error", 0x0102: "Destination node not in network",
              0x0105: "Node address setting error", 0x0202: "Unsupported command",
              0x1001: "Command too long", 0x1002: "Command too short", 0x1003: "Element count mismatch",
              0x1004: "Data length error", 0x1101: "Area classification missing",
              0x1103: "Address range error / bit number invalid", 0x110C: "Parameter error",
              0x2002: "Cannot write: PLC in RUN mode / protected", 0x2101: "Write not possible: read-only area",
              0x2103: "Write not possible: access right", 0x2201: "PLC mode does not allow this command",
              0x2302: "Write protected"}


def parse_address(address: str) -> tuple[int, int, int]:
    m = _ADDR.match(address.strip())
    if not m:
        raise PlcError(f"Invalid Omron address '{address}'. Use e.g. CIO100.00, W10.05, H5.01 or D100.07.")
    area = _AREAS[m.group(1).upper()]
    word, bit = int(m.group(2)), int(m.group(3))
    if bit > 15:
        raise PlcError("Bit number must be 0-15.")
    return area, word, bit


class OmronFinsDriver(PlcDriver):
    TYPE = "omron_fins"
    LABEL = "Omron (FINS / UDP)"
    DEFAULT_PORT = 9600
    ADDRESS_HELP = "Bit address: CIO100.00, W10.05, H5.01, A20.03 or D100.07 (bit of data-memory word)."
    EXAMPLE_PERMIT = "W10.00"
    EXTRA_FIELDS = (
        FieldDef("dest_node", "PLC FINS node (0 = last IP octet)", "int", 0,
                 "FINS node number of the PLC. 0 uses the last number of its IP address.", minimum=0, maximum=254),
        FieldDef("src_node", "PC FINS node (0 = last IP octet)", "int", 0,
                 "FINS node number of this PC. 0 uses the last number of this PC's IP address.", minimum=0,
                 maximum=254),
    )
    NOTES = "The PLC's Ethernet unit must allow FINS/UDP (port 9600). Write access needs a PLC mode that allows it."

    def __init__(self, cfg: PlcConfig, timeout_s: float = 3.0) -> None:
        super().__init__(cfg, timeout_s)
        self._sock: socket.socket | None = None
        self._sid = 0
        self._dest = 0
        self._src = 0
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
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.settimeout(self.timeout_s)
            s.connect((self.cfg.host, self.effective_port()))
            local_ip = s.getsockname()[0]
        except OSError as exc:
            raise PlcError(f"Cannot reach {self.cfg.host}:{self.effective_port()} - {exc}") from None
        self._dest = self.cfg.extra_int("dest_node", 0) or _last_octet(self.cfg.host)
        self._src = self.cfg.extra_int("src_node", 0) or _last_octet(local_ip)
        self._sock = s
        # prove the PLC is really answering (UDP "connect" proves nothing)
        try:
            self._request(0x05, 0x01, b"")        # controller data read: cheap and always allowed
        except PlcError:
            self.close()
            raise

    def close(self) -> None:
        s, self._sock = self._sock, None
        if s is not None:
            try:
                s.close()
            except OSError:
                pass

    def _request(self, mrc: int, src_code: int, data: bytes) -> bytes:
        if self._sock is None:
            raise PlcError("Not connected.")
        with self._lock:
            self._sid = (self._sid + 1) & 0xFF
            sid = self._sid
            header = bytes([0x80, 0x00, 0x02, 0x00, self._dest & 0xFF, 0x00, 0x00, self._src & 0xFF, 0x00, sid])
            frame = header + bytes([mrc, src_code]) + data
            last_exc: Exception | None = None
            for _attempt in range(2):                # UDP: one retry (all our commands are idempotent)
                try:
                    self._sock.send(frame)
                    while True:
                        resp = self._sock.recv(2048)
                        if len(resp) >= 14 and resp[9] == sid:
                            break
                    break
                except (socket.timeout, TimeoutError) as exc:
                    last_exc = exc
                except OSError as exc:
                    self.close()
                    raise PlcError(f"FINS communication error: {exc}") from None
            else:
                raise PlcError(f"PLC did not answer (timeout) - {last_exc}")
        if resp[10] != mrc or resp[11] != src_code:
            raise PlcError("Unexpected FINS response.")
        end = (resp[12] << 8) | resp[13]
        if end & 0x7FFF:
            raise PlcError(f"FINS error {end:#06x}: {_END_CODES.get(end, 'see Omron FINS manual')}")
        return resp[14:]

    def write_bool(self, address: str, value: bool) -> None:
        area, word, bit = parse_address(address)
        payload = bytes([area, (word >> 8) & 0xFF, word & 0xFF, bit, 0x00, 0x01, 0x01 if value else 0x00])
        self._request(0x01, 0x02, payload)

    def read_bool(self, address: str) -> bool:
        area, word, bit = parse_address(address)
        data = self._request(0x01, 0x01, bytes([area, (word >> 8) & 0xFF, word & 0xFF, bit, 0x00, 0x01]))
        if not data:
            raise PlcError("Empty FINS read response.")
        return bool(data[0] & 0x01)


def _last_octet(ip: str) -> int:
    try:
        return int(ip.strip().split(".")[-1]) & 0xFF
    except ValueError:
        return 0
