"""
pads_widget.py
--------------
A 2x4 grid of pad buttons that flash when triggered and show the assigned
sample's short name. Clicking a pad emits padClicked(index) so pads can be
auditioned with the mouse too.
"""

from __future__ import annotations

from PySide6.QtWidgets import QWidget, QGridLayout, QPushButton
from PySide6.QtCore import Signal, QTimer


class PadButton(QPushButton):
    def __init__(self, index: int):
        super().__init__(f"PAD {index + 1}")
        self.index = index
        self.setMinimumSize(70, 56)
        self._base_style = (
            "QPushButton{background:#2c313a;border:1px solid #444;"
            "border-radius:8px;font-weight:600;}"
        )
        self._flash_style = (
            "QPushButton{background:#ff5a36;border:1px solid #ff8a36;"
            "border-radius:8px;font-weight:700;color:#111;}"
        )
        self.setStyleSheet(self._base_style)

    def flash(self):
        self.setStyleSheet(self._flash_style)
        QTimer.singleShot(140, lambda: self.setStyleSheet(self._base_style))


class PadsWidget(QWidget):
    padClicked = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        grid = QGridLayout(self)
        grid.setSpacing(6)
        self.buttons: list[PadButton] = []
        for i in range(8):
            btn = PadButton(i)
            btn.clicked.connect(lambda _=False, idx=i: self.padClicked.emit(idx))
            # MPK layout: 2 rows of 4
            grid.addWidget(btn, i // 4, i % 4)
            self.buttons.append(btn)

    def flash(self, index: int):
        if 0 <= index < len(self.buttons):
            self.buttons[index].flash()

    def set_label(self, index: int, name: str):
        if 0 <= index < len(self.buttons):
            text = f"PAD {index + 1}"
            if name:
                text += f"\n{name}"
            self.buttons[index].setText(text)
