# garud360/core/detection/debounce.py
"""Trigger/release frame counting (same behaviour as the original test script)."""
from __future__ import annotations


class Debouncer:
    """Becomes active after `trigger` consecutive hits, inactive after `release` consecutive misses."""

    def __init__(self, trigger: int, release: int) -> None:
        self.trigger = max(1, int(trigger))
        self.release = max(1, int(release))
        self.active = False
        self._hits = 0
        self._misses = 0

    def configure(self, trigger: int, release: int) -> None:
        self.trigger = max(1, int(trigger))
        self.release = max(1, int(release))

    def update(self, hit: bool) -> bool:
        if hit:
            self._hits += 1
            self._misses = 0
            if not self.active and self._hits >= self.trigger:
                self.active = True
        else:
            self._misses += 1
            self._hits = 0
            if self.active and self._misses >= self.release:
                self.active = False
        return self.active

    def reset(self) -> None:
        self.active = False
        self._hits = 0
        self._misses = 0
