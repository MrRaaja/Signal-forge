"""
mixer.py  (AudioEngine)
-----------------------
Owns the synth + soundboard and does the real-time mixing and device routing.

Routing model
=============
There are up to three independent PortAudio streams, each with its own clock:

    microphone  --(mic ring buffer)-->  MASTER output callback
                                              |  renders synth + pads,
                                              |  mixes in mic, applies volumes
                                              v
                              MASTER output device  (your headphones / monitor)
                                              |
                                       (sec ring buffer)
                                              v
                              SECONDARY output device (VB-CABLE -> Discord)

The MASTER stream is the one that drives rendering, so the device you *hear*
(your monitor) gets the lowest latency. The SECONDARY stream (the virtual cable
feeding Discord) is fed from a ring buffer -- Discord tolerates a little extra
latency/jitter far better than your ears do.

If no monitor is selected, the cable becomes the master and there is no
secondary stream. If monitor == cable, there is only the master stream.

Two-clock caveat
================
The mic-in clock, master-out clock and secondary-out clock are not synchronised.
We bridge them with ring buffers and handle under/overrun gracefully (insert
silence on underrun, drop oldest on overrun). For an MVP this is stable for long
sessions; sample-accurate sync would need adaptive resampling (out of scope).
"""

from __future__ import annotations

import threading
import numpy as np

try:
    import sounddevice as sd
except Exception:  # pragma: no cover
    sd = None

from .synth import Synth
from .soundboard import Soundboard
from .voicefx import VoiceChanger
from .micproc import MicProcessor


class RingBuffer:
    """Simple thread-safe stereo float32 ring buffer (frames x 2)."""

    def __init__(self, capacity_frames: int):
        self.cap = capacity_frames
        self.buf = np.zeros((capacity_frames, 2), dtype=np.float32)
        self.w = 0
        self.r = 0
        self.count = 0
        self.lock = threading.Lock()

    def write(self, data: np.ndarray) -> None:
        n = data.shape[0]
        with self.lock:
            if n > self.cap:
                data = data[-self.cap:]
                n = self.cap
            # overrun: drop oldest by advancing read pointer
            if self.count + n > self.cap:
                drop = self.count + n - self.cap
                self.r = (self.r + drop) % self.cap
                self.count -= drop
            end = self.w + n
            if end <= self.cap:
                self.buf[self.w:end] = data
            else:
                first = self.cap - self.w
                self.buf[self.w:] = data[:first]
                self.buf[:end - self.cap] = data[first:]
            self.w = end % self.cap
            self.count += n

    def read(self, n: int) -> np.ndarray:
        """Return exactly n frames; pad with silence on underrun."""
        out = np.zeros((n, 2), dtype=np.float32)
        with self.lock:
            avail = min(n, self.count)
            if avail > 0:
                end = self.r + avail
                if end <= self.cap:
                    out[:avail] = self.buf[self.r:end]
                else:
                    first = self.cap - self.r
                    out[:first] = self.buf[self.r:]
                    out[first:avail] = self.buf[:end - self.cap]
                self.r = end % self.cap
                self.count -= avail
        return out

    def clear(self) -> None:
        with self.lock:
            self.r = self.w = self.count = 0


def list_devices():
    """Return (inputs, outputs) lists of dicts: {index, name, label, hostapi}."""
    if sd is None:
        return [], []
    inputs, outputs = [], []
    hostapis = sd.query_hostapis()
    for i, d in enumerate(sd.query_devices()):
        api = hostapis[d["hostapi"]]["name"]
        label = f'{d["name"]} [{api}]'
        entry = {"index": i, "name": d["name"], "label": label, "hostapi": api}
        if d["max_input_channels"] > 0:
            inputs.append(entry)
        if d["max_output_channels"] > 0:
            outputs.append(entry)
    return inputs, outputs


def find_device_index(name: str | None, want_output: bool) -> int | None:
    """Re-match a saved device *name* against current devices. None if absent."""
    if sd is None or not name:
        return None
    ins, outs = list_devices()
    pool = outs if want_output else ins
    # exact label match first, then exact name, then prefix
    for d in pool:
        if d["label"] == name:
            return d["index"]
    for d in pool:
        if d["name"] == name:
            return d["index"]
    for d in pool:
        if d["name"].startswith(name) or name.startswith(d["name"]):
            return d["index"]
    return None


