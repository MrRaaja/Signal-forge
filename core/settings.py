"""
settings.py
-----------
Local settings persistence for MIDI Discord Mixer.

Settings are stored as a single JSON file in the per-user config directory:
    Windows : %APPDATA%\\MidiDiscordMixer\\settings.json
    Other   : ~/.config/MidiDiscordMixer/settings.json   (dev / cross-platform)

Devices are intentionally stored *by name*, not by index, because PortAudio /
Windows device indices change between reboots and when hardware is plugged in.
On load we re-match the saved name against the current device list.
"""

from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass, field, asdict
from typing import Any

from .branding import APP_NAME, LEGACY_APP_DIR_NAME


APP_DIR_NAME = APP_NAME
SETTINGS_FILE = "settings.json"


def _config_base() -> str:
    if os.name == "nt":
        return os.environ.get("APPDATA") or os.path.expanduser("~")
    return os.environ.get("XDG_CONFIG_HOME") or os.path.join(
        os.path.expanduser("~"), ".config"
    )


def config_dir() -> str:
    """Return (and create) the per-user config directory."""
    path = os.path.join(_config_base(), APP_DIR_NAME)
    os.makedirs(path, exist_ok=True)
    return path


def settings_path() -> str:
    return os.path.join(config_dir(), SETTINGS_FILE)


def _migrate_legacy_settings(new_path: str) -> None:
    """One-time copy of settings from the old app-folder name, if present."""
    if os.path.exists(new_path) or not LEGACY_APP_DIR_NAME:
        return
    old = os.path.join(_config_base(), LEGACY_APP_DIR_NAME, SETTINGS_FILE)
    if os.path.exists(old):
        try:
            shutil.copyfile(old, new_path)
        except OSError:
            pass


# Default CC numbers for the 8 knobs. These are a *best-effort guess* for the
# Akai MPK mini mkIV factory preset -- correct them with the in-app MIDI Learn
# button (watch the debug log to see the real CC numbers your knobs send).
DEFAULT_KNOB_CC = [70, 71, 72, 73, 74, 75, 76, 77]

# What each knob controls. First four match the spec; rest are reserved.
DEFAULT_KNOB_TARGET = [
    "instrument", "pad", "mic", "master",
    "none", "none", "none", "none",
]

# Default note numbers for the 8 pads (Bank A). Also a best-effort guess --
# use MIDI Learn to correct. Watch the debug log: press a pad and read the note.
DEFAULT_PAD_NOTES = [36, 37, 38, 39, 40, 41, 42, 43]


@dataclass
class PadConfig:
    file: str | None = None          # absolute path to WAV/MP3, or None
    mode: str = "oneshot"            # "oneshot" | "hold" | "toggle"
    volume: float = 1.0              # 0.0 .. 1.0
    note: int = 36                   # MIDI note that triggers this pad


@dataclass
class Settings:
    # ---- device selections (stored by name) ----
    midi_device: str | None = None
    mic_device: str | None = None
    monitor_device: str | None = None
    cable_device: str | None = None

    # ---- audio engine ----
    samplerate: int = 48000
    blocksize: int = 256
    autostart_audio: bool = True   # connect MIDI + start audio on launch
    routing_locked: bool = False   # lock the device-routing dropdowns

    # ---- instrument (synth) ----
    synth_profile: str = "Electric Piano"
    echo_enabled: bool = False
    echo_time_ms: int = 300
    echo_feedback: float = 0.35
    echo_mix: float = 0.25

    # ---- voice changer (microphone) ----
    vc_enabled: bool = False
    vc_semitones: float = 0.0
    vc_robot: bool = False

    # ---- mic dynamics ----
    gate_enabled: bool = False
    gate_threshold_db: float = -45.0
    comp_enabled: bool = False
    comp_threshold_db: float = -18.0
    comp_ratio: float = 3.0

    # ---- mixer (0..1 volumes, bool mutes) ----
    vol_mic: float = 1.0
    vol_instrument: float = 0.8
    vol_pad: float = 0.9
    vol_master: float = 0.9
    mute_mic: bool = False
    mute_instrument: bool = False
    mute_pad: bool = False
    mute_master: bool = False

    # ---- controller mapping ----
    panic_note: int | None = None   # MIDI note that stops all pads (optional)
    knob_cc: list[int] = field(default_factory=lambda: list(DEFAULT_KNOB_CC))
    knob_target: list[str] = field(default_factory=lambda: list(DEFAULT_KNOB_TARGET))
    pads: list[PadConfig] = field(
        default_factory=lambda: [PadConfig(note=n) for n in DEFAULT_PAD_NOTES]
    )

    # -------------------------------------------------- serialization
    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Settings":
        s = cls()
        for k, v in d.items():
            if k == "pads" and isinstance(v, list):
                pads = []
                for i, pd in enumerate(v):
                    if isinstance(pd, dict):
                        pads.append(PadConfig(
                            file=pd.get("file"),
                            mode=pd.get("mode", "oneshot"),
                            volume=float(pd.get("volume", 1.0)),
                            note=int(pd.get("note", DEFAULT_PAD_NOTES[i % 8])),
                        ))
                if pads:
                    s.pads = pads
            elif hasattr(s, k):
                setattr(s, k, v)
        # Defensive: guarantee 8 pads / 8 knobs
        while len(s.pads) < 8:
            s.pads.append(PadConfig(note=DEFAULT_PAD_NOTES[len(s.pads) % 8]))
        s.pads = s.pads[:8]
        if len(s.knob_cc) != 8:
            s.knob_cc = list(DEFAULT_KNOB_CC)
        if len(s.knob_target) != 8:
            s.knob_target = list(DEFAULT_KNOB_TARGET)
        return s

    def save(self, path: str | None = None) -> None:
        path = path or settings_path()
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2)
        os.replace(tmp, path)  # atomic on the same filesystem

    @classmethod
    def load(cls, path: str | None = None) -> "Settings":
        path = path or settings_path()
        _migrate_legacy_settings(path)
        if not os.path.exists(path):
            return cls()
        try:
            with open(path, "r", encoding="utf-8") as f:
                return cls.from_dict(json.load(f))
        except (json.JSONDecodeError, OSError):
            # Corrupt or unreadable -> start fresh rather than crash.
            return cls()
