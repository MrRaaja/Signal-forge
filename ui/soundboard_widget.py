"""
soundboard_widget.py
--------------------
Assignment panel for the 8 pads. One compact row per pad:

  [PAD n] [file name] [Assign] [Clear] [Stop] [mode v] [vol ----] [Learn note: NN]

Signals (index = pad 0..7):
  assignRequested(index)        user clicked Assign (open file dialog in window)
  clearRequested(index)
  stopRequested(index)
  modeChanged(index, mode)
  volumeChanged(index, 0..1)
  learnNoteRequested(index)
"""

from __future__ import annotations

import os
from PySide6.QtWidgets import (
    QWidget, QGridLayout, QLabel, QPushButton, QComboBox, QSlider
)
from PySide6.QtCore import Qt, Signal

MODES = ["oneshot", "hold", "toggle"]


class SoundboardWidget(QWidget):
    assignRequested = Signal(int)
    clearRequested = Signal(int)
    stopRequested = Signal(int)
    modeChanged = Signal(int, str)
    volumeChanged = Signal(int, float)
    learnNoteRequested = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        grid = QGridLayout(self)
        grid.setHorizontalSpacing(6)
        grid.setVerticalSpacing(4)

        headers = ["Pad", "File", "", "", "", "Mode", "Volume", "Note"]
        for c, h in enumerate(headers):
            lbl = QLabel(h)
            lbl.setStyleSheet("color:#7f8896;font-size:10px;font-weight:600;")
            grid.addWidget(lbl, 0, c)

        self.file_labels: list[QLabel] = []
        self.mode_combos: list[QComboBox] = []
        self.vol_sliders: list[QSlider] = []
        self.note_btns: list[QPushButton] = []

        for i in range(8):
            r = i + 1
            grid.addWidget(QLabel(f"{i + 1}"), r, 0)

            fl = QLabel("— empty —")
            fl.setMinimumWidth(150)
            fl.setStyleSheet("color:#9aa4b2;")
            self.file_labels.append(fl)
            grid.addWidget(fl, r, 1)

            assign = QPushButton("Assign")
            assign.clicked.connect(lambda _=False, idx=i: self.assignRequested.emit(idx))
            grid.addWidget(assign, r, 2)

            clear = QPushButton("Clear")
            clear.clicked.connect(lambda _=False, idx=i: self.clearRequested.emit(idx))
            grid.addWidget(clear, r, 3)

            stop = QPushButton("Stop")
            stop.clicked.connect(lambda _=False, idx=i: self.stopRequested.emit(idx))
            grid.addWidget(stop, r, 4)

            mode = QComboBox()
            mode.addItems(MODES)
            mode.currentTextChanged.connect(
                lambda t, idx=i: self.modeChanged.emit(idx, t))
            self.mode_combos.append(mode)
            grid.addWidget(mode, r, 5)

            vol = QSlider(Qt.Horizontal)
            vol.setRange(0, 100)
            vol.setValue(100)
            vol.setFixedWidth(90)
            vol.valueChanged.connect(
                lambda v, idx=i: self.volumeChanged.emit(idx, v / 100.0))
            self.vol_sliders.append(vol)
            grid.addWidget(vol, r, 6)

            note = QPushButton("note --")
            note.clicked.connect(
                lambda _=False, idx=i: self.learnNoteRequested.emit(idx))
            self.note_btns.append(note)
            grid.addWidget(note, r, 7)

    # -- setters used to reflect loaded settings ------------------------------
    def set_file(self, index: int, path: str | None):
        name = os.path.basename(path) if path else "— empty —"
        self.file_labels[index].setText(name)

    def set_mode(self, index: int, mode: str):
        c = self.mode_combos[index]
        c.blockSignals(True); c.setCurrentText(mode); c.blockSignals(False)

    def set_volume(self, index: int, v0to1: float):
        s = self.vol_sliders[index]
        s.blockSignals(True); s.setValue(int(round(v0to1 * 100))); s.blockSignals(False)

    def set_note(self, index: int, note):
        self.note_btns[index].setText(f"note {note}" if note is not None else "note --")
