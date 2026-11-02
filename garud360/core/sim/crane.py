# garud360/core/sim/crane.py
"""Kinematic model of the simulated overhead crane (front elevation).

The crane shuttles a load between two pads. Movement happens only while the crane is
permitted; when blocked it brakes quickly and holds position until released - exactly what a
real crane does when the hold-to-run / enable circuit drops.
"""
from __future__ import annotations

from dataclasses import dataclass

PAD_A = 0.18
PAD_B = 0.82
Z_UP = 0.12          # hook height when travelling (0 = girder, 1 = floor)
Z_DOWN = 1.0
V_X = 0.13           # max trolley speed (fraction of span per second)
V_Z = 0.22           # max hoist speed
ACCEL = 0.35         # speed-up
BRAKE = 3.0          # emergency stop deceleration
DWELL_S = 1.6        # time to hook / unhook

_STEPS = ("to_src", "lower_src", "hook", "raise_src", "to_dst", "lower_dst", "unhook", "raise_dst")


@dataclass
class CraneSnapshot:
    x: float
    z: float
    load_attached: bool
    load_pad: float | None       # x position of the load while it rests on a pad
    phase: str
    permit: bool
    moving: bool
    watchdog_tripped: bool
    cycles: int


class CraneModel:
    def __init__(self) -> None:
        self.x = 0.5
        self.z = Z_UP
        self.vx = 0.0
        self.vz = 0.0
        self.src, self.dst = PAD_A, PAD_B
        self.load_pad: float | None = PAD_A
        self.load_attached = False
        self._step = 0
        self._dwell = 0.0
        self.permit = True
        self.watchdog_tripped = False
        self.cycles = 0

    # ---------------------------------------------------------------------------------
    @property
    def load_present(self) -> bool:
        """A load is suspended from the hook (the condition the client requires for monitoring)."""
        return self.load_attached

    def set_permit(self, permit: bool, watchdog_ok: bool = True) -> None:
        self.watchdog_tripped = not watchdog_ok
        self.permit = permit and watchdog_ok

    def snapshot(self) -> CraneSnapshot:
        moving = abs(self.vx) > 1e-3 or abs(self.vz) > 1e-3
        return CraneSnapshot(self.x, self.z, self.load_attached, self.load_pad, _STEPS[self._step],
                             self.permit, moving, self.watchdog_tripped, self.cycles)

    # ---------------------------------------------------------------------------------
    def step(self, dt: float) -> None:
        dt = max(0.0, min(dt, 0.25))
        if not self.permit:
            self.vx = _brake(self.vx, dt)
            self.vz = _brake(self.vz, dt)
            self.x += self.vx * dt
            self.z = min(max(self.z + self.vz * dt, 0.0), Z_DOWN)
            return
        name = _STEPS[self._step]
        if name in ("hook", "unhook"):
            self.vx = _brake(self.vx, dt, BRAKE)
            self.vz = _brake(self.vz, dt, BRAKE)
            self._dwell += dt
            if self._dwell >= DWELL_S:
                self._dwell = 0.0
                if name == "hook":
                    self.load_attached, self.load_pad = True, None
                else:
                    self.load_attached, self.load_pad = False, self.dst
                self._advance()
            return
        target_x, target_z = self.x, self.z
        if name == "to_src":
            target_x = self.src
        elif name == "to_dst":
            target_x = self.dst
        elif name in ("lower_src", "lower_dst"):
            target_z = Z_DOWN
        else:
            target_z = Z_UP
        done_x = self._move_axis("x", target_x, V_X, dt)
        done_z = self._move_axis("z", target_z, V_Z, dt)
        if done_x and done_z:
            self._advance()

    def _advance(self) -> None:
        self._step = (self._step + 1) % len(_STEPS)
        if self._step == 0:                      # cycle finished: swap pads and go the other way
            self.src, self.dst = self.dst, self.src
            self.cycles += 1

    def _move_axis(self, axis: str, target: float, vmax: float, dt: float) -> bool:
        pos = self.x if axis == "x" else self.z
        vel = self.vx if axis == "x" else self.vz
        dist = target - pos
        if abs(dist) < 0.004 and abs(vel) < 0.03:
            pos, vel = target, 0.0
            done = True
        else:
            direction = 1.0 if dist > 0 else -1.0
            stopping = (vel * vel) / (2.0 * ACCEL) if vel * direction > 0 else 0.0
            desired = direction * vmax if abs(dist) > stopping + 0.002 else 0.0
            if desired * direction > 0 or abs(vel) > 0:
                step = ACCEL * dt
                vel = vel + max(-step, min(step, desired - vel))
            pos += vel * dt
            if (target - pos) * direction < 0:   # overshoot guard
                pos, vel = target, 0.0
            done = False
        if axis == "x":
            self.x, self.vx = pos, vel
        else:
            self.z, self.vz = min(max(pos, 0.0), Z_DOWN), vel
        return done


def _brake(v: float, dt: float, decel: float = BRAKE) -> float:
    if v > 0:
        return max(0.0, v - decel * dt)
    return min(0.0, v + decel * dt)
