"""
synth.py
--------
A small, fast, polyphonic synthesiser intended to run inside an audio callback.

Design goals
============
* No per-sample Python loops in the hot path -- everything is vectorised with
  numpy so a block of N frames is rendered with a handful of array ops.
* Phase-continuous oscillators (no clicks between blocks).
* A vectorised linear ADSR envelope that is sample-accurate across block
  boundaries (also click-free on note-off thanks to the release stage).
* Velocity sensitivity.
* A hard polyphony cap with oldest-voice stealing.

The tone is a simple additive "electric-piano-ish" timbre: a fundamental plus a
few decaying harmonics. It is deliberately cheap. SoundFont support can be added
later behind the same note_on / note_off / render interface without touching the
rest of the app.

Thread-safety
=============
note_on / note_off are called from the MIDI thread; render() is called from the
audio thread. A short lock guards the voice list. Critical sections are tiny.
"""

from __future__ import annotations

import threading
import numpy as np


# ---------------------------------------------------------------------------
# Instrument profiles
# ===================
# Each profile defines the additive harmonic amplitudes (relative to the
# fundamental) and an ADSR envelope (attack, decay, sustain, release) in
# seconds / 0..1. These shape the timbre played from the keyboard.
# ---------------------------------------------------------------------------
PROFILES: dict[str, dict] = {
    "Electric Piano": {
        "harmonics": [1.0, 0.5, 0.28, 0.14],
        "adsr": (0.005, 0.6, 0.30, 0.35),
    },
    "Organ": {
        # drawbar-style: strong odd + octave partials, fully sustained
        "harmonics": [1.0, 0.0, 0.85, 0.0, 0.6, 0.0, 0.4, 0.7],
        "adsr": (0.01, 0.05, 1.0, 0.08),
    },
    "Synth Lead": {
        # bright, saw-ish stack
        "harmonics": [1.0, 0.6, 0.42, 0.32, 0.24, 0.18, 0.12, 0.08],
        "adsr": (0.005, 0.2, 0.8, 0.18),
    },
    "Strings": {
        # slow swell, sustained
        "harmonics": [1.0, 0.7, 0.5, 0.35, 0.22, 0.14],
        "adsr": (0.18, 0.3, 0.9, 0.45),
    },
    "Bass": {
        # fat low end, few partials, quick decay
        "harmonics": [1.0, 0.45, 0.18],
        "adsr": (0.005, 0.35, 0.5, 0.15),
    },
}
DEFAULT_PROFILE = "Electric Piano"


def _norm_harmonics(amps) -> np.ndarray:
    a = np.asarray(amps, dtype=np.float64)
    s = a.sum()
    return a / s if s > 0 else a


def midi_to_freq(note: int) -> float:
    """Convert a MIDI note number to frequency in Hz (A4 = 69 = 440 Hz)."""
    return 440.0 * (2.0 ** ((note - 69) / 12.0))


class _Envelope:
    """Vectorised linear ADSR. process(n, gate) -> float32 array of length n."""

    ATTACK, DECAY, SUSTAIN, RELEASE, DONE = range(5)

    def __init__(self, samplerate: int,
                 attack: float = 0.005, decay: float = 0.6,
                 sustain: float = 0.30, release: float = 0.35):
        self.sr = samplerate
        self.a = max(attack, 1e-4)
        self.d = max(decay, 1e-4)
        self.s = float(np.clip(sustain, 0.0, 1.0))
        self.r = max(release, 1e-4)
        self.stage = self.ATTACK
        self.level = 0.0

    def note_off(self) -> None:
        if self.stage != self.DONE:
            self.stage = self.RELEASE

    @property
    def finished(self) -> bool:
        return self.stage == self.DONE

    def process(self, n: int) -> np.ndarray:
        """Render n envelope samples, advancing internal state."""
        out = np.empty(n, dtype=np.float64)
        i = 0
        while i < n:
            remaining = n - i
            if self.stage == self.ATTACK:
                rate = 1.0 / (self.a * self.sr)          # per-sample increment
                steps_to_target = int(np.ceil((1.0 - self.level) / rate)) if rate > 0 else 0
                k = min(remaining, max(steps_to_target, 1))
                seg = self.level + rate * np.arange(1, k + 1)
                np.clip(seg, 0.0, 1.0, out=seg)
                out[i:i + k] = seg
                self.level = float(seg[-1])
                i += k
                if self.level >= 1.0 - 1e-6:
                    self.level = 1.0
                    self.stage = self.DECAY
            elif self.stage == self.DECAY:
                rate = (1.0 - self.s) / (self.d * self.sr)
                if rate <= 0:
                    self.level = self.s
                    self.stage = self.SUSTAIN
                    continue
                steps_to_target = int(np.ceil((self.level - self.s) / rate))
                k = min(remaining, max(steps_to_target, 1))
                seg = self.level - rate * np.arange(1, k + 1)
                np.clip(seg, self.s, 1.0, out=seg)
                out[i:i + k] = seg
                self.level = float(seg[-1])
                i += k
                if self.level <= self.s + 1e-6:
                    self.level = self.s
                    self.stage = self.SUSTAIN
            elif self.stage == self.SUSTAIN:
                out[i:n] = self.s
                self.level = self.s
                i = n  # sustain fills the rest of the block; gate handled by note_off
            elif self.stage == self.RELEASE:
                # Constant slope: full-scale release takes self.r seconds.
                rate = 1.0 / (self.r * self.sr) if self.r > 0 else 1.0
                if rate <= 0:
                    out[i:n] = 0.0
                    self.level = 0.0
                    self.stage = self.DONE
                    i = n
                    continue
                steps_to_zero = int(np.ceil(self.level / rate))
                k = min(remaining, max(steps_to_zero, 1))
                seg = self.level - rate * np.arange(1, k + 1)
                np.clip(seg, 0.0, 1.0, out=seg)
                out[i:i + k] = seg
                self.level = float(seg[-1])
                i += k
                if self.level <= 1e-5:
                    self.level = 0.0
                    self.stage = self.DONE
            else:  # DONE
                out[i:n] = 0.0
                i = n
        return out.astype(np.float32)


