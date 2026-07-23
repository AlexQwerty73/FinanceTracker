"""
main.py — application entry point.
Run with:  python main.py
"""
import sys
import traceback
from datetime import datetime
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

_ERROR_LOG_PATH = Path.home() / ".financetracker" / "error.log"
_ERROR_LOG_MAX_BYTES = 1_000_000


def _log_uncaught_exception(exc_type, exc_value, exc_tb) -> None:
    """Appends a timestamped traceback to ~/.financetracker/error.log —
    the packaged .exe has no console for anyone but the developer to see
    a crash in, so this is the one diagnostic a user could actually send
    back. Never lets a logging failure mask the real crash: falls through
    to the default hook regardless of whether writing the log succeeded."""
    try:
        _ERROR_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        if _ERROR_LOG_PATH.exists() and _ERROR_LOG_PATH.stat().st_size > _ERROR_LOG_MAX_BYTES:
            _ERROR_LOG_PATH.unlink()  # start fresh rather than growing forever
        with _ERROR_LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(f"\n--- {datetime.now().isoformat(timespec='seconds')} ---\n")
            traceback.print_exception(exc_type, exc_value, exc_tb, file=f)
    except OSError:
        pass
    sys.__excepthook__(exc_type, exc_value, exc_tb)


def _icon_path() -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base / "assets" / "icon.ico"


def main() -> None:
    sys.excepthook = _log_uncaught_exception
    app = QApplication(sys.argv)
    icon = QIcon(str(_icon_path()))
    app.setWindowIcon(icon)
    window = App()
    window.setWindowIcon(icon)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
