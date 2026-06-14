"""
micproc.py
----------
Mic dynamics: a noise gate and a compressor, applied to the mono mic signal
before the voice changer.

Both work at block granularity with a smoothed gain ramped across each block, so
they're click-free without needing a per-sample Python loop in the callback. This
is plenty for cleaning up a Discord mic (cut keyboard clatter / hiss between
phrases, even out level) — not a mastering-grade dynamics processor.
"""

from __future__ import annotations

import numpy as np


def _db_to_lin(db: float) -> float:
    return float(10.0 ** (db / 20.0))


class MicProcessor:
    def __init__(self, samplerate: int = 48000):
        self.sr = samplerate
        self.gate_enabled = False
        self.gate_threshold_db = -45.0
        self.comp_enabled = False
        self.comp_threshold_db = -18.0
        self.comp_ratio = 3.0
        self.makeup_db = 6.0
        self._gate_gain = 0.0
        self._comp_gain = 1.0

    def set_gate(self, enabled: bool, threshold_db: float) -> None:
        self.gate_enabled = bool(enabled)
        self.gate_threshold_db = float(threshold_db)

    def set_comp(self, enabled: bool, threshold_db: float,
                 ratio: float, makeup_db: float | None = None) -> None:
        self.comp_enabled = bool(enabled)
        self.comp_threshold_db = float(threshold_db)
        self.comp_ratio = max(1.0, float(ratio))
        if makeup_db is not None:
            self.makeup_db = float(makeup_db)

    @property
    def active(self) -> bool:
        return self.gate_enabled or self.comp_enabled

    def process(self, x: np.ndarray) -> np.ndarray:
        if not self.active:
            return x
        n = x.shape[0]
        rms = float(np.sqrt(np.mean(x * x)) + 1e-12)
        rms_db = 20.0 * np.log10(rms + 1e-12)

        # --- noise gate (open fast, close slower) ---
        target_gate = 1.0
        if self.gate_enabled:
            target_gate = 1.0 if rms_db > self.gate_threshold_db else 0.0
        coeff = 0.5 if target_gate > self._gate_gain else 0.12
        g0 = self._gate_gain
        g1 = g0 + (target_gate - g0) * coeff
        gate_ramp = np.linspace(g0, g1, n, dtype=np.float32)
        self._gate_gain = g1

        # --- compressor (downward, above threshold) ---
        target_comp = 1.0
        if self.comp_enabled and rms_db > self.comp_threshold_db:
            over = rms_db - self.comp_threshold_db
            gain_reduction_db = over - (over / self.comp_ratio)
            target_comp = _db_to_lin(-gain_reduction_db)
        c0 = self._comp_gain
        c1 = c0 + (target_comp - c0) * 0.25
        comp_ramp = np.linspace(c0, c1, n, dtype=np.float32)
        self._comp_gain = c1

        makeup = _db_to_lin(self.makeup_db) if self.comp_enabled else 1.0
        return (x * gate_ramp * comp_ramp * makeup).astype(np.float32)
