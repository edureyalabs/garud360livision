# tests/test_plc_worker_and_sim.py
import time

from garud360.core.plc.base import PlcConfig, PlcDriver, PlcError
from garud360.core.plc.simulated import SimulatedPlcDriver
from garud360.core.plc.worker import PlcWorker
from garud360.core.sim.crane import CraneModel
from tests.conftest import eventually

SETTINGS = {"plc_heartbeat_s": 0.1, "plc_input_poll_s": 0.02, "plc_verify_writes": True, "plc_reconnect_s": 0.1}


class FlakyDriver(PlcDriver):
    TYPE = "flaky"

    def __init__(self, cfg):
        super().__init__(cfg)
        self.up = True
        self._conn = False
        self.bits = {}
        self.writes = []
        self.ignore_writes = False

    @property
    def connected(self):
        return self._conn

    def connect(self):
        if not self.up:
            raise PlcError("down")
        self._conn = True

    def close(self):
        self._conn = False

    def write_bool(self, address, value):
        if not self.up:
            self._conn = False
            raise PlcError("link lost")
        self.writes.append((address, value))
        if not self.ignore_writes:
            self.bits[address] = value

    def read_bool(self, address):
        if not self.up:
            self._conn = False
            raise PlcError("link lost")
        return self.bits.get(address, False)


def make_worker(driver, cfg, events):
    w = PlcWorker(driver, cfg, lambda: SETTINGS, lambda ok, err: events.append(("link", ok)),
                  lambda: events.append("reset"), lambda: events.append("pause"))
    w.start()
    return w


def test_worker_writes_polarity_heartbeat_and_reasserts():
    cfg = PlcConfig.from_dict({"type": "flaky", "permit_address": "P", "heartbeat_address": "HB", "status_address": "ST"})
    d, ev = FlakyDriver(cfg), []
    w = make_worker(d, cfg, ev)
    try:
        w.set_permit(False)
        eventually(lambda: d.bits.get("P") is False and w.status().confirmed_permit is False)
        assert d.bits["ST"] is True                       # status lamp: blocking
        w.set_permit(True)
        eventually(lambda: d.bits.get("P") is True)
        n = len(d.writes)
        eventually(lambda: len(d.writes) > n + 4, message="periodic refresh")
        assert {v for a, v in d.writes if a == "HB"} == {True, False}     # heartbeat toggles
    finally:
        w.shutdown(None)


def test_worker_block_high_polarity():
    cfg = PlcConfig.from_dict({"type": "flaky", "permit_address": "P", "polarity": "block_high"})
    d, ev = FlakyDriver(cfg), []
    w = make_worker(d, cfg, ev)
    try:
        w.set_permit(False)
        eventually(lambda: d.bits.get("P") is True)       # block = 1
        w.set_permit(True)
        eventually(lambda: d.bits.get("P") is False)
    finally:
        w.shutdown(None)


def test_worker_link_loss_reconnect_and_rewrite():
    cfg = PlcConfig.from_dict({"type": "flaky", "permit_address": "P"})
    d, ev = FlakyDriver(cfg), []
    w = make_worker(d, cfg, ev)
    try:
        w.set_permit(False)
        eventually(lambda: w.status().connected and d.bits.get("P") is False)
        d.up = False
        eventually(lambda: not w.status().connected, message="fault detected")
        assert ("link", False) in ev and w.status().error
        d.bits.clear()
        d.up = True
        eventually(lambda: w.status().connected and d.bits.get("P") is False, message="state re-asserted")
        assert ev.count(("link", True)) >= 2
    finally:
        w.shutdown(None)


def test_worker_detects_ignored_write_via_verify():
    cfg = PlcConfig.from_dict({"type": "flaky", "permit_address": "P"})
    d, ev = FlakyDriver(cfg), []
    d.ignore_writes = True
    w = make_worker(d, cfg, ev)
    try:
        w.set_permit(True)
        eventually(lambda: any("verification" in (w.status().error or "") for _ in [0]), message="verify error")
        assert not w.status().connected
    finally:
        w.shutdown(None)


def test_worker_inputs_load_reset_pause_edges():
    cfg = PlcConfig.from_dict({"type": "flaky", "permit_address": "P", "load_present_address": "L",
                               "reset_address": "R", "pause_address": "PA"})
    d, ev = FlakyDriver(cfg), []
    w = make_worker(d, cfg, ev)
    try:
        eventually(lambda: w.status().load_present is False)
        d.bits["L"] = True
        eventually(lambda: w.status().load_present is True)
        d.bits["R"] = True
        eventually(lambda: "reset" in ev)
        time.sleep(0.2)
        assert ev.count("reset") == 1                      # edge-triggered, not level
        d.bits["R"] = False
        d.bits["PA"] = True
        eventually(lambda: "pause" in ev)
    finally:
        w.shutdown(None)


def test_worker_shutdown_writes_final_state():
    cfg = PlcConfig.from_dict({"type": "flaky", "permit_address": "P"})
    d, ev = FlakyDriver(cfg), []
    w = make_worker(d, cfg, ev)
    w.set_permit(True)
    eventually(lambda: d.bits.get("P") is True)
    w.shutdown(False)
    assert d.bits["P"] is False and not d.connected


# ------------------------------------------------------------------------- simulated
def test_crane_model_moves_only_when_permitted_and_cycles():
    m = CraneModel()
    start = (m.x, m.z)
    for _ in range(100):
        m.step(0.05)
    assert (m.x, m.z) != start
    m.set_permit(False)
    for _ in range(40):
        m.step(0.05)
    frozen = (round(m.x, 4), round(m.z, 4))
    for _ in range(200):
        m.step(0.05)
    assert (round(m.x, 4), round(m.z, 4)) == frozen and not m.snapshot().moving
    m.set_permit(True)
    seen_load = False
    for _ in range(4000):
        m.step(0.05)
        seen_load |= m.load_present
    assert seen_load and m.cycles >= 1 and 0 <= m.x <= 1 and 0 <= m.z <= 1


def test_simulated_driver_watchdog_stops_crane_when_heartbeat_dies():
    cfg = PlcConfig.from_dict({"type": "simulated", "permit_address": "SIM_PERMIT", "heartbeat_address": "SIM_HB"})
    d = SimulatedPlcDriver(cfg)
    d.connect()
    try:
        d.write_bool("SIM_PERMIT", True)
        d.write_bool("SIM_HB", True)
        eventually(lambda: d.snapshot().moving, message="crane runs while permitted")
        import garud360.core.plc.simulated as sim
        sim.SIM_WATCHDOG_S = 0.3
        eventually(lambda: d.snapshot().watchdog_tripped, message="watchdog trips without heartbeat")
        eventually(lambda: not d.snapshot().moving)
    finally:
        d.dispose()
