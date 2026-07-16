"""
core/config.py — file paths and shared constants.

FILE_PATHS is seeded from core.settings (persisted per-machine) rather than
hardcoded, so a distributed copy of the app isn't stuck pointing at the
original developer's files — see core/settings.py and
core/excel/templates.py for how a new year/file gets added at runtime.
On this machine's very first run (no settings.json yet), it's seeded with
the historical hardcoded defaults below so the existing setup needs no
migration step.

FINANCES_DIR (the default suggested folder for new files) can likewise be
overridden per-machine via settings' "default_folder" — see
app/components/manage_files_dialog.py. Both FILE_PATHS and FINANCES_DIR
are plain mutable module-level values (not functions) that get updated
in-memory directly wherever a path changes at runtime (create/move a
file), same pattern throughout — see core/file_ops.py.
"""
from __future__ import annotations

from pathlib import Path

from . import settings

_DEFAULT_FINANCES_DIR = Path.home() / "OneDrive" / "Finances"

_DEFAULT_FILES = {
    2025: (_DEFAULT_FINANCES_DIR / "Finances_2025.xlsx", settings.TEMPLATE_2025),
    2026: (_DEFAULT_FINANCES_DIR / "Finances_2026.xlsx", settings.TEMPLATE_2026),
}

_settings_data = settings.load()
if not _settings_data.get("files"):
    for _year, (_path, _template) in _DEFAULT_FILES.items():
        settings.register_file(_year, _path, _template)
    _settings_data = settings.load()

FINANCES_DIR = Path(_settings_data.get("default_folder") or _DEFAULT_FINANCES_DIR)

FILE_PATHS: dict[int, Path] = {
    int(year): Path(entry["path"]) for year, entry in _settings_data["files"].items()
}
