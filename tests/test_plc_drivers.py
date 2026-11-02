# tests/test_plc_drivers.py
"""Protocol-level tests: each driver talks to a local fake/emulated PLC server over a real socket."""
from __future__ import annotations

import socket
import socketserver
import struct
import threading
import time

import pytest

from garud360.core.plc.base import PlcConfig, PlcError
from garud360.core.plc.modbus import ModbusTcpDriver
from garud360.core.plc.omron import OmronFinsDriver
from garud360.core.plc.registry import DRIVERS, check_connection, create_driver, validate
from tests.conftest import eventually


def free_port(kind=socket.SOCK_STREAM) -> int:
    with socket.socket(socket.AF_INET, kind) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# ----------------------------------------------------------------------------- Modbus
class _ModbusHandler(socketserver.BaseRequestHandler):
    def handle(self):
        srv = self.server
        while True:
            try:
                hdr = self.request.recv(7)
                if len(hdr) < 7:
                    return
                tid, _, length, unit = struct.unpack(">HHHB", hdr)
                pdu = self.request.recv(length - 1)
                fc = pdu[0]
                if getattr(srv, "drop_next", False):
                    srv.drop_next = False
                    continue
                if fc in (1, 2):
                    addr, _n = struct.unpack(">HH", pdu[1:5])
                    store = srv.coils if fc == 1 else srv.inputs
                    out = bytes([fc, 1, 1 if store.get(addr) else 0])
                elif fc == 5:
                    addr, val = struct.unpack(">HH", pdu[1:5])
                    if addr == 9999:
                        out = bytes([0x85, 2])
                    else:
                        srv.coils[addr] = val == 0xFF00
                        out = pdu
                elif fc == 3:
                    addr, _n = struct.unpack(">HH", pdu[1:5])
                    out = bytes([3, 2]) + struct.pack(">H", srv.regs.get(addr, 0))
                elif fc == 6:
                    addr, val = struct.unpack(">HH", pdu[1:5])
                    srv.regs[addr] = val
                    out = pdu
                else:
                    out = bytes([fc | 0x80, 1])
                srv.units.append(unit)
                self.request.sendall(struct.pack(">HHHB", tid, 0, len(out) + 1, unit) + out)
            except OSError:
                return


@pytest.fixture()
def modbus_server():
    srv = socketserver.ThreadingTCPServer(("127.0.0.1", 0), _ModbusHandler)
    srv.daemon_threads = True
    srv.coils, srv.inputs, srv.regs, srv.units = {}, {7: True}, {20: 0b0100}, []
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv
    srv.shutdown()
    srv.server_close()


def _cfg(type_, port, **kw):
    return PlcConfig.from_dict({"type": type_, "host": "127.0.0.1", "port": port, **kw})


def test_modbus_coil_register_bit_and_errors(modbus_server):
    cfg = _cfg("modbus_tcp", modbus_server.server_address[1], permit_address="C100", extras={"unit_id": 7})
    d = ModbusTcpDriver(cfg, 2.0)
    d.connect()
    d.write_bool("C100", True)
    assert modbus_server.coils[100] is True and d.read_bool("100") is True
    d.write_bool("100", False)
    assert modbus_server.coils[100] is False
    assert d.read_bool("DI7") is True and d.read_bool("DI8") is False
    assert d.read_bool("HR20.2") is True and d.read_bool("HR20.0") is False
    d.write_bool("HR20.0", True)
    assert modbus_server.regs[20] == 0b0101                     # other bits preserved
    d.write_bool("HR20.2", False)
    assert modbus_server.regs[20] == 0b0001
    assert set(modbus_server.units) == {7}
    with pytest.raises(PlcError, match="exception"):
        d.write_bool("C9999", True)
    with pytest.raises(PlcError, match="read-only"):
        d.write_bool("DI7", True)
    for bad in ("X1", "HR5", "C1.2", "70000"):
        assert ModbusTcpDriver.validate_address(bad), bad
    d.close()
    assert not d.connected
    with pytest.raises(PlcError):
        d.read_bool("C1")


