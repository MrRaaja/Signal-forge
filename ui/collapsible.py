"""
collapsible.py
--------------
A QGroupBox-style container with a toggle button that collapses/expands its content.
"""

from __future__ import annotations

from PySide6.QtWidgets import QWidget, QVBoxLayout, QPushButton, QSizePolicy
from PySide6.QtCore import Qt


class CollapsibleBox(QWidget):
    def __init__(self, title: str, parent=None, collapsed: bool = False):
        super().__init__(parent)
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(2)

        self._toggle = QPushButton()
        self._toggle.setCheckable(True)
        self._toggle.setChecked(not collapsed)
        self._toggle.setStyleSheet("""
            QPushButton {
                text-align: left;
                padding: 5px 10px;
                background: #23272e;
                border: 1px solid #33373f;
                border-radius: 6px;
                color: #9aa4b2;
                font-weight: 600;
                font-size: 11px;
                letter-spacing: 1px;
            }
            QPushButton:hover { background: #2c313a; }
        """)
        self._title = title
        self._update_label()
        self._toggle.toggled.connect(self._on_toggle)
        self._layout.addWidget(self._toggle)

        self._body = QWidget()
        self._body_layout = QVBoxLayout(self._body)
        self._body_layout.setContentsMargins(4, 4, 4, 4)
        self._layout.addWidget(self._body)

        if collapsed:
            self._body.setVisible(False)

    def _update_label(self):
        arrow = "▼" if self._toggle.isChecked() else "▶"
        self._toggle.setText(f"{arrow}  {self._title.upper()}")

    def _on_toggle(self, checked: bool):
        self._body.setVisible(checked)
        self._update_label()

    def addWidget(self, widget: QWidget):
        self._body_layout.addWidget(widget)

    def setLayout(self, layout):
        self._body_layout.addLayout(layout)
