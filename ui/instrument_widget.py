"""
instrument_widget.py
---------------------
Keyboard instrument controls: timbre profile + echo (delay) effect.

Signals:
  profileChanged(name)
  echoChanged(enabled, time_ms, feedback, mix)
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QWidget, QGridLayout, QHBoxLayout, QLabel, QComboBox, QCheckBox, QSlider
)
from PySide6.QtCore import Qt, Signal

from core.synth import PROFILES


class InstrumentWidget(QWidget):
    profileChanged = Signal(str)
    echoChanged = Signal(bool, float, float, float)  # enabled, time_ms, fb, mix

    def __init__(self, parent=None):
        super().__init__(parent)
        g = QGridLayout(self)
        g.setHorizontalSpacing(10)
        g.setVerticalSpacing(6)

        # ---- profile ----
        g.addWidget(QLabel("Profile"), 0, 0)
        self.profile_combo = QComboBox()
        self.profile_combo.addItems(list(PROFILES.keys()))
        self.profile_combo.currentTextChanged.connect(self.profileChanged)
        g.addWidget(self.profile_combo, 0, 1, 1, 2)

        # ---- echo enable ----
        self.echo_chk = QCheckBox("Echo")
        self.echo_chk.toggled.connect(self._emit_echo)
        g.addWidget(self.echo_chk, 1, 0)

        # ---- echo time ----
        g.addWidget(QLabel("Time"), 2, 0)
        self.time_slider = QSlider(Qt.Horizontal)
        self.time_slider.setRange(50, 1000)       # ms
        self.time_slider.setValue(300)
        self.time_slider.valueChanged.connect(self._emit_echo)
        self.time_lbl = QLabel("300 ms")
        self.time_lbl.setStyleSheet("color:#7f8896;font-size:10px;")
        g.addWidget(self.time_slider, 2, 1)
        g.addWidget(self.time_lbl, 2, 2)

        # ---- echo feedback ----
        g.addWidget(QLabel("Feedback"), 3, 0)
        self.fb_slider = QSlider(Qt.Horizontal)
        self.fb_slider.setRange(0, 95)            # %
        self.fb_slider.setValue(35)
        self.fb_slider.valueChanged.connect(self._emit_echo)
        self.fb_lbl = QLabel("35%")
        self.fb_lbl.setStyleSheet("color:#7f8896;font-size:10px;")
        g.addWidget(self.fb_slider, 3, 1)
        g.addWidget(self.fb_lbl, 3, 2)

        # ---- echo mix ----
        g.addWidget(QLabel("Mix"), 4, 0)
        self.mix_slider = QSlider(Qt.Horizontal)
        self.mix_slider.setRange(0, 100)          # %
        self.mix_slider.setValue(25)
        self.mix_slider.valueChanged.connect(self._emit_echo)
        self.mix_lbl = QLabel("25%")
        self.mix_lbl.setStyleSheet("color:#7f8896;font-size:10px;")
        g.addWidget(self.mix_slider, 4, 1)
        g.addWidget(self.mix_lbl, 4, 2)

    # ------------------------------------------------------------- helpers
    def _emit_echo(self, *_):
        t = self.time_slider.value()
        fb = self.fb_slider.value()
        mix = self.mix_slider.value()
        self.time_lbl.setText(f"{t} ms")
        self.fb_lbl.setText(f"{fb}%")
        self.mix_lbl.setText(f"{mix}%")
        self.echoChanged.emit(self.echo_chk.isChecked(), float(t),
                              fb / 100.0, mix / 100.0)

    # ------------------------------------------------------------- setters
    def set_profile(self, name: str):
        self.profile_combo.blockSignals(True)
        self.profile_combo.setCurrentText(name)
        self.profile_combo.blockSignals(False)

    def set_echo(self, enabled: bool, time_ms: int, feedback: float, mix: float):
        for w in (self.echo_chk, self.time_slider, self.fb_slider, self.mix_slider):
            w.blockSignals(True)
        self.echo_chk.setChecked(enabled)
        self.time_slider.setValue(int(time_ms))
        self.fb_slider.setValue(int(round(feedback * 100)))
        self.mix_slider.setValue(int(round(mix * 100)))
        for w in (self.echo_chk, self.time_slider, self.fb_slider, self.mix_slider):
            w.blockSignals(False)
        self.time_lbl.setText(f"{int(time_ms)} ms")
        self.fb_lbl.setText(f"{int(round(feedback * 100))}%")
        self.mix_lbl.setText(f"{int(round(mix * 100))}%")