def test_modbus_timeout_marks_disconnected(modbus_server):
    d = ModbusTcpDriver(_cfg("modbus_tcp", modbus_server.server_address[1], permit_address="C1"), 0.4)
    d.connect()
    modbus_server.drop_next = True
    with pytest.raises(PlcError):
        d.read_bool("C1")
    assert not d.connected


def test_connect_refused_is_a_clean_error():
    d = ModbusTcpDriver(_cfg("modbus_tcp", free_port(), permit_address="C1"), 0.5)
    with pytest.raises(PlcError, match="Cannot connect"):
        d.connect()


# ------------------------------------------------------------------------------ FINS
class _FinsServer(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True)
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.settimeout(0.2)
        self.port = self.sock.getsockname()[1]
        self.bits: dict[tuple[int, int, int], int] = {}
        self.stop_flag = False
        self.seen_nodes: list[tuple[int, int]] = []
        self.end_code = 0
        self.ignore = 0
        self.start()

    def run(self):
        while not self.stop_flag:
            try:
                data, addr = self.sock.recvfrom(2048)
            except socket.timeout:
                continue
            if self.ignore:
                self.ignore -= 1
                continue
            sid = data[9]
            self.seen_nodes.append((data[4], data[7]))
            mrc, src = data[10], data[11]
            payload = b""
            if (mrc, src) == (0x01, 0x02):
                area, word, bit = data[12], (data[13] << 8) | data[14], data[15]
                self.bits[(area, word, bit)] = data[18]
            elif (mrc, src) == (0x01, 0x01):
                area, word, bit = data[12], (data[13] << 8) | data[14], data[15]
                payload = bytes([self.bits.get((area, word, bit), 0)])
            elif (mrc, src) == (0x05, 0x01):
                payload = b"CJ2M" + bytes(20)
            hdr = bytes([0xC0, 0, 2, 0, data[7], 0, 0, data[4], 0, sid])
            self.sock.sendto(hdr + bytes([mrc, src]) + struct.pack(">H", self.end_code) + payload, addr)

    def close(self):
        self.stop_flag = True
        self.join(1)
        self.sock.close()


def test_omron_fins_write_read_and_errors():
    srv = _FinsServer()
    try:
        cfg = _cfg("omron_fins", srv.port, permit_address="W10.05", extras={"dest_node": 11, "src_node": 5})
        d = OmronFinsDriver(cfg, 0.5)
        d.connect()
        d.write_bool("W10.05", True)
        assert srv.bits[(0x31, 10, 5)] == 1 and d.read_bool("W10.05") is True
        d.write_bool("CIO100.00", True)
        assert srv.bits[(0x30, 100, 0)] == 1
        d.write_bool("D100.15", True)
        assert srv.bits[(0x02, 100, 15)] == 1
        d.write_bool("W10.05", False)
        assert d.read_bool("W10.05") is False
        assert (11, 5) in srv.seen_nodes
        srv.ignore = 1                          # first datagram lost -> retry succeeds
        assert d.read_bool("W10.05") is False
        srv.end_code = 0x2101
        with pytest.raises(PlcError, match="0x2101"):
            d.write_bool("W10.05", True)
        srv.end_code = 0
        srv.ignore = 10
        with pytest.raises(PlcError, match="did not answer"):
            d.read_bool("W10.05")
        for bad in ("W10", "W10.16", "Q1.0", "CIO.1"):
            assert OmronFinsDriver.validate_address(bad), bad
        d.close()
    finally:
        srv.close()


def test_omron_connect_fails_when_plc_silent():
    port = free_port(socket.SOCK_DGRAM)
    d = OmronFinsDriver(_cfg("omron_fins", port, permit_address="W1.00"), 0.3)
    with pytest.raises(PlcError):
        d.connect()
    assert not d.connected


