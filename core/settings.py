"""
core/settings.py — persisted, per-machine app settings: which Excel file
each supported year points at, and which template ("2025-style" /
"2026-style") that file was created from. Lives outside the project/exe
directory (a distributed .exe's own folder isn't reliably writable) at
~/.financetracker/settings.json, so it survives app updates/reinstalls.

Dependency-free by design (no import of core.config) — config.py is the
one that seeds this with its historical hardcoded defaults on first run,
so this module can stay a plain, low-level JSON store.
"""
from __future__ import annotations

import json
from pathlib import Path

SETTINGS_DIR = Path.home() / ".financetracker"
SETTINGS_PATH = SETTINGS_DIR / "settings.json"

TEMPLATE_2025 = "2025-style"
TEMPLATE_2026 = "2026-style"


def load() -> dict:
    if not SETTINGS_PATH.exists():
        return {"files": {}}
    try:
        return json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"files": {}}


def save(data: dict) -> None:
    # Derived from SETTINGS_PATH (not the separate SETTINGS_DIR constant)
    # so redirecting SETTINGS_PATH alone — e.g. tests pointing it at a
    # scratch file — creates the right parent dir instead of also touching
    # the real ~/.financetracker.
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")


def register_file(year: int, path: Path, template: str) -> None:
    """Record that `year` now maps to `path`, created from `template`
    (TEMPLATE_2025 or TEMPLATE_2026) — persisted immediately."""
    data = load()
    data.setdefault("files", {})[str(year)] = {"path": str(path), "template": template}
    save(data)


def update_path(year: int, new_path: Path) -> None:
    """Change only the file path for an already-registered year, keeping
    its template unchanged. Used when a file is moved to a new folder —
    see core/file_ops.py."""
    data = load()
    entry = data.get("files", {}).get(str(year))
    if entry is None:
        raise KeyError(f"Year {year} is not registered.")
    entry["path"] = str(new_path)
    save(data)


def get_file_paths() -> dict[int, Path]:
    return {int(year): Path(entry["path"]) for year, entry in load().get("files", {}).items()}


def get_year_templates() -> dict[int, str]:
    return {int(year): entry["template"] for year, entry in load().get("files", {}).items()}


def get_default_folder() -> str | None:
    return load().get("default_folder")


def set_default_folder(path: Path) -> None:
    data = load()
    data["default_folder"] = str(path)
    save(data)