def default_output_name() -> str | None:
    """Name of the current Windows default playback device, or None."""
    if sd is None:
        return None
    try:
        return sd.query_devices(kind="output")["name"]
    except Exception:
        return None


def _pool_has(substr: str, want_output: bool) -> bool:
    ins, outs = list_devices()
    pool = outs if want_output else ins
    s = substr.lower()
    return any(s in d["name"].lower() for d in pool)


def detect_setup_issues() -> list[str]:
    """Return human-readable warnings about a misconfigured audio setup."""
    issues: list[str] = []
    if sd is None:
        return issues
    cable_present = _pool_has("CABLE Input", True) or _pool_has("CABLE Output", False)
    if not cable_present:
        issues.append(
            "VB-Audio Virtual Cable not detected. Discord can't receive your mix "
            "until you install it from vb-audio.com/Cable and reboot.")
    dn = (default_output_name() or "").lower()
    if "cable input" in dn:
        issues.append(
            "Windows default playback device is 'CABLE Input' — Discord will hear "
            "ALL your PC audio (Spotify, games, system sounds). Open Sound settings "
            "and set your speakers/headphones as the default output device.")
    return issues


class AudioEngine:
    CHANNELS = ("mic", "instrument", "pad", "master")

    def __init__(self, samplerate: int = 48000, blocksize: int = 256):
        self.sr = samplerate
        self.blocksize = blocksize
        self.synth = Synth(samplerate)
        self.soundboard = Soundboard(samplerate)
        self.voicefx = VoiceChanger(samplerate)
        self.micproc = MicProcessor(samplerate)

        # live output levels (0..1 peak) for VU meters; written on audio thread,
        # read on GUI thread. Plain float assignment is atomic enough for a meter.
        self.levels = {"mic": 0.0, "instrument": 0.0, "pad": 0.0, "master": 0.0}

        # device indices (None = unused)
        self.mic_index: int | None = None
        self.master_index: int | None = None      # what you hear
        self.secondary_index: int | None = None    # the cable -> Discord

        # mixer state
        self.vol = {"mic": 1.0, "instrument": 0.8, "pad": 0.9, "master": 0.9}
        self.mute = {c: False for c in self.CHANNELS}
        # solo applies to the source channels only (not the master bus)
        self.solo = {"mic": False, "instrument": False, "pad": False}
        self.mic_monitor = False  # mic goes to Discord but not to headphones by default

        # ring buffers (sized generously to absorb clock drift)
        self.mic_ring = RingBuffer(max(blocksize * 16, 8192))
        self.sec_ring = RingBuffer(max(blocksize * 16, 8192))

        self._streams: list = []
        self._running = False
        self._error_cb = None  # optional callback(str) for runtime errors

        # pending selections (set via configure())
        self._pending_mic: int | None = None
        self._pending_monitor: int | None = None
        self._pending_cable: int | None = None

    # ------------------------------------------------------------- mixer API
    def set_volume(self, channel: str, value: float) -> None:
        if channel in self.vol:
            self.vol[channel] = float(np.clip(value, 0.0, 2.0))

    def set_mute(self, channel: str, muted: bool) -> None:
        if channel in self.mute:
            self.mute[channel] = bool(muted)

    def set_solo(self, channel: str, soloed: bool) -> None:
        if channel in self.solo:
            self.solo[channel] = bool(soloed)

    def _g(self, channel: str) -> float:
        if self.mute[channel]:
            return 0.0
        # When any source channel is soloed, non-soloed sources are silenced.
        if channel != "master" and any(self.solo.values()) and not self.solo[channel]:
            return 0.0
        return self.vol[channel]

    @property
    def running(self) -> bool:
        return self._running

    # ----------------------------------------------------------- callbacks
    def _mic_callback(self, indata, frames, time_info, status):
        # indata: (frames, ch) float32. Convert to stereo and push.
        if indata.shape[1] == 1:
            stereo = np.repeat(indata, 2, axis=1)
        else:
            stereo = indata[:, :2]
        self.mic_ring.write(np.ascontiguousarray(stereo, dtype=np.float32))

    def _master_callback(self, outdata, frames, time_info, status):
        synth_buf = self.synth.render(frames)
        pad_buf = self.soundboard.render(frames)
        mic_buf = self.mic_ring.read(frames) if self.mic_index is not None else \
            np.zeros((frames, 2), dtype=np.float32)

        # mic chain: noise gate -> compressor -> voice changer (mono), re-spread
        if self.mic_index is not None and (self.micproc.active or self.voicefx.enabled):
            mono = np.ascontiguousarray(mic_buf[:, 0])
            mono = self.micproc.process(mono)
            mono = self.voicefx.process(mono)
            mic_buf = np.column_stack((mono, mono))

        mic_gain = self._g("mic")
        inst_buf = synth_buf * self._g("instrument")
        pad_only = pad_buf * self._g("pad")
        instruments = inst_buf + pad_only

        # Discord gets the full mic; monitor only gets it if mic_monitor is on
        discord_mix = (instruments + mic_buf * mic_gain) * self._g("master")
        np.clip(discord_mix, -1.0, 1.0, out=discord_mix)

        monitor_mic = mic_gain if self.mic_monitor else 0.0
        monitor_mix = (instruments + mic_buf * monitor_mic) * self._g("master")
        np.clip(monitor_mix, -1.0, 1.0, out=monitor_mix)

        # VU levels (peak per source, with a little decay handled GUI-side)
        self.levels["mic"] = float(np.max(np.abs(mic_buf * mic_gain))) if frames else 0.0
        self.levels["instrument"] = float(np.max(np.abs(inst_buf))) if frames else 0.0
        self.levels["pad"] = float(np.max(np.abs(pad_only))) if frames else 0.0
        self.levels["master"] = float(np.max(np.abs(discord_mix))) if frames else 0.0

        outdata[:] = monitor_mix
        if self.secondary_index is not None:
            self.sec_ring.write(discord_mix)

    def _secondary_callback(self, outdata, frames, time_info, status):
        outdata[:] = self.sec_ring.read(frames)

    # --------------------------------------------------------------- start
    def _resolve_roles(self):
        """Decide master vs secondary from monitor/cable selections."""
        monitor = self._pending_monitor
        cable = self._pending_cable
        if monitor is not None:
            self.master_index = monitor
            self.secondary_index = cable if (cable is not None and cable != monitor) else None
        elif cable is not None:
            self.master_index = cable
            self.secondary_index = None
        else:
            self.master_index = None
            self.secondary_index = None

    def configure(self, mic_index, monitor_index, cable_index,
                  samplerate=None, blocksize=None):
        self._pending_mic = mic_index
        self._pending_monitor = monitor_index
        self._pending_cable = cable_index
        if samplerate:
            self.sr = samplerate
            self.synth.sr = samplerate
            self.synth.delay.sr = samplerate
            self.voicefx.sr = samplerate
            self.micproc.sr = samplerate
            self.soundboard.sr = samplerate
        if blocksize:
            self.blocksize = blocksize

    def start(self) -> None:
        """Open and start streams. Raises RuntimeError with a clear message."""
        if sd is None:
            raise RuntimeError("sounddevice/PortAudio is not available.")
        if self._running:
            self.stop()

        self.mic_index = self._pending_mic
        self._resolve_roles()
        if self.master_index is None:
            raise RuntimeError(
                "No output device selected. Choose a monitor output and/or the "
                "virtual cable output before starting audio."
            )

        self.mic_ring.clear()
        self.sec_ring.clear()
        streams = []
        try:
            master = sd.OutputStream(
                device=self.master_index, channels=2, samplerate=self.sr,
                blocksize=self.blocksize, dtype="float32", latency="low",
                callback=self._master_callback,
            )
            streams.append(master)

            if self.secondary_index is not None:
                secondary = sd.OutputStream(
                    device=self.secondary_index, channels=2, samplerate=self.sr,
                    blocksize=self.blocksize, dtype="float32", latency="low",
                    callback=self._secondary_callback,
                )
                streams.append(secondary)

            if self.mic_index is not None:
                mic = sd.InputStream(
                    device=self.mic_index, channels=1, samplerate=self.sr,
                    blocksize=self.blocksize, dtype="float32", latency="low",
                    callback=self._mic_callback,
                )
                streams.append(mic)

            for s in streams:
                s.start()
        except Exception as e:
            for s in streams:
                try:
                    s.close()
                except Exception:
                    pass
            raise RuntimeError(f"Could not start audio: {e}") from e

        self._streams = streams
        self._running = True

    def stop(self) -> None:
        for s in self._streams:
            try:
                s.stop()
                s.close()
            except Exception:
                pass
        self._streams = []
        self._running = False
        self.synth.all_notes_off()
        self.soundboard.stop_all()
        for k in self.levels:
            self.levels[k] = 0.0