# -------------------------------------------------------------------- Mitsubishi (3E)
class _McHandler(socketserver.BaseRequestHandler):
    def handle(self):
        srv = self.server
        while True:
            hdr = self.request.recv(9)
            if len(hdr) < 9:
                return
            length = struct.unpack("<H", hdr[7:9])[0]
            body = b""
            while len(body) < length:
                chunk = self.request.recv(length - len(body))
                if not chunk:
                    return
                body += chunk
            cmd, sub = struct.unpack("<HH", body[2:6])
            head = int.from_bytes(body[6:9], "little")
            code = body[9]
            points = struct.unpack("<H", body[10:12])[0]
            data = b""
            if cmd == 0x1401:                      # batch write, bit units
                raw = body[12:]
                vals = []
                for b in raw:
                    vals += [(b >> 4) & 1, b & 1]
                for i in range(points):
                    srv.bits[(code, head + i)] = vals[i]
            elif cmd == 0x0401:
                vals = [srv.bits.get((code, head + i), 0) for i in range(points)]
                if len(vals) % 2:
                    vals.append(0)
                data = bytes((vals[i] << 4) | vals[i + 1] for i in range(0, len(vals), 2))
            resp = b"\xD0\x00" + hdr[2:7] + struct.pack("<H", 2 + len(data)) + b"\x00\x00" + data
            self.request.sendall(resp)


def test_mitsubishi_mc_write_read_through_pymcprotocol():
    pytest.importorskip("pymcprotocol")
    from garud360.core.plc.mitsubishi import MitsubishiMcDriver
    srv = socketserver.ThreadingTCPServer(("127.0.0.1", 0), _McHandler)
    srv.daemon_threads = True
    srv.bits = {}
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        d = MitsubishiMcDriver(_cfg("mitsubishi_mc", srv.server_address[1], permit_address="M100"), 1.0)
        d.connect()
        d.write_bool("M100", True)
        assert srv.bits[(0x90, 100)] == 1                          # device code 0x90 = M
        assert d.read_bool("M100") is True and d.read_bool("M101") is False
        d.write_bool("Y10", True)
        assert srv.bits[(0x9D, 0x10)] == 1                         # Y addresses are hexadecimal
        d.write_bool("M100", False)
        assert d.read_bool("M100") is False
        d.close()
        assert not d.connected
        assert MitsubishiMcDriver.validate_address("M100") is None and MitsubishiMcDriver.validate_address("Z9")
    finally:
        srv.shutdown()
        srv.server_close()


# ---------------------------------------------------------------------------- Siemens
def test_siemens_s7_bit_access_via_snap7_server():
    pytest.importorskip("snap7")
    from snap7.server import Server
    from snap7.type import SrvArea
    from garud360.core.plc.siemens import SiemensS7Driver, parse_address
    port = free_port()
    db, mk, pa = bytearray(10), bytearray(16), bytearray(8)
    srv = Server()
    srv.register_area(SrvArea.DB, 10, db)
    srv.register_area(SrvArea.MK, 0, mk)
    srv.register_area(SrvArea.PA, 0, pa)
    srv.start(tcp_port=port)
    try:
        time.sleep(0.3)
        d = SiemensS7Driver(_cfg("siemens_s7", port, permit_address="DB10.DBX3.2", extras={"rack": 0, "slot": 1}), 2.0)
        d.connect()
        assert d.connected
        d.write_bool("DB10.DBX3.2", True)
        assert db[3] != 0 and d.read_bool("DB10.DBX3.2") is True
        d.write_bool("DB10.DBX3.2", False)
        assert db[3] == 0 and d.read_bool("DB10.DBX3.2") is False
        d.write_bool("M2.5", True)
        assert mk[2] != 0
        d.write_bool("Q0.1", True)
        assert pa[0] != 0
        with pytest.raises(PlcError, match="read-only"):
            d.write_bool("I0.0", True)
        d.close()
        assert not d.connected
    finally:
        srv.stop()
    assert parse_address("DB1.DBX0.7") == ("DB", 1, 0, 7)
    assert parse_address("m10.2") == ("M", 0, 10, 2)
    for bad in ("DB1.DBW0", "M1.8", "DB.DBX0.0", "X1.0"):
        assert SiemensS7Driver.validate_address(bad), bad


def test_siemens_unreachable_is_clean_error():
    pytest.importorskip("snap7")
    from garud360.core.plc.siemens import SiemensS7Driver
    d = SiemensS7Driver(_cfg("siemens_s7", free_port(), permit_address="M0.0"), 0.5)
    with pytest.raises(PlcError, match="Cannot connect"):
        d.connect()


