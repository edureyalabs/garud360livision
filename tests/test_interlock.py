# tests/test_interlock.py
from garud360.core.detection.debounce import Debouncer
from garud360.core.detection.roi import RoiMask
from garud360.core.space.interlock import Interlock, InterlockInputs, Status


def inp(**kw):
    base = dict(person_active=False, fault_active=False, starting=False)
    base.update(kw)
    return InterlockInputs(**base)


def test_clear_person_fault_priorities():
    il = Interlock()
    assert il.evaluate(inp(), 0).status == Status.CLEAR and il.evaluate(inp(), 0).permit
    s = il.evaluate(inp(person_active=True), 1)
    assert s.status == Status.PERSON and not s.permit and s.alarm
    s = il.evaluate(inp(fault_active=True), 2)
    assert s.status == Status.CAMERA_FAULT and not s.permit and s.alarm
    s = il.evaluate(inp(fault_active=True, person_active=True), 3)
    assert s.status == Status.PERSON


def test_fault_blocking_can_be_disabled():
    s = Interlock().evaluate(inp(fault_active=True, fault_blocks_crane=False), 0)
    assert s.permit and s.alarm


def test_starting_is_blocked_without_alarm_and_not_when_fault_blocking_off():
    s = Interlock().evaluate(inp(starting=True, fault_active=True), 0)
    assert s.status == Status.STARTING and not s.permit and not s.alarm
    assert Interlock().evaluate(inp(starting=True, fault_blocks_crane=False), 0).permit


def test_latch_until_reset():
    il = Interlock()
    s = il.evaluate(inp(person_active=True, latch_until_reset=True), 0)
    assert s.status == Status.LATCHED and not s.permit
    s = il.evaluate(inp(latch_until_reset=True), 1)           # person left, still latched
    assert s.status == Status.LATCHED and s.alarm
    il.request_reset()
    s = il.evaluate(inp(person_active=True, latch_until_reset=True), 2)   # reset refused while a person is in zone
    assert s.status == Status.LATCHED and s.reset_rejected
    il.request_reset()
    s = il.evaluate(inp(latch_until_reset=True), 3)
    assert s.status == Status.CLEAR and s.permit
    # latch disabled -> auto release
    il2 = Interlock()
    il2.evaluate(inp(person_active=True), 0)
    assert il2.evaluate(inp(), 1).permit


def test_pause_permits_and_auto_resumes():
    il = Interlock()
    il.pause(300, now=100)
    s = il.evaluate(inp(person_active=True), 101)
    assert s.status == Status.PAUSED and s.permit and not s.alarm and not s.ai_active
    assert 198 < s.pause_remaining_s <= 299
    s = il.evaluate(inp(person_active=True), 401)           # expired
    assert s.status == Status.PERSON and not s.permit
    il.pause(60, 500)
    il.resume()
    assert il.evaluate(inp(), 501).status == Status.CLEAR


def test_pause_clears_latch():
    il = Interlock()
    il.evaluate(inp(person_active=True, latch_until_reset=True), 0)
    il.pause(60, 1)
    assert il.evaluate(inp(latch_until_reset=True), 2).status == Status.PAUSED
    assert il.evaluate(inp(latch_until_reset=True), 70).status == Status.CLEAR


def test_load_gating_client_requirement():
    il = Interlock()
    g = dict(load_gating=True)
    s = il.evaluate(inp(person_active=True, load_present=False, **g), 0)
    assert s.status == Status.NO_LOAD and s.permit and not s.ai_active          # person w/o load = no violation
    s = il.evaluate(inp(person_active=True, load_present=True, **g), 1)
    assert s.status == Status.PERSON and not s.permit
    s = il.evaluate(inp(person_active=True, load_present=None, **g), 2)          # unknown -> stay protective
    assert s.status == Status.PERSON


def test_latched_survives_load_detach():
    il = Interlock()
    il.evaluate(inp(person_active=True, load_present=True, load_gating=True, latch_until_reset=True), 0)
    s = il.evaluate(inp(load_present=False, load_gating=True, latch_until_reset=True), 1)
    assert s.status == Status.LATCHED and not s.permit


def test_debouncer_matches_original_script_semantics():
    d = Debouncer(3, 15)
    states = [d.update(True) for _ in range(3)]
    assert states == [False, False, True]
    for _ in range(14):
        assert d.update(False) is True
    assert d.update(False) is False
    d.update(True); d.update(True); d.update(False)        # interrupted run restarts the count
    assert d.update(True) is False


def test_roi_modes():
    roi = RoiMask([(0.5, 0.0), (1.0, 0.0), (1.0, 1.0), (0.5, 1.0)])   # right half
    shape = (100, 200, 3)
    left, right, straddle = (10, 10, 60, 90), (120, 10, 180, 90), (60, 10, 140, 90)
    assert not roi.matches(left, shape, "any_overlap") and roi.matches(right, shape, "any_overlap")
    assert roi.matches(straddle, shape, "any_overlap")
    assert not roi.matches((60, 10, 120, 90), shape, "box_center")           # centre x=90 -> outside
    assert roi.matches((60, 10, 160, 90), shape, "box_center")           # centre x=110 -> inside
    assert not roi.matches((20, 10, 100, 90), shape, "foot_point")
    assert RoiMask(None).matches(left, shape)                             # no polygon = whole picture
    assert RoiMask([(0, 0), (1, 1)]).matches(left, shape)                 # < 3 points ignored
    assert not roi.matches((300, 300, 400, 400), shape, "any_overlap")    # outside the frame
