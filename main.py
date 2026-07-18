"""
main.py — application entry point.
Run with:  python main.py
"""
import sys
from pathlib import Path

if sys.platform == "win32":
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "com.financetracker.app")
    except Exception:
        pass

from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QApplication

from app.window import App


def _icon_path() -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base / "assets" / "icon.ico"


def main() -> None:
    app = QApplication(sys.argv)
    icon = QIcon(str(_icon_path()))
    app.setWindowIcon(icon)
    window = App()
    window.setWindowIcon(icon)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
