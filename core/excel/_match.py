"""
core/excel/_match.py — small comparison helpers used to relocate a
transaction's AllData mirror row by content (date/type/category/amount),
since AllData doesn't store a back-reference to its source row.
"""
from __future__ import annotations

from datetime import date as Date, datetime


def same_date(a, b) -> bool:
    if a is None or b is None:
        return False
    da = a.date() if isinstance(a, datetime) else a
    db = b.date() if isinstance(b, datetime) else b
    return da == db


def amounts_close(a: float | None, b: float | None, eps: float = 1e-6) -> bool:
    if a is None or b is None:
        return False
    return abs(a - b) < eps