class _Voice:
    __slots__ = ("note", "freq", "vel", "phase", "env", "age", "harmonics", "harm_n")

    def __init__(self, note: int, velocity: int, samplerate: int, age: int,
                 harmonics: np.ndarray, adsr: tuple):
        self.note = note
        self.freq = midi_to_freq(note)
        self.vel = float(velocity) / 127.0
        self.phase = 0.0                       # in cycles (0..1)
        self.env = _Envelope(samplerate, *adsr)
        self.age = age                         # for voice stealing
        self.harmonics = harmonics
        self.harm_n = np.arange(1, len(harmonics) + 1, dtype=np.float64)

    def render(self, n: int, samplerate: int, cum_pitch: np.ndarray) -> np.ndarray:
        # cum_pitch is the per-sample cumulative pitch factor (cumsum of the
        # bend * vibrato curve), shared across all voices. Multiplying by the
        # voice's base per-sample phase increment gives sample-accurate pitch
        # bend + vibrato that stays phase-continuous across blocks.
        base_dphase = self.freq / samplerate
        idx = self.phase + base_dphase * cum_pitch
        sig = np.zeros(n, dtype=np.float64)
        two_pi = 2.0 * np.pi
        for amp, h in zip(self.harmonics, self.harm_n):
            if amp != 0.0:
                sig += amp * np.sin(two_pi * h * idx)
        self.phase = (self.phase + base_dphase * cum_pitch[-1]) % 1.0
        env = self.env.process(n)
        return (sig * env * self.vel).astype(np.float32)


class _StereoDelay:
    """Feedback delay (echo) for stereo float32 blocks.

    Block-safe without per-sample recursion: the delay time is always longer
    than the audio block, so each block reads only from already-written history.
    """

    def __init__(self, samplerate: int, max_seconds: float = 2.0):
        self.sr = samplerate
        self.cap = max(int(samplerate * max_seconds), 1)
        self.buf = np.zeros((self.cap, 2), dtype=np.float32)
        self.w = 0
        self.enabled = False
        self.delay_samples = int(0.3 * samplerate)
        self.feedback = 0.35
        self.mix = 0.25

    def set_params(self, enabled: bool, time_ms: float,
                   feedback: float, mix: float) -> None:
        self.enabled = bool(enabled)
        d = int(round(time_ms / 1000.0 * self.sr))
        self.delay_samples = int(np.clip(d, 1, self.cap - 1))
        self.feedback = float(np.clip(feedback, 0.0, 0.95))
        self.mix = float(np.clip(mix, 0.0, 1.0))

    def clear(self) -> None:
        self.buf.fill(0.0)
        self.w = 0

    def process(self, x: np.ndarray) -> np.ndarray:
        if not self.enabled:
            return x
        n = x.shape[0]
        d = self.delay_samples
        ar = np.arange(n)
        r = (self.w - d + ar) % self.cap
        delayed = self.buf[r]
        wet = x + self.mix * delayed
        wv = (self.w + ar) % self.cap
        self.buf[wv] = x + self.feedback * delayed
        self.w = (self.w + n) % self.cap
        return wet.astype(np.float32)


