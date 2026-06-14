"""
voice_widget.py
---------------
Microphone voice-changer controls: enable, pitch (semitones), robot, presets.

Signal:
  changed(enabled, semitones, robot)
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QWidget, QGridLayout, QHBoxLayout, QLabel, QCheckBox, QSlider, QPushButton
)
from PySide6.QtCore import Qt, Signal

# (label, semitones) quick presets
PRESETS = [
    ("Deep", -5),
    ("Normal", 0),
    ("Chipmunk", 7),
]


class VoiceWidget(QWidget):
    changed = Signal(bool, float, bool)   # enabled, semitones, robot

    def __init__(self, parent=None):
        super().__init__(parent)
        g = QGridLayout(self)
        g.setHorizontalSpacing(10)
        g.setVerticalSpacing(6)

        self.enable_chk = QCheckBox("Enable voice changer")
        self.enable_chk.toggled.connect(self._emit)
        g.addWidget(self.enable_chk, 0, 0, 1, 3)

        g.addWidget(QLabel("Pitch"), 1, 0)
        self.pitch_slider = QSlider(Qt.Horizontal)
        self.pitch_slider.setRange(-12, 12)       # semitones
        self.pitch_slider.setValue(0)
        self.pitch_slider.setTickPosition(QSlider.TicksBelow)
        self.pitch_slider.setTickInterval(6)
        self.pitch_slider.valueChanged.connect(self._emit)
        self.pitch_lbl = QLabel("0 st")
        self.pitch_lbl.setStyleSheet("color:#7f8896;font-size:10px;")
        g.addWidget(self.pitch_slider, 1, 1)
        g.addWidget(self.pitch_lbl, 1, 2)

        self.robot_chk = QCheckBox("Robot")
        self.robot_chk.toggled.connect(self._emit)
        g.addWidget(self.robot_chk, 2, 0)

        # preset buttons
        preset_row = QHBoxLayout()
        for label, semis in PRESETS:
            btn = QPushButton(label)
            btn.setFixedHeight(22)
            btn.clicked.connect(lambda _=False, s=semis: self._apply_preset(s))
            preset_row.addWidget(btn)
        holder = QWidget()
        holder.setLayout(preset_row)
        g.addWidget(holder, 3, 0, 1, 3)

    # ------------------------------------------------------------- helpers
    def _apply_preset(self, semis: int):
        self.enable_chk.setChecked(True)
        self.pitch_slider.setValue(semis)   # triggers _emit

    def _emit(self, *_):
        semis = self.pitch_slider.value()
        self.pitch_lbl.setText(f"{semis:+d} st")
        self.changed.emit(self.enable_chk.isChecked(), float(semis),
                          self.robot_chk.isChecked())

    def set_state(self, enabled: bool, semitones: float, robot: bool):
        for w in (self.enable_chk, self.pitch_slider, self.robot_chk):
            w.blockSignals(True)
        self.enable_chk.setChecked(enabled)
        self.pitch_slider.setValue(int(round(semitones)))
        self.robot_chk.setChecked(robot)
        for w in (self.enable_chk, self.pitch_slider, self.robot_chk):
            w.blockSignals(False)
        self.pitch_lbl.setText(f"{int(round(semitones)):+d} st")
