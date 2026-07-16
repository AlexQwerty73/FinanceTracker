"""
core/file_ops.py — move a registered year's file to a new folder, keeping
the app's registration (settings.json + in-memory config.FILE_PATHS) in
sync with where the file actually lives, so the user never has to move a
file in Explorer and then separately figure out how to point the app at
its new location.
"""
from __future__ import annotations

import shutil
from pathlib import Path

from . import config, settings
from .excel import workbook_io


def move_year_file(year: int, new_path: Path) -> None:
    """Physically move the file registered for `year` to `new_path`
    (folder + filename), then update settings.json and config.FILE_PATHS
    to match. Raises FileNotFoundError/FileExistsError/PermissionError
    (e.g. the file is open in Excel) — callers should show these as a
    status message, not let them propagate as a crash."""
    old_path = config.FILE_PATHS.get(year)
    if old_path is None:
        raise ValueError(f"Year {year} is not registered.")
    if not old_path.exists():
        raise FileNotFoundError(f"{old_path} does not exist — nothing to move.")
    new_path = Path(new_path)
    if new_path == old_path:
        return
    if new_path.exists():
        raise FileExistsError(f"{new_path} already exists.")

    new_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(old_path), str(new_path))  # handles cross-drive moves too

    workbook_io.invalidate(old_path)
    settings.update_path(year, new_path)
    config.FILE_PATHS[year] = new_path