class Synth:
    def __init__(self, samplerate: int = 48000, max_voices: int = 24,
                 gain: float = 0.6):
        self.sr = samplerate
        self.max_voices = max_voices
        self.gain = gain
        self._voices: list[_Voice] = []
        self._age = 0
        self._lock = threading.Lock()

        # current instrument profile (timbre + envelope)
        self.profile_name = DEFAULT_PROFILE
        prof = PROFILES[DEFAULT_PROFILE]
        self.harmonics = _norm_harmonics(prof["harmonics"])
        self.adsr = tuple(prof["adsr"])

        # echo / delay effect
        self.delay = _StereoDelay(samplerate)

        # ---- performance controls (pitch bend / mod wheel / sustain) ----
        self.bend = 1.0                 # frequency multiplier (1.0 == centre)
        self.bend_range = 2.0           # +/- semitones at full wheel
        self.mod_depth = 0.0            # vibrato depth as a frequency ratio
        self.mod_max = 0.03             # ratio at full mod wheel (~half semitone)
        self.lfo_rate = 5.5             # vibrato speed in Hz
        self._lfo_phase = 0.0
        self.sustain = False            # sustain pedal held?
        self._held: set[int] = set()        # notes physically down
        self._sustained: set[int] = set()   # notes kept by the pedal

    # ---------------------------------------------------------------- control
    def note_on(self, note: int, velocity: int) -> None:
        if velocity <= 0:
            self.note_off(note)
            return
        with self._lock:
            self._age += 1
            self._held.add(note)
            self._sustained.discard(note)
            # retrigger if same note already sounding
            for v in self._voices:
                if v.note == note and not v.env.finished:
                    v.vel = velocity / 127.0
                    v.env = _Envelope(self.sr, *self.adsr)
                    v.harmonics = self.harmonics
                    v.harm_n = np.arange(1, len(self.harmonics) + 1, dtype=np.float64)
                    v.age = self._age
                    return
            if len(self._voices) >= self.max_voices:
                # steal the oldest voice
                self._voices.sort(key=lambda x: x.age)
                self._voices.pop(0)
            self._voices.append(
                _Voice(note, velocity, self.sr, self._age,
                       self.harmonics, self.adsr))

    def note_off(self, note: int) -> None:
        with self._lock:
            self._held.discard(note)
            if self.sustain:
                self._sustained.add(note)   # held by the pedal; keep sounding
                return
            self._release_note_locked(note)

    def _release_note_locked(self, note: int) -> None:
        for v in self._voices:
            if v.note == note and v.env.stage < _Envelope.RELEASE:
                v.env.note_off()

    def all_notes_off(self) -> None:
        with self._lock:
            self._held.clear()
            self._sustained.clear()
            for v in self._voices:
                v.env.note_off()

    # -------------------------------------------------- performance controls
    def set_pitch_bend(self, value14: int) -> None:
        """value14: raw MIDI pitch wheel, -8192..8191 (0 == centre)."""
        semis = (value14 / 8192.0) * self.bend_range
        self.bend = 2.0 ** (semis / 12.0)

    def set_mod(self, value0to1: float) -> None:
        """Mod wheel 0..1 -> vibrato depth."""
        self.mod_depth = float(np.clip(value0to1, 0.0, 1.0)) * self.mod_max

    def set_sustain(self, on: bool) -> None:
        with self._lock:
            self.sustain = bool(on)
            if not self.sustain:
                for note in list(self._sustained):
                    if note not in self._held:
                        self._release_note_locked(note)
                self._sustained.clear()

    # ----------------------------------------------------------- profile / fx
    def set_profile(self, name: str) -> None:
        """Switch the instrument timbre. New/retriggered notes use it."""
        prof = PROFILES.get(name)
        if not prof:
            return
        with self._lock:
            self.profile_name = name
            self.harmonics = _norm_harmonics(prof["harmonics"])
            self.adsr = tuple(prof["adsr"])

    def set_echo(self, enabled: bool, time_ms: float,
                 feedback: float, mix: float) -> None:
        self.delay.set_params(enabled, time_ms, feedback, mix)

    def _pitch_curve(self, n: int) -> np.ndarray:
        """Per-sample cumulative pitch factor from bend + vibrato (mod wheel)."""
        if self.mod_depth > 0.0:
            inc = self.lfo_rate / self.sr
            t = self._lfo_phase + np.arange(1, n + 1, dtype=np.float64) * inc
            lfo = np.sin(2.0 * np.pi * t)
            self._lfo_phase = (self._lfo_phase + n * inc) % 1.0
            pf = self.bend * (1.0 + self.mod_depth * lfo)
        else:
            pf = np.full(n, self.bend, dtype=np.float64)
        return np.cumsum(pf)

    # ---------------------------------------------------------------- render
    def render(self, frames: int) -> np.ndarray:
        """Return a (frames, 2) float32 stereo buffer."""
        mono = np.zeros(frames, dtype=np.float32)
        with self._lock:
            if self._voices:
                cum_pitch = self._pitch_curve(frames)
                for v in self._voices:
                    mono += v.render(frames, self.sr, cum_pitch)
                # drop finished voices
                self._voices = [v for v in self._voices if not v.env.finished]
        mono *= self.gain
        # soft clip to be safe under heavy polyphony
        np.tanh(mono, out=mono)
        stereo = np.column_stack((mono, mono))
        return self.delay.process(stereo)
