"""
main.py — application entry point.
Run with:  python main.py
"""
import sys

if sys.platform == "win32":
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "com.financetracker.app")
    except Exception:
        pass

from PyQt6.QtWidgets import QApplication

from app.window import App


def main() -> None:
    app = QApplication(sys.argv)
    window = App()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