# --------------------------------------------------------------------------- Rockwell
def test_rockwell_driver_with_injected_pycomm3(monkeypatch):
    pytest.importorskip("pycomm3")
    import pycomm3
    from garud360.core.plc.rockwell import RockwellCipDriver

    class Res:
        def __init__(self, value=None, error=None):
            self.value, self.error = value, error

    class FakeLogix:
        tags: dict = {}
        opened_with = None

        def __init__(self, path, **kw):
            FakeLogix.opened_with = (path, kw)
            self.connected = False

        def open(self):
            self.connected = True
            return True

        def close(self):
            self.connected = False

        def write(self, item):
            tag, val = item
            if tag == "Bad":
                return Res(error="tag does not exist")
            FakeLogix.tags[tag] = val
            return Res(val)

        def read(self, tag):
            return Res(FakeLogix.tags.get(tag, False))

    monkeypatch.setattr(pycomm3, "LogixDriver", FakeLogix)
    d = RockwellCipDriver(_cfg("rockwell_cip", 0, host="10.1.1.5", permit_address="Crane_Permit", extras={"slot": 2}), 2)
    d.connect()
    assert FakeLogix.opened_with[0] == "10.1.1.5/2" and d.connected
    d.write_bool("Crane_Permit", True)
    assert d.read_bool("Crane_Permit") is True
    with pytest.raises(PlcError, match="does not exist"):
        d.write_bool("Bad", True)
    d.close()
    assert not d.connected
    assert RockwellCipDriver.validate_address("Program:Main.Permit") is None
    assert RockwellCipDriver.validate_address("1bad") and RockwellCipDriver.validate_address("a b")


# ----------------------------------------------------------------------------- OPC UA
def test_opcua_roundtrip_against_asyncua_server():
    pytest.importorskip("asyncua")
    from asyncua.sync import Server
    from garud360.core.plc.opcua import OpcUaDriver
    port = free_port()
    server = Server()
    server.set_endpoint(f"opc.tcp://127.0.0.1:{port}")
    idx = server.register_namespace("garud")
    obj = server.nodes.objects.add_object(idx, "Crane")
    permit = obj.add_variable(idx, "Permit", False)
    permit.set_writable()
    server.start()
    try:
        nid = permit.nodeid.to_string()
        d = OpcUaDriver(_cfg("opcua", port, permit_address=nid), 3.0)
        d.connect()
        d.write_bool(nid, True)
        assert permit.read_value() is True and d.read_bool(nid) is True
        d.write_bool(nid, False)
        assert permit.read_value() is False
        d.close()
        assert not d.connected
    finally:
        server.stop()
    assert OpcUaDriver.validate_address("ns=2;s=Crane.Permit") is None and OpcUaDriver.validate_address("Crane")


# ---------------------------------------------------------------------------- registry
def test_registry_validation_and_connection_test(modbus_server):
    assert set(DRIVERS) == {"simulated", "siemens_s7", "rockwell_cip", "mitsubishi_mc", "omron_fins", "modbus_tcp",
                            "opcua"}
    assert validate({"type": "modbus_tcp", "host": "", "permit_address": "C1"})
    assert validate({"type": "modbus_tcp", "host": "bad host!", "permit_address": "C1"})
    assert validate({"type": "modbus_tcp", "host": "10.0.0.1", "permit_address": ""})
    assert validate({"type": "modbus_tcp", "host": "10.0.0.1", "permit_address": "ZZ"})
    assert validate({"type": "nope"})
    assert validate({"type": "simulated"}) == []
    ok, msg = check_connection({"type": "modbus_tcp", "host": "127.0.0.1", "port": modbus_server.server_address[1],
                               "permit_address": "C5"})
    assert ok and "reads 0" in msg
    assert modbus_server.coils == {}                       # the connection test never writes
    ok, msg = check_connection({"type": "modbus_tcp", "host": "127.0.0.1", "port": free_port(),
                               "permit_address": "C5"}, 0.5)
    assert not ok and "Cannot connect" in msg
    assert create_driver(PlcConfig(type="simulated")).LABEL.startswith("Simulated")
