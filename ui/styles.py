"""Qt stylesheet — dark, MPK-mini-inspired look."""

STYLE = """
QWidget {
    background-color: #1c1f24;
    color: #e6e6e6;
    font-family: "Segoe UI", Arial, sans-serif;
    font-size: 12px;
}
QGroupBox {
    border: 1px solid #33373f;
    border-radius: 8px;
    margin-top: 14px;
    padding: 8px;
    background-color: #23272e;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 4px;
    color: #9aa4b2;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 1px;
}
QPushButton {
    background-color: #2c313a;
    border: 1px solid #3a3f4a;
    border-radius: 6px;
    padding: 6px 10px;
}
QPushButton:hover { background-color: #353b45; border-color: #ff5a36; }
QPushButton:pressed { background-color: #ff5a36; color: #111; }
QPushButton:checked { background-color: #ff5a36; color: #111; font-weight: 600; }
QCheckBox::indicator:checked {
    background-color: #ff5a36;
    border: 1px solid #ff5a36;
    border-radius: 3px;
}
QCheckBox::indicator:unchecked {
    background-color: #14171b;
    border: 1px solid #3a3f4a;
    border-radius: 3px;
}
QComboBox, QLineEdit {
    background-color: #14171b;
    border: 1px solid #3a3f4a;
    border-radius: 5px;
    padding: 4px 6px;
}
QComboBox QAbstractItemView {
    background-color: #14171b;
    selection-background-color: #ff5a36;
}
QPlainTextEdit {
    background-color: #0f1113;
    border: 1px solid #2a2e35;
    border-radius: 6px;
    font-family: "Consolas", "Courier New", monospace;
    font-size: 11px;
    color: #8fd17a;
}
QSlider::groove:vertical {
    width: 6px; background: #14171b; border-radius: 3px;
}
QSlider::handle:vertical {
    height: 16px; margin: 0 -6px; border-radius: 4px;
    background: #ff5a36;
}
QSlider::groove:horizontal { height: 6px; background:#14171b; border-radius:3px; }
QSlider::handle:horizontal { width:16px; margin:-6px 0; border-radius:4px; background:#ff5a36; }
QLabel#title {
    font-size: 20px;
    font-weight: 800;
    color: #ffffff;
    letter-spacing: 6px;
    padding: 6px 2px 10px 2px;
    border-bottom: 2px solid #ff5a36;
}
QCheckBox::indicator { width: 16px; height: 16px; }
"""
