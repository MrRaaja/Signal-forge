"""
keyboard_widget.py
------------------
A small painted piano keyboard that highlights notes as they are played.
Covers MIDI notes LOW..HIGH; notes outside the range are simply ignored
(they still play and are logged elsewhere).
"""

from __future__ import annotations

from PySide6.QtWidgets import QWidget
from PySide6.QtGui import QPainter, QColor, QPen
from PySide6.QtCore import Qt, QRectF


LOW = 36     # C2
HIGH = 72    # C5  -> 3 octaves, comfortably covers the 25-key MPK range
WHITE_SET = {0, 2, 4, 5, 7, 9, 11}  # semitone offsets that are white keys


class KeyboardWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(126)
        self.active: set[int] = set()
        self._white_notes = [n for n in range(LOW, HIGH + 1) if (n % 12) in WHITE_SET]

    def set_note(self, note: int, on: bool) -> None:
        if on:
            self.active.add(note)
        else:
            self.active.discard(note)
        self.update()

    def clear_all(self) -> None:
        self.active.clear()
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, False)
        w = self.width()
        h = self.height()
        n_white = len(self._white_notes)
        if n_white == 0:
            return
        ww = w / n_white
        label_h = 16  # pixels reserved at bottom for octave labels
        key_h = h - label_h

        # white keys
        white_x = {}
        for i, note in enumerate(self._white_notes):
            x = i * ww
            white_x[note] = x
            rect = QRectF(x, 0, ww - 1, key_h)
            color = QColor("#ff5a36") if note in self.active else QColor("#f3f3f3")
            p.fillRect(rect, color)
            p.setPen(QPen(QColor("#888"), 1))
            p.drawRect(rect)

        # black keys (drawn on top)
        bw = ww * 0.62
        bh = key_h * 0.62
        for note in range(LOW, HIGH + 1):
            semitone = note % 12
            if semitone in WHITE_SET:
                continue
            left_white = note - 1
            if left_white in white_x:
                x = white_x[left_white] + ww - bw / 2
                rect = QRectF(x, 0, bw, bh)
                color = QColor("#ff8a36") if note in self.active else QColor("#111418")
                p.fillRect(rect, color)
                p.setPen(QPen(QColor("#000"), 1))
                p.drawRect(rect)

        # octave labels at C notes (bottom strip)
        p.fillRect(QRectF(0, key_h, w, label_h), QColor("#1c1f24"))
        font = p.font()
        font.setPointSize(8)
        p.setFont(font)
        for note, x in white_x.items():
            if note % 12 == 0:  # C note
                octave = (note // 12) - 1
                label = f"C{octave}"
                p.setPen(QColor("#9aa4b2"))
                p.drawText(QRectF(x, key_h, ww * 2, label_h),
                           Qt.AlignLeft | Qt.AlignVCenter, label)
        p.end()
