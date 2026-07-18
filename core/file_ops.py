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
from .excel import registry, workbook_io


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


def set_active_file(year: int, path: Path) -> None:
    """Switch which already-registered candidate file is active for
    `year` — the one choke point everything (settings.json, the in-memory
    config.FILE_PATHS the rest of the app reads, and the cached schema
    instance) goes through, so a caller never has to update more than
    one of those and risk them drifting apart."""
    settings.set_active(year, path)
    config.FILE_PATHS[year] = Path(path)
    registry.invalidate(year)


def discover_candidate_files(folder: Path) -> list[Path]:
    """Every *.xlsx in `folder`, tracked or not — e.g. an unrelated file
    dropped in the same OneDrive folder as the real finance files.
    FileSelectionDialog cross-references each against the currently
    registered candidates (across all years) to decide checked/unchecked."""
    return sorted(Path(folder).glob("*.xlsx"))


def known_candidate_years() -> dict[Path, int]:
    """path -> year, for every currently registered candidate across all
    years (regardless of active/inactive) — used by FileSelectionDialog to
    look up which year (if any) a discovered file already belongs to."""
    result: dict[Path, int] = {}
    for year_str, entry in settings.load().get("files", {}).items():
        for c in entry["candidates"]:
            result[Path(c["path"])] = int(year_str)
    return result
