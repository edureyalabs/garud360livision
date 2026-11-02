# garud360/core/alerts/siren.py
"""Two-tone siren. Plays a looping WAV through winsound on Windows (no-op elsewhere)."""
from __future__ import annotations

import logging
import math
import struct
import sys
import threading
import wave
from pathlib import Path
from typing import Any, Callable

log = logging.getLogger(__name__)
RATE = 22050


def build_wav(path: Path, low_hz: int, high_hz: int, tone_ms: int) -> None:
    frames = bytearray()
    for hz in (low_hz, high_hz):
        n = int(RATE * tone_ms / 1000)
        fade = max(1, int(RATE * 0.005))
        for i in range(n):
            amp = min(1.0, i / fade, (n - i) / fade)
            frames += struct.pack("<h", int(32767 * 0.6 * amp * math.sin(2 * math.pi * hz * i / RATE)))
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(bytes(frames))


class SirenController:
    def __init__(self, settings: Callable[[], dict[str, Any]], work_dir: Path) -> None:
        self._settings = settings
        self._dir = work_dir
        self._lock = threading.Lock()
        self._playing = False
        self._alarms: set[int] = set()
        self._muted: set[int] | None = None       # alarm ids that were active when muted
        self._wav: Path | None = None
        self._wav_key: tuple[int, int, int] | None = None
        self._test_until = 0.0

    @property
    def playing(self) -> bool:
        return self._playing

    @property
    def muted(self) -> bool:
        return self._muted is not None

    def update(self, alarmed_spaces: set[int]) -> None:
        """Called periodically with the ids of all spaces that currently want the siren."""
        with self._lock:
            self._alarms = set(alarmed_spaces)
            if not self._alarms:
                self._muted = None
            elif self._muted is not None and not self._alarms <= self._muted:
                self._muted = None                  # a NEW alarm un-mutes the siren
            want = bool(self._alarms) and self._muted is None
        self._apply(want)

    def mute(self) -> None:
        with self._lock:
            if self._alarms:
                self._muted = set(self._alarms)
        self._apply(False)

    def test(self, seconds: float = 3.0) -> None:
        import time
        self._test_until = time.monotonic() + seconds
        self._apply(True)
        threading.Timer(seconds, lambda: self._apply(bool(self._alarms) and self._muted is None)).start()

    def close(self) -> None:
        self._apply(False)

    # -- internals --------------------------------------------------------------
    def _apply(self, want: bool) -> None:
        if want == self._playing:
            return
        if sys.platform != "win32":
            self._playing = want
            log.info("Siren %s (audio only on Windows)", "ON" if want else "OFF")
            return
        import winsound
        try:
            if want:
                s = self._settings()
                key = (int(s["siren_low_hz"]), int(s["siren_high_hz"]), int(s["siren_tone_ms"]))
                if self._wav is None or self._wav_key != key:
                    self._wav = self._dir / f"siren_{key[0]}_{key[1]}_{key[2]}.wav"
                    if not self._wav.exists():
                        build_wav(self._wav, *key)
                    self._wav_key = key
                winsound.PlaySound(str(self._wav), winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_LOOP)
            else:
                winsound.PlaySound(None, winsound.SND_PURGE)
            self._playing = want
        except Exception:  # noqa: BLE001 - audio problems must never affect safety logic
            log.exception("Siren audio failed")
