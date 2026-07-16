"""
core/watcher.py — watches every folder currently holding a registered
Finances file for changes and reports them via a Qt signal, so the UI
never touches watchdog's worker thread directly. Watches multiple
directories (not just one default folder), since core.file_ops.move_year_file
can scatter files across different folders — call rewatch() after any
create/move so newly relevant folders start being watched without an app
restart.
"""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QObject, pyqtSignal
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from . import config


class _Handler(FileSystemEventHandler):
    def __init__(self, on_change):
        self._on_change = on_change

    def _maybe_notify(self, path: str) -> None:
        # Read config.FILE_PATHS live (not a module-level snapshot) so a
        # file created/moved at runtime is watched too, no app restart needed.
        watched_names = {p.name for p in config.FILE_PATHS.values()}
        if Path(path).name in watched_names:
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
    any registered Finances file is modified on disk, wherever its folder
    currently is."""

    changed = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._observer = Observer()
        self._watched_dirs: set[str] = set()
        self._schedule_current_dirs()

    def _current_dirs(self) -> set[Path]:
        dirs = {p.parent for p in config.FILE_PATHS.values()}
        dirs.add(config.FINANCES_DIR)
        return dirs

    def _schedule_current_dirs(self) -> None:
        for d in self._current_dirs():
            # watchdog's schedule()/start() raises FileNotFoundError if the
            # directory doesn't exist yet — true for a brand-new install
            # with no Finances folder at all until a file is created there.
            d.mkdir(parents=True, exist_ok=True)
            key = str(d)
            if key not in self._watched_dirs:
                self._observer.schedule(_Handler(self.changed.emit), key, recursive=False)
                self._watched_dirs.add(key)

    def rewatch(self) -> None:
        """Call after registering a new file or moving one to a different
        folder, so that folder starts being watched immediately — watchdog
        supports scheduling additional watches on an already-running
        Observer, so this works whether called before or after start()."""
        self._schedule_current_dirs()

    def start(self) -> None:
        self._observer.start()

    def stop(self) -> None:
        self._observer.stop()
        self._observer.join(timeout=2)
