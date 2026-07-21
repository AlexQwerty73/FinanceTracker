"""
core/settings.py — persisted, per-machine app settings: which Excel
file(s) each supported year points at, and which template ("2025-style" /
"2026-style" / a custom template id) each file was created from. A year
can have multiple *candidate* files registered (e.g. while trying out a
new layout side by side with the original) but always has at most one
*active* candidate — the one the rest of the app actually reads/writes.
Lives outside the project/exe directory (a distributed .exe's own folder
isn't reliably writable) at ~/.financetracker/settings.json, so it
survives app updates/reinstalls.

Dependency-free by design (no import of core.config) — config.py is the
one that seeds this with its historical hardcoded defaults on first run,
so this module can stay a plain, low-level JSON store.
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path

SETTINGS_DIR = Path.home() / ".financetracker"
SETTINGS_PATH = SETTINGS_DIR / "settings.json"

TEMPLATE_2025 = "2025-style"
TEMPLATE_2026 = "2026-style"


def _migrate_old_shape(data: dict) -> None:
    """Upgrade the old one-file-per-year shape (`{"path":..., "template":
    ...}`) into the current multi-candidate shape (`{"active_path":...,
    "candidates":[...]}`) in place, so an existing install's settings.json
    keeps working without a manual migration step."""
    for entry in data.setdefault("files", {}).values():
        if "candidates" not in entry:
            path, template = entry["path"], entry["template"]
            entry.clear()
            entry["active_path"] = path
            entry["candidates"] = [{"path": path, "template": template}]


def load() -> dict:
    if not SETTINGS_PATH.exists():
        return {"files": {}}
    try:
        data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"files": {}}
    _migrate_old_shape(data)
    return data


def save(data: dict) -> None:
    # Derived from SETTINGS_PATH (not the separate SETTINGS_DIR constant)
    # so redirecting SETTINGS_PATH alone — e.g. tests pointing it at a
    # scratch file — creates the right parent dir instead of also touching
    # the real ~/.financetracker.
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")


def register_candidate(year: int, path: Path, template: str, activate: bool = True) -> None:
    """Add `path` as a known file for `year` (created from `template`).
    A year's first-ever candidate always becomes active regardless of
    `activate`; later candidates only take over if `activate=True`."""
    data = load()
    entry = data.setdefault("files", {}).setdefault(str(year), {"active_path": None, "candidates": []})
    path_str = str(path)
    if not any(c["path"] == path_str for c in entry["candidates"]):
        entry["candidates"].append({"path": path_str, "template": template})
    if activate or entry["active_path"] is None:
        entry["active_path"] = path_str
    save(data)


def set_active(year: int, path: Path) -> None:
    """Switch which already-registered candidate is active for `year`."""
    data = load()
    entry = data.get("files", {}).get(str(year))
    path_str = str(path)
    if entry is None or not any(c["path"] == path_str for c in entry["candidates"]):
        raise KeyError(f"{path} is not a known candidate for year {year}.")
    entry["active_path"] = path_str
    save(data)


def unregister_candidate(year: int, path: Path) -> None:
    """Stop tracking `path` for `year` (never deletes the file itself).
    Refuses if it's the active candidate and others remain — call
    set_active() with a replacement first. Removing a year's last
    candidate drops the year from get_file_paths()/get_year_templates()
    entirely."""
    data = load()
    entry = data.get("files", {}).get(str(year))
    if entry is None:
        return
    path_str = str(path)
    if entry["active_path"] == path_str and len(entry["candidates"]) > 1:
        raise ValueError("Pick a different active file for this year before removing this one.")
    entry["candidates"] = [c for c in entry["candidates"] if c["path"] != path_str]
    if not entry["candidates"]:
        del data["files"][str(year)]
    save(data)


def get_candidates(year: int) -> list[dict]:
    entry = load().get("files", {}).get(str(year))
    return list(entry["candidates"]) if entry else []


def update_path(year: int, new_path: Path) -> None:
    """Change the active candidate's path in place, keeping its template
    unchanged. Used when the active file is moved to a new folder — see
    core/file_ops.py."""
    data = load()
    entry = data.get("files", {}).get(str(year))
    if entry is None:
        raise KeyError(f"Year {year} is not registered.")
    old_path = entry["active_path"]
    for c in entry["candidates"]:
        if c["path"] == old_path:
            c["path"] = str(new_path)
    entry["active_path"] = str(new_path)
    save(data)


def get_file_paths() -> dict[int, Path]:
    """Year -> active file path (the one the app actually reads/writes)."""
    return {
        int(year): Path(entry["active_path"])
        for year, entry in load().get("files", {}).items()
        if entry.get("active_path")
    }


def get_year_templates() -> dict[int, str]:
    """Year -> the active candidate's template id."""
    result: dict[int, str] = {}
    for year, entry in load().get("files", {}).items():
        active = entry.get("active_path")
        for c in entry["candidates"]:
            if c["path"] == active:
                result[int(year)] = c["template"]
                break
    return result


