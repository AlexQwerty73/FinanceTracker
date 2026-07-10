"""
core/watcher.py — watches the Finances directory for changes to either
workbook and reports them via a Qt signal, so the UI never touches
watchdog's worker thread directly.
"""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QObject, pyqtSignal
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from .config import FILE_PATHS, FINANCES_DIR

_WATCHED_NAMES = {p.name for p in FILE_PATHS.values()}


class _Handler(FileSystemEventHandler):
    def __init__(self, on_change):
        self._on_change = on_change

    def _maybe_notify(self, path: str) -> None:
        if Path(path).name in _WATCHED_NAMES:
            self._on_change(path)

    def on_modified(self, event):
        if not event.is_directory:
            self._maybe_notify(event.src_path)

    def on_created(self, event):
        if not event.is_directory:
            self._maybe_notify(event.src_path)

    def on_moved(self, event):
        if not event.is_directory:
            self._maybe_notify(event.dest_path)


class FileWatcher(QObject):
    """Emits `changed` (thread-safe, queued to the Qt main thread) whenever
    Finances_2025.xlsx or Finances_2026.xlsx is modified on disk."""

    changed = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._observer = Observer()
        self._observer.schedule(_Handler(self.changed.emit), str(FINANCES_DIR), recursive=False)

    def start(self) -> None:
        self._observer.start()

    def stop(self) -> None:
        self._observer.stop()
        self._observer.join(timeout=2)
