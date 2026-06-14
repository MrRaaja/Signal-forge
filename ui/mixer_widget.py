"""
mixer_widget.py
---------------
Four vertical faders (Mic / Instrument / Pads / Master) each with a mute toggle.

Signals:
  volumeChanged(channel, value0to1)
  muteChanged(channel, bool)
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QSlider, QLabel, QPushButton
)
from PySide6.QtGui import QPainter, QColor
from PySide6.QtCore import Qt, Signal, QRectF

CHANNELS = [("mic", "MIC"), ("instrument", "INST"), ("pad", "PADS"), ("master", "MASTER")]


class _Meter(QWidget):
    """Thin vertical VU meter with smooth decay."""

    def __init__(self):
        super().__init__()
        self.setFixedWidth(8)
        self.setMinimumHeight(140)
        self._level = 0.0

    def set_level(self, v: float):
        v = max(0.0, min(1.0, float(v)))
        # fast attack, slow release
        self._level = v if v > self._level else self._level * 0.82
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        h = self.height()
        w = self.width()
        p.fillRect(self.rect(), QColor("#0f1113"))
        fill = int(h * self._level)
        if fill > 0:
            if self._level < 0.6:
                col = QColor("#6fcf6f")
            elif self._level < 0.85:
                col = QColor("#e3c84a")
            else:
                col = QColor("#ff5a36")
            p.fillRect(QRectF(0, h - fill, w, fill), col)
        p.end()


class _ChannelStrip(QWidget):
    volumeChanged = Signal(str, float)
    muteChanged = Signal(str, bool)
    monitorChanged = Signal(bool)  # only emitted by the mic strip

    def __init__(self, key: str, label: str):
        super().__init__()
        self.key = key
        lay = QVBoxLayout(self)
        lay.setAlignment(Qt.AlignHCenter)

        name = QLabel(label)
        name.setAlignment(Qt.AlignCenter)

        self.slider = QSlider(Qt.Vertical)
        self.slider.setRange(0, 100)
        self.slider.setValue(80)
        self.slider.setMinimumHeight(140)
        self.slider.valueChanged.connect(
            lambda v: self.volumeChanged.emit(self.key, v / 100.0))

        self.value_lbl = QLabel("80")
        self.value_lbl.setAlignment(Qt.AlignCenter)
        self.value_lbl.setStyleSheet("color:#7f8896;font-size:10px;")
        self.slider.valueChanged.connect(lambda v: self.value_lbl.setText(str(v)))

        self.meter = _Meter()

        self.mute_btn = QPushButton("MUTE")
        self.mute_btn.setCheckable(True)
        self.mute_btn.setFixedHeight(24)
        self.mute_btn.toggled.connect(self._on_mute)

        slider_row = QHBoxLayout()
        slider_row.setSpacing(4)
        slider_row.setAlignment(Qt.AlignHCenter)
        slider_row.addWidget(self.slider)
        slider_row.addWidget(self.meter)

        lay.addWidget(name)
        lay.addLayout(slider_row)
        lay.addWidget(self.value_lbl)
        lay.addWidget(self.mute_btn)

        # Monitor toggle — only shown for the mic strip
        if key == "mic":
            self.mon_btn = QPushButton("MON OFF")
            self.mon_btn.setCheckable(True)
            self.mon_btn.setChecked(False)
            self.mon_btn.setFixedHeight(24)
            self.mon_btn.setToolTip("Hear your mic in headphones (Discord always gets it)")
            self.mon_btn.toggled.connect(self._on_monitor)
            self.mon_btn.setStyleSheet("background:#555;color:#aaa;")
            lay.addWidget(self.mon_btn)
        else:
            self.mon_btn = None

    def _on_mute(self, checked: bool):
        self.mute_btn.setText("MUTED" if checked else "MUTE")
        self.mute_btn.setStyleSheet(
            "background:#ff5a36;color:#111;font-weight:700;" if checked else "")
        self.muteChanged.emit(self.key, checked)

    def _on_monitor(self, checked: bool):
        self.mon_btn.setText("MON ON" if checked else "MON OFF")
        self.mon_btn.setStyleSheet(
            "" if checked else "background:#555;color:#aaa;")
        self.monitorChanged.emit(checked)

    def set_volume(self, v0to1: float):
        self.slider.blockSignals(True)
        self.slider.setValue(int(round(v0to1 * 100)))
        self.value_lbl.setText(str(int(round(v0to1 * 100))))
        self.slider.blockSignals(False)

    def set_mute(self, muted: bool):
        self.mute_btn.setChecked(muted)


class MixerWidget(QWidget):
    volumeChanged = Signal(str, float)
    muteChanged = Signal(str, bool)
    micMonitorChanged = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setSpacing(10)
        self.strips: dict[str, _ChannelStrip] = {}
        for key, label in CHANNELS:
            strip = _ChannelStrip(key, label)
            strip.volumeChanged.connect(self.volumeChanged)
            strip.muteChanged.connect(self.muteChanged)
            if key == "mic":
                strip.monitorChanged.connect(self.micMonitorChanged)
            self.strips[key] = strip
            lay.addWidget(strip)

    def set_volume(self, channel: str, v0to1: float):
        if channel in self.strips:
            self.strips[channel].set_volume(v0to1)

    def set_mute(self, channel: str, muted: bool):
        if channel in self.strips:
            self.strips[channel].set_mute(muted)

    def set_level(self, channel: str, v: float):
        if channel in self.strips:
            self.strips[channel].meter.set_level(v)