def get_default_folder() -> str | None:
    return load().get("default_folder")


def set_default_folder(path: Path) -> None:
    data = load()
    data["default_folder"] = str(path)
    save(data)


def _snapshots_root(data: dict) -> dict:
    """The {"list", "active_id", "use_enabled"} structure — replaces (not
    migrates) an older per-currency net_worth_snapshots shape from an
    earlier round this session, which isn't compatible with the history-
    of-snapshots model and was never relied on with real data."""
    root = data.get("net_worth_snapshots")
    if not isinstance(root, dict) or "list" not in root:
        root = {"list": [], "active_id": None, "use_enabled": True}
        data["net_worth_snapshots"] = root
    return root


def get_net_worth_snapshots() -> list[dict]:
    """[{"id", "date": "YYYY-MM-DD", "taken_at": iso datetime,
    "balances": {cur: {"cash","card"}},   # exactly what was typed into the form
    "opening": {cur: {"cash","card"}},    # balance before the very first transaction
    "monthly_history": {"YYYY-MM-01": {cur: {"cash","card"}}, ...}},
    ...] — every snapshot ever taken (Currencies page's "Take snapshot"
    form), newest first. `monthly_history` is permanent once a given
    month's entry is written (never recomputed or overwritten — same rule
    core/rate_history.py already follows for cached rates) but keeps
    growing forward every time the Currencies page runs its catch-up
    pass, for as long as this snapshot exists (whether it's the active
    one or not)."""
    return sorted(_snapshots_root(load())["list"], key=lambda s: s["taken_at"], reverse=True)


def add_net_worth_snapshot(date_iso: str, taken_at_iso: str, balances: dict, opening: dict, monthly_history: dict) -> str:
    """Stores a new snapshot and makes it the active one. Returns its id."""
    snapshot_id = uuid.uuid4().hex
    data = load()
    root = _snapshots_root(data)
    root["list"].append({
        "id": snapshot_id, "date": date_iso, "taken_at": taken_at_iso,
        "balances": balances, "opening": opening, "monthly_history": monthly_history,
    })
    root["active_id"] = snapshot_id
    save(data)
    return snapshot_id


def delete_net_worth_snapshot(snapshot_id: str) -> None:
    data = load()
    root = _snapshots_root(data)
    root["list"] = [s for s in root["list"] if s["id"] != snapshot_id]
    if root["active_id"] == snapshot_id:
        root["active_id"] = None
    save(data)


def extend_net_worth_snapshot_history(snapshot_id: str, new_entries: dict) -> None:
    """Merges `new_entries` ({"YYYY-MM-01": {cur: {...}}, ...}) into a
    snapshot's monthly_history -- only adds keys that aren't already
    there, never overwrites an existing (frozen) month."""
    data = load()
    root = _snapshots_root(data)
    for snap in root["list"]:
        if snap["id"] == snapshot_id:
            history = snap.setdefault("monthly_history", {})
            for key, value in new_entries.items():
                history.setdefault(key, value)
            save(data)
            return


def get_active_net_worth_snapshot_id() -> str | None:
    return _snapshots_root(load())["active_id"]


def set_active_net_worth_snapshot_id(snapshot_id: str | None) -> None:
    data = load()
    _snapshots_root(data)["active_id"] = snapshot_id
    save(data)


def get_net_worth_snapshot_use_enabled() -> bool:
    """The one page-wide "use snapshot in calculations" switch — separate
    from *which* snapshot is active, so the user can flip calculations
    off without losing track of which snapshot they'd go back to."""
    return _snapshots_root(load())["use_enabled"]


def set_net_worth_snapshot_use_enabled(enabled: bool) -> None:
    data = load()
    _snapshots_root(data)["use_enabled"] = enabled
    save(data)


def get_ignored_review_items() -> list[str]:
    """Signatures (core/duplicates.py's DuplicateGroup.signature /
    Outlier.signature) the user has dismissed as "not actually a problem"
    on the Review page — excluded from future detection runs. One shared
    list for both duplicates and outliers (signatures are prefixed
    "dup|"/"outlier|", so they never collide)."""
    return list(load().get("ignored_review_items", []))


def set_review_item_ignored(signature: str, ignored: bool) -> None:
    data = load()
    ignored_list = data.setdefault("ignored_review_items", [])
    if ignored and signature not in ignored_list:
        ignored_list.append(signature)
    elif not ignored and signature in ignored_list:
        ignored_list.remove(signature)
    save(data)
