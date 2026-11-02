# garud360/core/space/interlock.py
"""Pure crane-interlock decision logic (no I/O, fully unit-tested).

Priority (highest first):
    1. PAUSED       operator paused AI to attach/detach a load -> crane permitted, no alarm
    2. LATCHED      a violation is latched until a manual reset -> crane blocked, alarm on
    3. NO_LOAD      load gating is on and no load is suspended -> AI disabled, crane permitted
    4. STARTING     cameras not proven healthy yet -> crane blocked (fail-safe), no alarm
    5. PERSON       person confirmed in the zone -> crane blocked, alarm on
    6. CAMERA_FAULT camera lost / detector stalled -> crane blocked (if configured), alarm on
    7. CLEAR        crane permitted
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Status(str, Enum):
    STOPPED = "STOPPED"
    STARTING = "STARTING"
    CLEAR = "CLEAR"
    PERSON = "PERSON DETECTED"
    CAMERA_FAULT = "CAMERA FAULT"
    LATCHED = "LATCHED - RESET REQUIRED"
    PAUSED = "PAUSED"
    NO_LOAD = "NO LOAD - AI OFF"


@dataclass(frozen=True)
class InterlockInputs:
    person_active: bool
    fault_active: bool
    starting: bool
    load_present: bool | None = None      # None = unknown / not wired
    load_gating: bool = False             # only monitor while a load is suspended
    latch_until_reset: bool = False
    fault_blocks_crane: bool = True


@dataclass(frozen=True)
class InterlockState:
    status: Status
    permit: bool                  # True = crane movement allowed
    alarm: bool                   # True = siren / red alert
    ai_active: bool               # should cameras run detection?
    reason: str = ""
    latched: bool = False
    pause_remaining_s: float = 0.0
    reset_rejected: bool = False


class Interlock:
    def __init__(self) -> None:
        self._latched = False
        self._latch_reason = ""
        self._paused_until: float | None = None
        self._reset_requested = False

    # -- commands (thread-safe enough: single bool/float assignments) ----------
    def pause(self, seconds: float, now: float) -> None:
        self._paused_until = now + max(1.0, seconds)
        self._latched = False
        self._latch_reason = ""

    def resume(self) -> None:
        self._paused_until = None

    def request_reset(self) -> None:
        self._reset_requested = True

    @property
    def is_paused(self) -> bool:
        return self._paused_until is not None

    def clear_all(self) -> None:
        self._latched, self._latch_reason = False, ""
        self._paused_until = None
        self._reset_requested = False

    # -- evaluation ---------------------------------------------------------------
    def evaluate(self, i: InterlockInputs, now: float) -> InterlockState:
        reset_rejected = False
        # 1. pause
        if self._paused_until is not None:
            remaining = self._paused_until - now
            if remaining > 0:
                self._reset_requested = False
                return InterlockState(Status.PAUSED, True, False, False,
                                      "Paused by operator", False, remaining)
            self._paused_until = None            # auto-resume

        gated_off = i.load_gating and i.load_present is False
        violation = (not gated_off) and not i.starting and (
            i.person_active or (i.fault_active and i.fault_blocks_crane))

        # manual reset: accepted only while the zone is genuinely clear
        if self._reset_requested:
            self._reset_requested = False
            if self._latched:
                if violation:
                    reset_rejected = True
                else:
                    self._latched, self._latch_reason = False, ""

        # 2. latched
        if i.latch_until_reset and violation and not self._latched:
            self._latched = True
            self._latch_reason = "Person detected" if i.person_active else "Camera fault"
        if not i.latch_until_reset:
            self._latched, self._latch_reason = False, ""
        if self._latched:
            return InterlockState(Status.LATCHED, False, True, True,
                                  f"{self._latch_reason} - press Reset when the zone is clear", True, 0.0,
                                  reset_rejected)
        # 3. no load
        if gated_off:
            return InterlockState(Status.NO_LOAD, True, False, False, "No suspended load", False, 0.0, reset_rejected)
        # 4. starting
        if i.starting:
            return InterlockState(Status.STARTING, not i.fault_blocks_crane, False, True,
                                  "Checking cameras", False, 0.0, reset_rejected)
        # 5/6. violations
        if i.person_active:
            return InterlockState(Status.PERSON, False, True, True, "Person in zone", False, 0.0, reset_rejected)
        if i.fault_active:
            return InterlockState(Status.CAMERA_FAULT, not i.fault_blocks_crane, True, True,
                                  "Camera fault", False, 0.0, reset_rejected)
        return InterlockState(Status.CLEAR, True, False, True, "Zone clear", False, 0.0, reset_rejected)
