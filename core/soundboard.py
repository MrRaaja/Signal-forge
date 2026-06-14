"""
soundboard.py
-------------
Sample playback for the 8 pads.

* Loads WAV (and MP3 if your libsndfile build supports it) via `soundfile`.
* Samples are decoded once, converted to stereo float32, and resampled to the
  engine samplerate with linear interpolation (cheap, fine for one-shots).
* Three trigger modes:
    - "oneshot" : each hit plays the whole sample to the end (re-triggerable,
                  multiple overlapping copies allowed).
    - "hold"    : plays while the pad is held; stops on release.
    - "toggle"  : first hit starts looping/holding, second hit stops.
* render(frames) mixes all active playbacks into a (frames, 2) buffer.

Thread-safety: trigger/release/stop come from the MIDI thread, render() from the
audio thread. A short lock guards the active-playback lists.
"""

from __future__ import annotations

import threading
import numpy as np

try:
    import soundfile as sf
except Exception:  # pragma: no cover - import guard for clearer error msg
    sf = None


def _load_sample(path: str, target_sr: int) -> np.ndarray:
    """Load an audio file -> (N, 2) float32 at target_sr. Raises on failure."""
    if sf is None:
        raise RuntimeError("soundfile is not installed")
    data, sr = sf.read(path, dtype="float32", always_2d=True)  # (N, ch)
    # force stereo
    if data.shape[1] == 1:
        data = np.repeat(data, 2, axis=1)
    elif data.shape[1] > 2:
        data = data[:, :2]
    # linear resample if needed
    if sr != target_sr and data.shape[0] > 1:
        duration = data.shape[0] / sr
        new_n = max(int(round(duration * target_sr)), 1)
        old_idx = np.linspace(0.0, data.shape[0] - 1, num=new_n)
        base = np.floor(old_idx).astype(np.int64)
        frac = (old_idx - base).astype(np.float32)[:, None]
        nxt = np.minimum(base + 1, data.shape[0] - 1)
        data = data[base] * (1.0 - frac) + data[nxt] * frac
    return np.ascontiguousarray(data, dtype=np.float32)


class _Playback:
    __slots__ = ("sample", "pos", "loop")

    def __init__(self, sample: np.ndarray, loop: bool):
        self.sample = sample
        self.pos = 0
        self.loop = loop

    def render(self, frames: int) -> np.ndarray:
        out = np.zeros((frames, 2), dtype=np.float32)
        n = self.sample.shape[0]
        written = 0
        while written < frames:
            if self.pos >= n:
                if self.loop:
                    self.pos = 0
                else:
                    break
            chunk = min(frames - written, n - self.pos)
            out[written:written + chunk] = self.sample[self.pos:self.pos + chunk]
            self.pos += chunk
            written += chunk
        return out

    @property
    def finished(self) -> bool:
        return (not self.loop) and self.pos >= self.sample.shape[0]


class Pad:
    def __init__(self):
        self.sample: np.ndarray | None = None
        self.file: str | None = None
        self.mode: str = "oneshot"          # oneshot | hold | toggle
        self.volume: float = 1.0
        self.playbacks: list[_Playback] = []
        self.toggled_on: bool = False


class Soundboard:
    def __init__(self, samplerate: int = 48000, num_pads: int = 8):
        self.sr = samplerate
        self.pads = [Pad() for _ in range(num_pads)]
        self._lock = threading.Lock()

    # ---------------------------------------------------------------- config
    def assign(self, idx: int, path: str) -> None:
        """Load a sample onto a pad. Raises on decode error (caller reports)."""
        sample = _load_sample(path, self.sr)
        with self._lock:
            pad = self.pads[idx]
            pad.sample = sample
            pad.file = path
            pad.playbacks.clear()
            pad.toggled_on = False

    def clear(self, idx: int) -> None:
        with self._lock:
            pad = self.pads[idx]
            pad.sample = None
            pad.file = None
            pad.playbacks.clear()
            pad.toggled_on = False

    def has_sample(self, idx: int) -> bool:
        """True if this pad has a sample loaded (so it should claim its note)."""
        if 0 <= idx < len(self.pads):
            return self.pads[idx].sample is not None
        return False

    def set_mode(self, idx: int, mode: str) -> None:
        with self._lock:
            self.pads[idx].mode = mode

    def set_volume(self, idx: int, vol: float) -> None:
        with self._lock:
            self.pads[idx].volume = float(np.clip(vol, 0.0, 1.0))

    # --------------------------------------------------------------- control
    def trigger(self, idx: int) -> None:
        with self._lock:
            pad = self.pads[idx]
            if pad.sample is None:
                return
            if pad.mode == "oneshot":
                pad.playbacks.append(_Playback(pad.sample, loop=False))
            elif pad.mode == "hold":
                pad.playbacks = [_Playback(pad.sample, loop=True)]
            elif pad.mode == "toggle":
                if pad.toggled_on:
                    pad.playbacks.clear()
                    pad.toggled_on = False
                else:
                    pad.playbacks = [_Playback(pad.sample, loop=True)]
                    pad.toggled_on = True

    def release(self, idx: int) -> None:
        """Pad physically released -- only matters for 'hold' mode."""
        with self._lock:
            pad = self.pads[idx]
            if pad.mode == "hold":
                pad.playbacks.clear()

    def stop(self, idx: int) -> None:
        with self._lock:
            pad = self.pads[idx]
            pad.playbacks.clear()
            pad.toggled_on = False

    def stop_all(self) -> None:
        with self._lock:
            for pad in self.pads:
                pad.playbacks.clear()
                pad.toggled_on = False

    # ---------------------------------------------------------------- render
    def render(self, frames: int) -> np.ndarray:
        out = np.zeros((frames, 2), dtype=np.float32)
        with self._lock:
            for pad in self.pads:
                if not pad.playbacks:
                    continue
                pad_buf = np.zeros((frames, 2), dtype=np.float32)
                for pb in pad.playbacks:
                    pad_buf += pb.render(frames)
                pad.playbacks = [pb for pb in pad.playbacks if not pb.finished]
                out += pad_buf * pad.volume
        return out
