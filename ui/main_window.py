"""
main_window.py
--------------
The application window. Ties together the engine, MIDI input, the widgets,
device selection, controller mapping (with MIDI learn) and settings persistence.

Threading note
==============
MIDI messages arrive on python-rtmidi's background thread. Audio-affecting calls
(synth.note_on, soundboard.trigger, engine.set_volume) are thread-safe and are
made directly from that thread for the lowest latency. Anything that touches Qt
widgets is forwarded to the GUI thread through `MidiBridge` signals (Qt delivers
cross-thread signals on the receiver's thread automatically).
"""

from __future__ import annotations

import os
import sys
import threading

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QGroupBox,
    QComboBox, QPushButton, QLabel, QPlainTextEdit, QFileDialog, QMessageBox,
    QScrollArea, QApplication, QSystemTrayIcon, QMenu
)
from PySide6.QtCore import QObject, Signal, Qt, QTime, QTimer, QProcess
from PySide6.QtGui import (
    QIcon, QPixmap, QPainter, QColor, QFont, QAction, QShortcut, QKeySequence
)

from core.branding import APP_NAME, CONTROLLER_NAME, TAGLINE, HAS_PADS_KNOBS
from core.settings import (
    Settings, DEFAULT_PAD_NOTES, DEFAULT_KNOB_CC, DEFAULT_KNOB_TARGET
)
from core.mixer import (
    AudioEngine, list_devices, find_device_index, detect_setup_issues
)
from core.midi_input import MidiInput
from .styles import STYLE
from .keyboard_widget import KeyboardWidget
from .pads_widget import PadsWidget
from .knobs_widget import KnobsWidget
from .mixer_widget import MixerWidget
from .soundboard_widget import SoundboardWidget
from .instrument_widget import InstrumentWidget
from .voice_widget import VoiceWidget
from .mic_widget import MicWidget
from .collapsible import CollapsibleBox

VOLUME_CHANNELS = {"instrument", "pad", "mic", "master"}
NONE_LABEL = "(none)"


