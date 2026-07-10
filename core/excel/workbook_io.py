"""
core/excel/workbook_io.py — load/save .xlsx with retry+backoff.

Excel or OneDrive can hold a transient lock on the file (open in Excel,
mid-sync). Retry with exponential backoff instead of failing outright.
"""
from __future__ import annotations

import time
import zipfile
from pathlib import Path

import openpyxl
from openpyxl.workbook import Workbook

_RETRY_DELAYS = (0.5, 1, 2, 4, 8)  # seconds


class WorkbookLockedError(Exception):
    """Raised when the workbook could not be read/written after all retries."""


def load(path: Path, data_only: bool = False) -> Workbook:
    last_exc: Exception | None = None
    for delay in (0, *_RETRY_DELAYS):
        if delay:
            time.sleep(delay)
        try:
            return openpyxl.load_workbook(path, data_only=data_only, keep_vba=False)
        except (PermissionError, zipfile.BadZipFile) as exc:
            last_exc = exc
    raise WorkbookLockedError(
        f"Could not open {path.name} — it may be open in Excel or still syncing "
        f"with OneDrive. Please close it and try again."
    ) from last_exc


def save(wb: Workbook, path: Path) -> None:
    last_exc: Exception | None = None
    for delay in (0, *_RETRY_DELAYS):
        if delay:
            time.sleep(delay)
        try:
            wb.save(path)
            return
        except PermissionError as exc:
            last_exc = exc
    raise WorkbookLockedError(
        f"Could not save {path.name} — it may be open in Excel or still syncing "
        f"with OneDrive. Please close it and try again."
    ) from last_exc
