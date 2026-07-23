"""
core/excel/workbook_io.py — load/save .xlsx with retry+backoff, plus an
mtime-keyed in-memory cache so repeated reads of an unchanged file (flipping
through months, or Analytics scanning a whole year) don't re-parse the whole
workbook from disk every time — that full re-parse, multiplied across every
month a page reads, was the cause of the month-navigation and yearly-view
slowness.

Excel or OneDrive can hold a transient lock on the file (open in Excel,
mid-sync). Retry with exponential backoff instead of failing outright.
"""
from __future__ import annotations

import os
import time
import zipfile
from pathlib import Path

import openpyxl
from openpyxl.workbook import Workbook

_RETRY_DELAYS = (0.5, 1, 2, 4, 8)  # seconds

_cache: dict[Path, tuple[float, Workbook]] = {}


class WorkbookLockedError(Exception):
    """Raised when the workbook could not be read/written after all retries."""


def load(path: Path, data_only: bool = False) -> Workbook:
    # The cache below is keyed only on path+mtime, not on this flag -- every
    # real caller in this project always loads with data_only=False (see
    # this module's own docstring/project convention: never trust Excel's
    # cached computed values). Asserting here turns a silent wrong-workbook
    # return (a data_only=True call transparently getting back a cached
    # data_only=False object) into a loud, obvious failure instead, should
    # that convention ever get violated.
    assert not data_only, "workbook_io.load(data_only=True) is not supported by this cache — see docstring"
    try:
        mtime = path.stat().st_mtime
    except OSError:
        mtime = None
    else:
        cached = _cache.get(path)
        if cached is not None and cached[0] == mtime:
            return cached[1]

    last_exc: Exception | None = None
    for delay in (0, *_RETRY_DELAYS):
        if delay:
            time.sleep(delay)
        try:
            wb = openpyxl.load_workbook(path, data_only=data_only, keep_vba=False)
            if mtime is not None:
                _cache[path] = (mtime, wb)
            return wb
        except (PermissionError, zipfile.BadZipFile) as exc:
            last_exc = exc
    raise WorkbookLockedError(
        f"Could not open {path.name} — it may be open in Excel or still syncing "
        f"with OneDrive. Please close it and try again."
    ) from last_exc


def invalidate(path: Path) -> None:
    """Drop any cached copy of `path`. Every write method calls this right
    after load(), before mutating the workbook in memory — so if the write
    fails before save() (SheetFullError, a bad rename, etc.), the cache is
    simply empty rather than holding a partially-mutated object that was
    never actually written to disk. The next load() re-reads the untouched
    file fresh."""
    _cache.pop(path, None)


def save(wb: Workbook, path: Path) -> None:
    # Atomic: write to a sibling temp file, then os.replace() it onto the
    # real path -- os.replace is a single filesystem rename, so a crash or
    # power loss mid-write leaves the original file untouched instead of a
    # half-written .xlsx (wb.save(path) directly truncates the real file
    # as it writes). OneDrive's own version history would let you recover
    # from that, but there's no reason to depend on it for something this
    # cheap to avoid outright.
    tmp_path = path.with_suffix(".tmp.xlsx")
    last_exc: Exception | None = None
    for delay in (0, *_RETRY_DELAYS):
        if delay:
            time.sleep(delay)
        try:
            wb.save(tmp_path)
            os.replace(tmp_path, path)
            try:
                _cache[path] = (path.stat().st_mtime, wb)
            except OSError:
                _cache.pop(path, None)
            return
        except PermissionError as exc:
            last_exc = exc
        finally:
            tmp_path.unlink(missing_ok=True)  # leftover only if save/replace failed this attempt
    _cache.pop(path, None)
    raise WorkbookLockedError(
        f"Could not save {path.name} — it may be open in Excel or still syncing "
        f"with OneDrive. Please close it and try again."
    ) from last_exc
