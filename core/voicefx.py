"""
voicefx.py
----------
Real-time voice changer for the microphone signal.

* Pitch shift: a vectorised granular (overlap-add, two crossfaded grains)
  pitch shifter. No per-sample Python loop -- a whole block is gathered with
  numpy fancy-indexing + linear interpolation, so it's cheap enough for the
  audio callback. Quality is "good fun" rather than studio-grade (granular
  shifters have a little warble), which is exactly right for a Discord voice
  changer.
* Robot: ring modulation (multiply by a sine) for a classic robotic timbre.

Everything is mono in / mono out (the mic is summed to mono first). When the
effect is disabled, or pitch == 0 and robot is off, the input passes through
untouched (true bypass, no artefacts).
"""

from __future__ import annotations

import numpy as np


class VoiceChanger:
    def __init__(self, samplerate: int = 48000, grain: int = 1024):
        self.sr = samplerate
        self.G = int(grain)
        self.enabled = False
        self.semitones = 0.0
        self.robot = False
        self.robot_hz = 120.0
        self._phase = 0.0           # grain sawtooth phase (0..1)
        self._ring_phase = 0.0      # robot oscillator phase (0..1)
        self._tail = np.zeros(self.G + 2, dtype=np.float32)

    def set_params(self, enabled: bool, semitones: float, robot: bool) -> None:
        self.enabled = bool(enabled)
        self.semitones = float(np.clip(semitones, -12.0, 12.0))
        self.robot = bool(robot)

    def reset(self) -> None:
        self._tail.fill(0.0)
        self._phase = 0.0
        self._ring_phase = 0.0

    # ------------------------------------------------------------------ process
    def process(self, x: np.ndarray) -> np.ndarray:
        """x: mono float32 (n,). Returns mono float32 (n,)."""
        if not self.enabled:
            return x
        n = x.shape[0]
        y = x
        if abs(self.semitones) > 1e-6:
            y = self._pitch_shift(x, 2.0 ** (self.semitones / 12.0))
        if self.robot:
            inc = self.robot_hz / self.sr
            t = self._ring_phase + np.arange(1, n + 1, dtype=np.float64) * inc
            y = (y * np.sin(2.0 * np.pi * t)).astype(np.float32)
            self._ring_phase = (self._ring_phase + n * inc) % 1.0
        return y.astype(np.float32)

    def _pitch_shift(self, x: np.ndarray, ratio: float) -> np.ndarray:
        n = x.shape[0]
        G = self.G
        hist = np.concatenate([self._tail, x.astype(np.float32)])
        base = self._tail.shape[0]                 # index of first new sample
        step = (1.0 - ratio) / G                   # grain phase increment/sample

        ph = self._phase + np.arange(n, dtype=np.float64) * step
        p1 = ph % 1.0
        p2 = (ph + 0.5) % 1.0
        idx = base + np.arange(n)
        s1 = self._interp(hist, idx - p1 * G)
        s2 = self._interp(hist, idx - p2 * G)
        # Two Hann grains offset by half a period -> their windows sum to 1.
        w1 = 0.5 * (1.0 - np.cos(2.0 * np.pi * p1))
        w2 = 0.5 * (1.0 - np.cos(2.0 * np.pi * p2))
        out = (w1 * s1 + w2 * s2).astype(np.float32)

        self._phase = (self._phase + n * step) % 1.0
        self._tail = hist[-(G + 2):].astype(np.float32)
        return out

    @staticmethod
    def _interp(buf: np.ndarray, pos: np.ndarray) -> np.ndarray:
        pos = np.clip(pos, 0.0, buf.shape[0] - 1.0001)
        i0 = np.floor(pos).astype(np.int64)
        frac = (pos - i0).astype(np.float32)
        return buf[i0] * (1.0 - frac) + buf[i0 + 1] * frac
