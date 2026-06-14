"""
main.py — entry point for SignalForge.

Run from source:
    python main.py
"""

import sys


def main() -> int:
    try:
        from PySide6.QtWidgets import QApplication
    except Exception as e:  # pragma: no cover
        print("PySide6 is required. Install with:  pip install -r requirements.txt")
        print(f"Import error: {e}")
        return 1

    from ui.main_window import MainWindow
    from core.branding import APP_NAME

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    win = MainWindow()
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
