"""
core/excel/_rows.py — shared row-scanning helpers for the year schemas.
"""
from __future__ import annotations

from openpyxl.worksheet.worksheet import Worksheet


def find_empty_row(ws: Worksheet, start: int, end: int, key_col: int) -> int | None:
    """First row in [start, end] whose key_col cell is empty, or None if full."""
    for row in range(start, end + 1):
        if ws.cell(row=row, column=key_col).value is None:
            return row
    return None


def find_next_open_row(ws: Worksheet, start: int, key_col: int) -> int:
    """First empty row at or after `start`, scanning without an upper bound.
    Reuses gaps left by earlier deletes rather than always growing the sheet."""
    row = start
    while ws.cell(row=row, column=key_col).value is not None:
        row += 1
    return row
