"""
knobs_widget.py
---------------
8 rotary knobs (QDial 0..127). Each knob has:
  * a live value reflecting the physical knob,
  * a 'Learn' button to bind it to whatever CC the physical knob sends,
  * a target dropdown (instrument / pad / mic / master / none).

Signals:
  learnRequested(index)      -> user clicked Learn on knob `index`
  targetChanged(index, str)  -> user changed knob `index` target
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QWidget, QGridLayout, QVBoxLayout, QDial, QLabel, QPushButton, QComboBox
)
from PySide6.QtCore import Qt, Signal

TARGETS = ["instrument", "pad", "mic", "master", "none"]


class KnobsWidget(QWidget):
    learnRequested = Signal(int)
    targetChanged = Signal(int, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        grid = QGridLayout(self)
        grid.setSpacing(8)
        self.dials: list[QDial] = []
        self.cc_labels: list[QLabel] = []
        self.target_combos: list[QComboBox] = []
        self.learn_btns: list[QPushButton] = []

        for i in range(8):
            col = QVBoxLayout()
            title = QLabel(f"K{i + 1}")
            title.setAlignment(Qt.AlignCenter)

            dial = QDial()
            dial.setRange(0, 127)
            dial.setNotchesVisible(True)
            dial.setFixedSize(54, 54)
            dial.setEnabled(False)  # display only; driven by MIDI
            self.dials.append(dial)

            cc_lbl = QLabel("CC --")
            cc_lbl.setAlignment(Qt.AlignCenter)
            cc_lbl.setStyleSheet("color:#7f8896;font-size:10px;")
            self.cc_labels.append(cc_lbl)

            learn = QPushButton("Learn")
            learn.setFixedHeight(22)
            learn.clicked.connect(lambda _=False, idx=i: self.learnRequested.emit(idx))
            self.learn_btns.append(learn)

            combo = QComboBox()
            combo.addItems(TARGETS)
            combo.currentTextChanged.connect(
                lambda t, idx=i: self.targetChanged.emit(idx, t))
            self.target_combos.append(combo)

            col.addWidget(title)
            col.addWidget(dial, alignment=Qt.AlignCenter)
            col.addWidget(cc_lbl)
            col.addWidget(learn)
            col.addWidget(combo)
            holder = QWidget()
            holder.setLayout(col)
            grid.addWidget(holder, i // 4, i % 4)

    def set_value(self, index: int, value: int):
        if 0 <= index < 8:
            self.dials[index].setValue(int(value))

    def set_cc(self, index: int, cc):
        if 0 <= index < 8:
            self.cc_labels[index].setText(f"CC {cc}" if cc is not None else "CC --")

    def set_learning(self, index: int, active: bool):
        """Highlight a knob's Learn button while waiting for a CC."""
        if not (0 <= index < 8):
            return
        btn = self.learn_btns[index]
        if active:
            btn.setText("Turn knob…")
            btn.setStyleSheet("background:#ff5a36;color:#111;font-weight:700;")
        else:
            btn.setText("Learn")
            btn.setStyleSheet("")

    def set_target(self, index: int, target: str):
        if 0 <= index < 8:
            self.target_combos[index].blockSignals(True)
            self.target_combos[index].setCurrentText(target)
            self.target_combos[index].blockSignals(False)