class MidiBridge(QObject):
    """Carries events from the MIDI thread to the GUI thread."""
    keyOn = Signal(int)
    keyOff = Signal(int)
    padFlash = Signal(int)
    knobValue = Signal(int, int)        # knob index, value
    volReflect = Signal(str, float)     # channel, 0..1
    log = Signal(str)
    knobLearned = Signal(int, int)      # knob index, cc
    padLearned = Signal(int, int)       # pad index, note
    panicLearned = Signal(int)          # note bound as the STOP trigger


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME}  ·  {CONTROLLER_NAME}")
        self.resize(1180, 820)
        self.setStyleSheet(STYLE)

        self.settings = Settings.load()
        self.engine = AudioEngine(self.settings.samplerate, self.settings.blocksize)
        self.midi = MidiInput()
        self.bridge = MidiBridge()

        # routing maps (guarded; read on MIDI thread, written on GUI thread)
        self._maps_lock = threading.Lock()
        self._pad_notes = [p.note for p in self.settings.pads]       # idx -> note
        self._knob_cc = list(self.settings.knob_cc)                   # idx -> cc
        self._knob_target = list(self.settings.knob_target)           # idx -> target
        self._panic_note = self.settings.panic_note                   # STOP trigger
        self._learn = None  # None | ("knob", idx) | ("pad", idx) | ("panic", 0)

        self._really_quit = False
        self.tray = None
        # auto-audio is allowed until the user manually clicks Stop
        self._auto_audio_allowed = True

        self._build_ui()
        self._wire_signals()
        self._build_tray()
        self._apply_settings_to_engine()
        self._apply_settings_to_ui()
        self.refresh_devices()
        self.log("Ready. Select devices, then Connect MIDI and Start Audio.")
        self._start_device_watch()

    # ============================================================= UI build
    def _build_ui(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        self.setCentralWidget(scroll)

        central = QWidget()
        scroll.setWidget(central)
        root = QVBoxLayout(central)

        title = QLabel(TAGLINE)
        title.setObjectName("title")
        root.addWidget(title)

        # setup-guard banner (hidden unless there's a problem)
        self.banner = QLabel("")
        self.banner.setWordWrap(True)
        self.banner.setObjectName("banner")
        self.banner.setStyleSheet(
            "background:#3a2417;border:1px solid #c0554a;border-radius:6px;"
            "padding:8px;color:#ffd9c2;")
        self.banner.hide()
        root.addWidget(self.banner)

        # ---- top: pads (left) + knobs (right) ----
        top = QHBoxLayout()
        pads_box = CollapsibleBox("Pads", collapsed=not HAS_PADS_KNOBS)
        self.pads = PadsWidget()
        pads_box.addWidget(self.pads)
        self.stop_pads_btn = QPushButton("⏹  STOP ALL PADS  (F9)")
        self.stop_pads_btn.setToolTip("Immediately stop every playing soundboard pad")
        self.stop_pads_btn.setStyleSheet(
            "background:#c0554a;color:#fff;font-weight:700;padding:6px;")
        pads_box.addWidget(self.stop_pads_btn)
        self.learn_panic_btn = QPushButton("Bind physical STOP button…")
        self.learn_panic_btn.setToolTip(
            "Click, then hit the pad/key on your keyboard you want to use as STOP")
        pads_box.addWidget(self.learn_panic_btn)
        top.addWidget(pads_box, 1)

        knobs_box = CollapsibleBox("Knobs", collapsed=not HAS_PADS_KNOBS)
        self.knobs = KnobsWidget()
        knobs_box.addWidget(self.knobs)
        top.addWidget(knobs_box, 2)
        root.addLayout(top)

        # ---- middle: left column (devices + status) | right (mixer) ----
        mid = QHBoxLayout()

        left_col = QVBoxLayout()
        left_col.addWidget(self._build_devices_box())
        left_col.addWidget(self._build_instrument_box())
        left_col.addWidget(self._build_voice_box())
        left_col.addWidget(self._build_mic_box())
        left_col.addWidget(self._build_status_box())
        mid.addLayout(left_col, 3)

        mixer_box = CollapsibleBox("Mixer")
        self.mixer = MixerWidget()
        mixer_box.addWidget(self.mixer)
        mid.addWidget(mixer_box, 2)
        root.addLayout(mid)

        # ---- soundboard assignment ----
        sb_box = CollapsibleBox("Soundboard — pad assignments", collapsed=True)
        self.soundboard_ui = SoundboardWidget()
        sb_box.addWidget(self.soundboard_ui)
        root.addWidget(sb_box)

        # ---- keyboard ----
        kb_box = CollapsibleBox("Keyboard")
        self.keyboard = KeyboardWidget()
        kb_box.addWidget(self.keyboard)
        root.addWidget(kb_box)

        # ---- debug log ----
        log_box = CollapsibleBox("MIDI debug log", collapsed=True)
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(500)
        self.log_view.setFixedHeight(120)
        log_box.addWidget(self.log_view)
        root.addWidget(log_box)

    def _build_devices_box(self) -> CollapsibleBox:
        box = CollapsibleBox("Devices & routing", collapsed=False)
        inner = QWidget()
        g = QGridLayout(inner)

        self.midi_combo = QComboBox()
        self.mic_combo = QComboBox()
        self.monitor_combo = QComboBox()
        self.cable_combo = QComboBox()

        rows = [
            ("MIDI input", self.midi_combo),
            ("Microphone input", self.mic_combo),
            ("Monitor output (headphones)", self.monitor_combo),
            ("Virtual output (CABLE Input → Discord)", self.cable_combo),
        ]
        for r, (label, combo) in enumerate(rows):
            g.addWidget(QLabel(label), r, 0)
            g.addWidget(combo, r, 1)

        self.refresh_btn = QPushButton("Refresh devices")
        self.connect_midi_btn = QPushButton("Connect MIDI")
        self.audio_btn = QPushButton("Start Audio")
        self.reset_map_btn = QPushButton("Restore default pad/knob mapping")
        self.reset_map_btn.setToolTip(
            "Reset pad notes and knob CCs to factory defaults — use if a preset "
            "change on the controller scrambled them, then re-Learn any custom ones.")
        self.lock_routing_btn = QPushButton("🔓  Lock routing")
        self.lock_routing_btn.setCheckable(True)
        self.lock_routing_btn.setToolTip(
            "Lock the device dropdowns so they can't be changed by accident")
        self.restart_btn = QPushButton("⟳  Restart app")
        self.restart_btn.setToolTip("Relaunch SignalForge (loads any updated code)")

        g.addWidget(self.refresh_btn, 4, 0)
        g.addWidget(self.connect_midi_btn, 4, 1)
        g.addWidget(self.audio_btn, 5, 0, 1, 2)
        g.addWidget(self.reset_map_btn, 6, 0, 1, 2)
        self.tray_btn = QPushButton("🗕  Hide to tray (work mode)")
        self.tray_btn.setToolTip(
            "Hide the window to the system tray — audio keeps running so it won't "
            "disrupt you. Click the tray icon to bring it back.")
        g.addWidget(self.lock_routing_btn, 7, 0)
        g.addWidget(self.restart_btn, 7, 1)
        g.addWidget(self.tray_btn, 8, 0, 1, 2)
        box.addWidget(inner)
        return box

    def _build_instrument_box(self) -> CollapsibleBox:
        box = CollapsibleBox("Instrument & effects")
        self.instrument = InstrumentWidget()
        box.addWidget(self.instrument)
        return box

    def _build_voice_box(self) -> CollapsibleBox:
        box = CollapsibleBox("Voice changer (mic)")
        self.voice = VoiceWidget()
        box.addWidget(self.voice)
        return box

    def _build_mic_box(self) -> CollapsibleBox:
        box = CollapsibleBox("Mic processing (gate / compressor)", collapsed=True)
        self.mic_dyn = MicWidget()
        box.addWidget(self.mic_dyn)
        return box

    def _build_status_box(self) -> QGroupBox:
        box = QGroupBox("Status")
        g = QGridLayout(box)
        self.status_midi = QLabel("● MIDI: disconnected")
        self.status_mic = QLabel("● Microphone: inactive")
        self.status_out = QLabel("● Virtual output: inactive")
        for w in (self.status_midi, self.status_mic, self.status_out):
            w.setStyleSheet("color:#c0554a;")
        g.addWidget(self.status_midi, 0, 0)
        g.addWidget(self.status_mic, 1, 0)
        g.addWidget(self.status_out, 2, 0)
        return box

    # ============================================================ signal wiring
    def _wire_signals(self):
        # buttons
        self.refresh_btn.clicked.connect(self.refresh_devices)
        self.connect_midi_btn.clicked.connect(self.connect_midi)
        self.audio_btn.clicked.connect(self.toggle_audio)
        self.reset_map_btn.clicked.connect(self._restore_default_mapping)
        self.lock_routing_btn.toggled.connect(self._on_lock_routing)
        self.restart_btn.clicked.connect(self._restart_app)
        self.tray_btn.clicked.connect(self._hide_to_tray)
        self.stop_pads_btn.clicked.connect(self._panic_pads)
        self.learn_panic_btn.clicked.connect(self._start_panic_learn)

        # F9 = panic: stop all soundboard pads (works anywhere in the app)
        self._panic_shortcut = QShortcut(QKeySequence("F9"), self)
        self._panic_shortcut.setContext(Qt.ApplicationShortcut)
        self._panic_shortcut.activated.connect(self._panic_pads)

        # F6 / F7 / F8 = solo Mic / Instrument / Pads
        self._solo_shortcuts = []
        for keyseq, ch in (("F6", "mic"), ("F7", "instrument"), ("F8", "pad")):
            sc = QShortcut(QKeySequence(keyseq), self)
            sc.setContext(Qt.ApplicationShortcut)
            sc.activated.connect(lambda c=ch: self.mixer.toggle_solo(c))
            self._solo_shortcuts.append(sc)

        # device combos persist on change
        self.midi_combo.currentIndexChanged.connect(lambda _: self._save())
        self.mic_combo.currentIndexChanged.connect(lambda _: self._save())
        self.monitor_combo.currentIndexChanged.connect(lambda _: self._save())
        self.cable_combo.currentIndexChanged.connect(lambda _: self._save())

        # mixer
        self.mixer.volumeChanged.connect(self._on_volume)
        self.mixer.muteChanged.connect(self._on_mute)
        self.mixer.soloChanged.connect(self._on_solo)
        self.mixer.micMonitorChanged.connect(self._on_mic_monitor)

        # instrument & effects
        self.instrument.profileChanged.connect(self._on_profile)
        self.instrument.echoChanged.connect(self._on_echo)

        # voice changer
        self.voice.changed.connect(self._on_voice)

        # mic dynamics
        self.mic_dyn.gateChanged.connect(self._on_gate)
        self.mic_dyn.compChanged.connect(self._on_comp)

        # VU meter refresh
        self._meter_timer = QTimer(self)
        self._meter_timer.setInterval(33)   # ~30 fps
        self._meter_timer.timeout.connect(self._update_meters)
        self._meter_timer.start()

        # knobs
        self.knobs.learnRequested.connect(self._start_knob_learn)
        self.knobs.targetChanged.connect(self._on_knob_target)

        # pads (mouse audition)
        self.pads.padClicked.connect(self._audition_pad)

        # soundboard panel
        self.soundboard_ui.assignRequested.connect(self._assign_pad)
        self.soundboard_ui.clearRequested.connect(self._clear_pad)
        self.soundboard_ui.stopRequested.connect(lambda i: self.engine.soundboard.stop(i))
        self.soundboard_ui.modeChanged.connect(self._on_pad_mode)
        self.soundboard_ui.volumeChanged.connect(self._on_pad_volume)
        self.soundboard_ui.learnNoteRequested.connect(self._start_pad_learn)

        # MIDI callbacks -> direct audio + bridge signals
        self.midi.on_note_on = self._midi_note_on
        self.midi.on_note_off = self._midi_note_off
        self.midi.on_cc = self._midi_cc
        self.midi.on_pitch = self._midi_pitch
        self.midi.on_message = lambda s: self.bridge.log.emit(s)

        # bridge -> GUI slots
        self.bridge.keyOn.connect(lambda n: self.keyboard.set_note(n, True))
        self.bridge.keyOff.connect(lambda n: self.keyboard.set_note(n, False))
        self.bridge.padFlash.connect(self.pads.flash)
        self.bridge.knobValue.connect(self.knobs.set_value)
        self.bridge.volReflect.connect(self.mixer.set_volume)
        self.bridge.log.connect(self._log_line)
        self.bridge.knobLearned.connect(self._on_knob_learned)
        self.bridge.padLearned.connect(self._on_pad_learned)
        self.bridge.panicLearned.connect(self._on_panic_learned)

    # ============================================================ MIDI handlers
    # (these run on the rtmidi thread)
    def _midi_note_on(self, note: int, vel: int):
        with self._maps_lock:
            learn = self._learn
            if learn and learn[0] == "panic":
                self._panic_note = note
                self._learn = None
                self.bridge.panicLearned.emit(note)
                return
            if learn and learn[0] == "pad":
                idx = learn[1]
                self._pad_notes[idx] = note
                self._learn = None
                self.bridge.padLearned.emit(idx, note)
                return
            panic_note = self._panic_note
            pad_idx = self._pad_notes.index(note) if note in self._pad_notes else None
        # A bound STOP key always stops the soundboard and plays nothing else.
        if panic_note is not None and note == panic_note:
            self.engine.soundboard.stop_all()
            self.bridge.log.emit("All pads stopped (physical STOP).")
            return
        # Only let a pad claim the note if it actually has a sample loaded;
        # otherwise the note falls through to the synth (fixes low keyboard keys
        # whose note numbers overlap the default pad notes 36-43).
        if pad_idx is not None and self.engine.soundboard.has_sample(pad_idx):
            self.engine.soundboard.trigger(pad_idx)
            self.bridge.padFlash.emit(pad_idx)
        else:
            self.engine.synth.note_on(note, vel)
            self.bridge.keyOn.emit(note)

    def _midi_note_off(self, note: int):
        with self._maps_lock:
            panic_note = self._panic_note
            pad_idx = self._pad_notes.index(note) if note in self._pad_notes else None
        if panic_note is not None and note == panic_note:
            return
        if pad_idx is not None and self.engine.soundboard.has_sample(pad_idx):
            self.engine.soundboard.release(pad_idx)
        else:
            self.engine.synth.note_off(note)
            self.bridge.keyOff.emit(note)

    def _midi_pitch(self, value: int):
        # Pitch bend wheel -> bend all sounding notes (runs on MIDI thread).
        self.engine.synth.set_pitch_bend(value)

    def _midi_cc(self, cc: int, value: int):
        # Learn captures ANY incoming CC first -- even CC 1/64 -- so a knob that
        # happens to send those can still be bound.
        with self._maps_lock:
            learn = self._learn
            if learn and learn[0] == "knob":
                idx = learn[1]
                self._knob_cc[idx] = cc
                self._learn = None
                self.bridge.knobLearned.emit(idx, cc)
                return
            knob_idx = self._knob_cc.index(cc) if cc in self._knob_cc else None
            target = self._knob_target[knob_idx] if knob_idx is not None else None

        # Reserved performance controllers (only when not mapped to a knob):
        if knob_idx is None:
            if cc == 1:                   # modulation wheel -> vibrato
                self.engine.synth.set_mod(value / 127.0)
                return
            if cc == 64:                  # sustain pedal
                self.engine.synth.set_sustain(value >= 64)
                return
        if knob_idx is not None:
            self.bridge.knobValue.emit(knob_idx, value)
            if target in VOLUME_CHANNELS:
                v = value / 127.0
                self.engine.set_volume(target, v)
                self.bridge.volReflect.emit(target, v)

    # ============================================================ GUI slots
    def _log_line(self, text: str):
        ts = QTime.currentTime().toString("HH:mm:ss.zzz")
        self.log_view.appendPlainText(f"[{ts}] {text}")

    def log(self, text: str):
        self._log_line(text)

    def _on_volume(self, channel: str, v: float):
        self.engine.set_volume(channel, v)
        setattr(self.settings, f"vol_{channel}", v)
        self._save()

    def _on_mic_monitor(self, enabled: bool):
        self.engine.mic_monitor = enabled

    def _on_profile(self, name: str):
        self.engine.synth.set_profile(name)
        self.settings.synth_profile = name
        self._save()
        self.log(f"Instrument profile: {name}")

    def _on_echo(self, enabled: bool, time_ms: float, feedback: float, mix: float):
        self.engine.synth.set_echo(enabled, time_ms, feedback, mix)
        self.settings.echo_enabled = bool(enabled)
        self.settings.echo_time_ms = int(time_ms)
        self.settings.echo_feedback = float(feedback)
        self.settings.echo_mix = float(mix)
        self._save()

    def _on_voice(self, enabled: bool, semitones: float, robot: bool):
        self.engine.voicefx.set_params(enabled, semitones, robot)
        self.settings.vc_enabled = bool(enabled)
        self.settings.vc_semitones = float(semitones)
        self.settings.vc_robot = bool(robot)
        self._save()

    def _on_gate(self, enabled: bool, threshold_db: float):
        self.engine.micproc.set_gate(enabled, threshold_db)
        self.settings.gate_enabled = bool(enabled)
        self.settings.gate_threshold_db = float(threshold_db)
        self._save()

    def _on_comp(self, enabled: bool, threshold_db: float, ratio: float):
        self.engine.micproc.set_comp(enabled, threshold_db, ratio)
        self.settings.comp_enabled = bool(enabled)
        self.settings.comp_threshold_db = float(threshold_db)
        self.settings.comp_ratio = float(ratio)
        self._save()

    def _update_meters(self):
        lv = self.engine.levels
        for ch in ("mic", "instrument", "pad", "master"):
            self.mixer.set_level(ch, lv.get(ch, 0.0))

    def _refresh_banner(self):
        issues = detect_setup_issues()
        if issues:
            self.banner.setText("⚠  " + "\n\n⚠  ".join(issues))
            self.banner.show()
        else:
            self.banner.hide()

    def _on_solo(self, channel: str, soloed: bool):
        self.engine.set_solo(channel, soloed)
        active = [c.upper() for c in ("mic", "instrument", "pad")
                  if self.engine.solo.get(c)]
        self.log("Solo: " + (", ".join(active) if active else "off"))

    def _on_mute(self, channel: str, muted: bool):
        self.engine.set_mute(channel, muted)
        setattr(self.settings, f"mute_{channel}", muted)
        self._save()

    def _on_knob_target(self, idx: int, target: str):
        with self._maps_lock:
            self._knob_target[idx] = target
        self.settings.knob_target[idx] = target
        self._save()

    def _start_knob_learn(self, idx: int):
        with self._maps_lock:
            self._learn = ("knob", idx)
        for i in range(8):                       # clear any previous highlight
            self.knobs.set_learning(i, i == idx)
        self.log(f"Learning knob K{idx + 1}: turn the physical knob now… "
                 f"(then set its target dropdown if needed)")

    def _on_knob_learned(self, idx: int, cc: int):
        self.knobs.set_learning(idx, False)
        self.knobs.set_cc(idx, cc)
        self.settings.knob_cc[idx] = cc
        self._save()
        tgt = self._knob_target[idx]
        extra = "" if tgt in VOLUME_CHANNELS else "  (set its target to hear an effect)"
        self.log(f"Knob K{idx + 1} bound to CC {cc} → {tgt}.{extra}")

    def _start_pad_learn(self, idx: int):
        with self._maps_lock:
            self._learn = ("pad", idx)
        self.log(f"Learning Pad {idx + 1}: hit the physical pad now…")

    def _on_pad_learned(self, idx: int, note: int):
        self.soundboard_ui.set_note(idx, note)
        self.settings.pads[idx].note = note
        self._save()
        self.log(f"Pad {idx + 1} bound to note {note}.")

    def _panic_pads(self):
        self.engine.soundboard.stop_all()
        self.log("All pads stopped (panic).")

    def _start_panic_learn(self):
        with self._maps_lock:
            self._learn = ("panic", 0)
        self.log("Learning STOP button: hit the pad/key you want to use as STOP…")

    def _on_panic_learned(self, note: int):
        self.settings.panic_note = note
        self._save()
        self.learn_panic_btn.setText(f"STOP button = note {note}  (rebind…)")
        self.log(f"Physical STOP button bound to note {note}.")

    def _audition_pad(self, idx: int):
        self.engine.soundboard.trigger(idx)
        self.pads.flash(idx)

    def _assign_pad(self, idx: int):
        path, _ = QFileDialog.getOpenFileName(
            self, f"Assign sample to Pad {idx + 1}",
            "", "Audio files (*.wav *.mp3 *.flac *.ogg);;All files (*)")
        if not path:
            return
        try:
            self.engine.soundboard.assign(idx, path)
        except Exception as e:
            QMessageBox.warning(self, "Could not load sample",
                                f"Failed to load:\n{path}\n\n{e}")
            self.log(f"Pad {idx + 1} load FAILED: {e}")
            return
        self.settings.pads[idx].file = path
        self.soundboard_ui.set_file(idx, path)
        self.pads.set_label(idx, os.path.basename(path))
        self._save()
        self.log(f"Pad {idx + 1} <- {os.path.basename(path)}")

    def _clear_pad(self, idx: int):
        self.engine.soundboard.clear(idx)
        self.settings.pads[idx].file = None
        self.soundboard_ui.set_file(idx, None)
        self.pads.set_label(idx, "")
        self._save()

    def _on_pad_mode(self, idx: int, mode: str):
        self.engine.soundboard.set_mode(idx, mode)
        self.settings.pads[idx].mode = mode
        self._save()

    def _on_pad_volume(self, idx: int, v: float):
        self.engine.soundboard.set_volume(idx, v)
        self.settings.pads[idx].volume = v
        self._save()

    # ============================================================ devices
    def refresh_devices(self):
        inputs, outputs = list_devices()
        midi_inputs = MidiInput.list_inputs()

        def fill(combo, items, allow_none, current_name):
            combo.blockSignals(True)
            combo.clear()
            if allow_none:
                combo.addItem(NONE_LABEL)
            for it in items:
                combo.addItem(it)
            # restore previous selection by name if present
            if current_name:
                i = combo.findText(current_name)
                if i >= 0:
                    combo.setCurrentIndex(i)
            combo.blockSignals(False)

        fill(self.midi_combo, midi_inputs, True, self.settings.midi_device)
        fill(self.mic_combo, [d["label"] for d in inputs], True, self.settings.mic_device)
        fill(self.monitor_combo, [d["label"] for d in outputs], True, self.settings.monitor_device)
        fill(self.cable_combo, [d["label"] for d in outputs], True, self.settings.cable_device)
        self.log(f"Devices refreshed: {len(midi_inputs)} MIDI in, "
                 f"{len(inputs)} audio in, {len(outputs)} audio out.")
        self._refresh_banner()

    def _combo_value(self, combo: QComboBox) -> str | None:
        t = combo.currentText()
        return None if (t == NONE_LABEL or t == "") else t

    def connect_midi(self):
        name = self._combo_value(self.midi_combo)
        if not name:
            QMessageBox.information(self, "No MIDI device", "Select a MIDI input first.")
            return
        try:
            self.midi.open(name)
        except Exception as e:
            QMessageBox.warning(self, "MIDI error", str(e))
            self.log(f"MIDI connect FAILED: {e}")
            return
        self.settings.midi_device = name
        self._save()
        self.status_midi.setText("● MIDI: connected")
        self.status_midi.setStyleSheet("color:#6fcf6f;")
        self.log(f"MIDI connected: {name}")

    def _restore_default_mapping(self):
        """Reset pad notes + knob CCs/targets to factory defaults."""
        with self._maps_lock:
            self._pad_notes = list(DEFAULT_PAD_NOTES)
            self._knob_cc = list(DEFAULT_KNOB_CC)
            self._knob_target = list(DEFAULT_KNOB_TARGET)
            self._learn = None
        for i in range(8):
            self.settings.pads[i].note = DEFAULT_PAD_NOTES[i]
            self.settings.knob_cc[i] = DEFAULT_KNOB_CC[i]
            self.settings.knob_target[i] = DEFAULT_KNOB_TARGET[i]
            self.soundboard_ui.set_note(i, DEFAULT_PAD_NOTES[i])
            self.knobs.set_cc(i, DEFAULT_KNOB_CC[i])
            self.knobs.set_target(i, DEFAULT_KNOB_TARGET[i])
        self._save()
        self.log("Mapping reset to defaults (pads 36-43, knobs CC 70-77). "
                 "Use Learn to rebind any that differ on your controller.")

    def _on_lock_routing(self, locked: bool):
        for combo in (self.midi_combo, self.mic_combo,
                      self.monitor_combo, self.cable_combo):
            combo.setEnabled(not locked)
        self.lock_routing_btn.setText("🔒  Routing locked" if locked else "🔓  Lock routing")
        self.settings.routing_locked = bool(locked)
        self._save()

    # ============================================================ system tray
    def _make_icon(self) -> QIcon:
        pm = QPixmap(64, 64)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        p.setBrush(QColor("#ff5a36"))
        p.setPen(Qt.NoPen)
        p.drawRoundedRect(4, 4, 56, 56, 14, 14)
        p.setPen(QColor("#111"))
        p.setFont(QFont("Arial", 30, QFont.Bold))
        p.drawText(pm.rect(), Qt.AlignCenter, "S")
        p.end()
        return QIcon(pm)

    def _build_tray(self):
        icon = self._make_icon()
        self.setWindowIcon(icon)
        if not QSystemTrayIcon.isSystemTrayAvailable():
            self.tray = None
            return
        self.tray = QSystemTrayIcon(icon, self)
        self.tray.setToolTip(f"{APP_NAME} — {CONTROLLER_NAME}")
        menu = QMenu()
        act_show = QAction("Show SignalForge", self)
        act_show.triggered.connect(self._show_from_tray)
        act_hide = QAction("Hide (work mode)", self)
        act_hide.triggered.connect(self._hide_to_tray)
        act_quit = QAction("Quit SignalForge", self)
        act_quit.triggered.connect(self._quit_app)
        menu.addAction(act_show)
        menu.addAction(act_hide)
        menu.addSeparator()
        menu.addAction(act_quit)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._tray_activated)
        self.tray.show()

    def _tray_activated(self, reason):
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            if self.isVisible():
                self._hide_to_tray()
            else:
                self._show_from_tray()

    def _show_from_tray(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _hide_to_tray(self):
        if self.tray is None:
            self.showMinimized()
            return
        self.hide()
        self.tray.showMessage(
            "SignalForge", "Still running — audio continues. "
            "Click the tray icon to bring it back.",
            self._make_icon(), 3000)

    def _quit_app(self):
        self._really_quit = True
        self.close()

    def _restart_app(self):
        if QMessageBox.question(
                self, "Restart SignalForge",
                "Restart the app now? Audio will stop briefly.") != QMessageBox.Yes:
            return
        self.log("Restarting…")
        try:
            self.engine.stop()
            self.midi.close()
            self._save()
        except Exception:
            pass
        script = os.path.abspath(sys.argv[0])
        QProcess.startDetached(sys.executable, [script], os.path.dirname(script))
        QApplication.quit()

    _WATCH_INTERVAL_MS = 3000   # how often to poll for device hot-plug

    def _start_device_watch(self):
        """Persistent watcher: connects MIDI / starts audio whenever the saved
        devices appear, and stops cleanly if they vanish. Designed for a laptop
        where the MPK / Focusrite are only plugged in some of the time."""
        self._watch_timer = QTimer(self)
        self._watch_timer.setInterval(self._WATCH_INTERVAL_MS)
        self._watch_timer.timeout.connect(self._watch_devices)
        self._watch_timer.start()
        self._watch_devices()   # run once immediately

    def _connect_midi_silent(self) -> None:
        """Open the saved MIDI port without modal popups (used by the watcher)."""
        name = self._combo_value(self.midi_combo)
        if not name or self.midi.is_open:
            return
        try:
            self.midi.open(name)
            self.settings.midi_device = name
            self.status_midi.setText("● MIDI: connected")
            self.status_midi.setStyleSheet("color:#6fcf6f;")
            self.log(f"MIDI connected: {name}")
        except Exception as e:
            self.log(f"Auto-connect MIDI failed (will retry): {e}")

    def _midi_device_present(self) -> bool:
        name = self.settings.midi_device
        if not name:
            return False
        for n in MidiInput.list_inputs():
            if n == name or n.startswith(name) or name.startswith(n):
                return True
        return False

    def _watch_devices(self):
        # --- MIDI hot-plug ---
        if self.settings.midi_device:
            present = self._midi_device_present()
            if self.midi.is_open and not present:
                self.midi.close()
                self.status_midi.setText("● MIDI: disconnected")
                self.status_midi.setStyleSheet("color:#c0554a;")
                self.log("MIDI device disconnected.")
            elif not self.midi.is_open and present:
                self.refresh_devices()       # repopulate combo with the new device
                self._connect_midi_silent()

        mon_idx = find_device_index(self.settings.monitor_device, want_output=True)
        cab_idx = find_device_index(self.settings.cable_device, want_output=True)

        # --- audio already running: stop if its output(s) were unplugged ---
        if self.engine.running:
            if self.settings.monitor_device and mon_idx is None and cab_idx is None:
                self.engine.stop()
                self._stop_audio_ui()
                self.log("Output device disconnected — audio stopped "
                         "(will auto-start when it returns).")
            return

        # --- audio not running: start when the gear is back ---
        if not (self.settings.autostart_audio and self._auto_audio_allowed):
            return
        # Require the monitor (e.g. Focusrite) if one is configured, so we don't
        # start a useless cable-only session while you're working without it.
        if self.settings.monitor_device:
            ready = mon_idx is not None
        else:
            ready = cab_idx is not None
        if ready:
            self.refresh_devices()           # restore combo selections
            if self._do_start_audio(silent=True):
                self.log("Devices detected — audio auto-started.")

    def toggle_audio(self):
        if self.engine.running:
            # Manual stop -> remember the user's intent so the watcher won't
            # immediately auto-start it again.
            self._auto_audio_allowed = False
            self.engine.stop()
            self._stop_audio_ui()
            self.log("Audio stopped.")
        else:
            self._auto_audio_allowed = True
            self._do_start_audio(silent=False)

    def _stop_audio_ui(self):
        self.audio_btn.setText("Start Audio")
        self.status_mic.setText("● Microphone: inactive")
        self.status_mic.setStyleSheet("color:#c0554a;")
        self.status_out.setText("● Virtual output: inactive")
        self.status_out.setStyleSheet("color:#c0554a;")

    def _do_start_audio(self, silent: bool) -> bool:
        """Start the engine from the current selections. Returns True on success.
        `silent` suppresses the modal error box (used by the auto watcher)."""
        mic_name = self._combo_value(self.mic_combo)
        mon_name = self._combo_value(self.monitor_combo)
        cab_name = self._combo_value(self.cable_combo)

        mic_idx = find_device_index(mic_name, want_output=False)
        mon_idx = find_device_index(mon_name, want_output=True)
        cab_idx = find_device_index(cab_name, want_output=True)

        self.engine.configure(mic_idx, mon_idx, cab_idx,
                              self.settings.samplerate, self.settings.blocksize)
        try:
            self.engine.start()
        except Exception as e:
            if not silent:
                QMessageBox.warning(self, "Audio error", str(e))
            self.log(f"Audio start FAILED: {e}")
            return False

        # persist names
        self.settings.mic_device = mic_name
        self.settings.monitor_device = mon_name
        self.settings.cable_device = cab_name
        self._save()

        self.audio_btn.setText("Stop Audio")
        if mic_idx is not None:
            self.status_mic.setText("● Microphone: active")
            self.status_mic.setStyleSheet("color:#6fcf6f;")
        if self.engine.secondary_index is not None or cab_idx is not None:
            self.status_out.setText("● Virtual output: active")
            self.status_out.setStyleSheet("color:#6fcf6f;")
        self.log(f"Audio started (sr={self.engine.sr}, block={self.engine.blocksize}).")
        return True

    # ============================================================ settings glue
    def _apply_settings_to_engine(self):
        for ch in ("mic", "instrument", "pad", "master"):
            self.engine.set_volume(ch, getattr(self.settings, f"vol_{ch}"))
            self.engine.set_mute(ch, getattr(self.settings, f"mute_{ch}"))
        self.engine.synth.set_profile(self.settings.synth_profile)
        self.engine.synth.set_echo(
            self.settings.echo_enabled, self.settings.echo_time_ms,
            self.settings.echo_feedback, self.settings.echo_mix)
        self.engine.voicefx.set_params(
            self.settings.vc_enabled, self.settings.vc_semitones,
            self.settings.vc_robot)
        self.engine.micproc.set_gate(
            self.settings.gate_enabled, self.settings.gate_threshold_db)
        self.engine.micproc.set_comp(
            self.settings.comp_enabled, self.settings.comp_threshold_db,
            self.settings.comp_ratio)
        for i, pad in enumerate(self.settings.pads):
            self.engine.soundboard.set_mode(i, pad.mode)
            self.engine.soundboard.set_volume(i, pad.volume)
            if pad.file and os.path.exists(pad.file):
                try:
                    self.engine.soundboard.assign(i, pad.file)
                except Exception as e:
                    self.log(f"Pad {i + 1} sample missing/unreadable: {e}")

    def _apply_settings_to_ui(self):
        for ch in ("mic", "instrument", "pad", "master"):
            self.mixer.set_volume(ch, getattr(self.settings, f"vol_{ch}"))
            self.mixer.set_mute(ch, getattr(self.settings, f"mute_{ch}"))
        for i, pad in enumerate(self.settings.pads):
            self.soundboard_ui.set_file(i, pad.file)
            self.soundboard_ui.set_mode(i, pad.mode)
            self.soundboard_ui.set_volume(i, pad.volume)
            self.soundboard_ui.set_note(i, pad.note)
            self.pads.set_label(i, os.path.basename(pad.file) if pad.file else "")
        for i in range(8):
            self.knobs.set_cc(i, self.settings.knob_cc[i])
            self.knobs.set_target(i, self.settings.knob_target[i])
        self.instrument.set_profile(self.settings.synth_profile)
        self.instrument.set_echo(
            self.settings.echo_enabled, self.settings.echo_time_ms,
            self.settings.echo_feedback, self.settings.echo_mix)
        self.voice.set_state(
            self.settings.vc_enabled, self.settings.vc_semitones,
            self.settings.vc_robot)
        self.mic_dyn.set_state(
            self.settings.gate_enabled, self.settings.gate_threshold_db,
            self.settings.comp_enabled, self.settings.comp_threshold_db,
            self.settings.comp_ratio)
        if self.settings.panic_note is not None:
            self.learn_panic_btn.setText(
                f"STOP button = note {self.settings.panic_note}  (rebind…)")
        if self.settings.routing_locked:
            self.lock_routing_btn.setChecked(True)   # triggers _on_lock_routing

    def _save(self):
        try:
            self.settings.save()
        except Exception as e:
            self.log(f"Settings save failed: {e}")

    def closeEvent(self, event):
        # Closing the window (X) hides to tray instead of quitting, so audio
        # keeps running while you work. Quit for real via the tray menu.
        if not self._really_quit and self.tray is not None:
            event.ignore()
            self._hide_to_tray()
            return
        try:
            if self.tray is not None:
                self.tray.hide()
            self.engine.stop()
            self.midi.close()
            self._save()
        finally:
            super().closeEvent(event)
