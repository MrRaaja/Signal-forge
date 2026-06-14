"""
mic_widget.py
-------------
Mic dynamics controls: noise gate + compressor.

Signals:
  gateChanged(enabled, threshold_db)
  compChanged(enabled, threshold_db, ratio)
"""

from __future__ import annotations

from PySide6.QtWidgets import QWidget, QGridLayout, QLabel, QCheckBox, QSlider
from PySide6.QtCore import Qt, Signal


class MicWidget(QWidget):
    gateChanged = Signal(bool, float)
    compChanged = Signal(bool, float, float)

    def __init__(self, parent=None):
        super().__init__(parent)
        g = QGridLayout(self)
        g.setHorizontalSpacing(10)
        g.setVerticalSpacing(6)

        # ---- noise gate ----
        self.gate_chk = QCheckBox("Noise gate")
        self.gate_chk.toggled.connect(self._emit_gate)
        g.addWidget(self.gate_chk, 0, 0, 1, 3)

        g.addWidget(QLabel("Threshold"), 1, 0)
        self.gate_slider = QSlider(Qt.Horizontal)
        self.gate_slider.setRange(-70, -20)       # dB
        self.gate_slider.setValue(-45)
        self.gate_slider.valueChanged.connect(self._emit_gate)
        self.gate_lbl = QLabel("-45 dB")
        self.gate_lbl.setStyleSheet("color:#7f8896;font-size:10px;")
        g.addWidget(self.gate_slider, 1, 1)
        g.addWidget(self.gate_lbl, 1, 2)

        # ---- compressor ----
        self.comp_chk = QCheckBox("Compressor")
        self.comp_chk.toggled.connect(self._emit_comp)
        g.addWidget(self.comp_chk, 2, 0, 1, 3)

        g.addWidget(QLabel("Threshold"), 3, 0)
        self.comp_thr = QSlider(Qt.Horizontal)
        self.comp_thr.setRange(-40, 0)            # dB
        self.comp_thr.setValue(-18)
        self.comp_thr.valueChanged.connect(self._emit_comp)
        self.comp_thr_lbl = QLabel("-18 dB")
        self.comp_thr_lbl.setStyleSheet("color:#7f8896;font-size:10px;")
        g.addWidget(self.comp_thr, 3, 1)
        g.addWidget(self.comp_thr_lbl, 3, 2)

        g.addWidget(QLabel("Amount"), 4, 0)
        self.comp_ratio = QSlider(Qt.Horizontal)
        self.comp_ratio.setRange(11, 100)         # ratio x10 (1.1 .. 10.0)
        self.comp_ratio.setValue(30)
        self.comp_ratio.valueChanged.connect(self._emit_comp)
        self.comp_ratio_lbl = QLabel("3.0:1")
        self.comp_ratio_lbl.setStyleSheet("color:#7f8896;font-size:10px;")
        g.addWidget(self.comp_ratio, 4, 1)
        g.addWidget(self.comp_ratio_lbl, 4, 2)

    def _emit_gate(self, *_):
        thr = self.gate_slider.value()
        self.gate_lbl.setText(f"{thr} dB")
        self.gateChanged.emit(self.gate_chk.isChecked(), float(thr))

    def _emit_comp(self, *_):
        thr = self.comp_thr.value()
        ratio = self.comp_ratio.value() / 10.0
        self.comp_thr_lbl.setText(f"{thr} dB")
        self.comp_ratio_lbl.setText(f"{ratio:.1f}:1")
        self.compChanged.emit(self.comp_chk.isChecked(), float(thr), float(ratio))

    # ----------------------------------------------------------- setters
    def set_state(self, gate_on, gate_thr, comp_on, comp_thr, comp_ratio):
        widgets = (self.gate_chk, self.gate_slider, self.comp_chk,
                   self.comp_thr, self.comp_ratio)
        for w in widgets:
            w.blockSignals(True)
        self.gate_chk.setChecked(gate_on)
        self.gate_slider.setValue(int(gate_thr))
        self.comp_chk.setChecked(comp_on)
        self.comp_thr.setValue(int(comp_thr))
        self.comp_ratio.setValue(int(round(comp_ratio * 10)))
        for w in widgets:
            w.blockSignals(False)
        self.gate_lbl.setText(f"{int(gate_thr)} dB")
        self.comp_thr_lbl.setText(f"{int(comp_thr)} dB")
        self.comp_ratio_lbl.setText(f"{comp_ratio:.1f}:1")
