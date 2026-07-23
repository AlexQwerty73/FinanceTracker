"""
core/excel/transaction_reader.py — pure row-reading: given an open month
worksheet and a schema's column map, returns every transaction row as a
plain dict. Split out from DynamicSchema so "how do I read a transaction
row" is one small, independently testable place (see
feedback_modular_structure.md) rather than mixed into a large schema
class. No writing, no PyQt — just cells in, dicts out.
"""
from __future__ import annotations

from datetime import date as Date, datetime

from ._formula import amount_value
from .template_model import (
    ROLE_AMOUNT, ROLE_BASE_AMOUNT, ROLE_CATEGORY, ROLE_CURRENCY, ROLE_DATE, ROLE_NOTES,
    ROLE_PAYMENT, ROLE_RATE, ROLE_TYPE,
)

DATA_START_ROW = 2
MAX_DATA_ROW = 500  # generous — no real formula ties this down for a fresh custom file


def read_month(ws, col: dict[str, int], month_name: str) -> list[dict]:
    """Every transaction row in `ws`, positioned per `col` (a role -> 1-
    based column map, e.g. DynamicSchema._col) — newest first."""
    date_col, payment_col, currency_col = col.get(ROLE_DATE), col.get(ROLE_PAYMENT), col.get(ROLE_CURRENCY)
    notes_col, rate_col, base_col = col.get(ROLE_NOTES), col.get(ROLE_RATE), col.get(ROLE_BASE_AMOUNT)

    result = []
    for row in range(DATA_START_ROW, MAX_DATA_ROW + 1):
        category = ws.cell(row=row, column=col[ROLE_CATEGORY]).value
        if category is None:
            continue
        result.append({
            "_row": row, "month": month_name,
            "date": ws.cell(row=row, column=date_col).value if date_col else None,
            "type": ws.cell(row=row, column=col[ROLE_TYPE]).value,
            "category": category,
            "amount": amount_value(ws.cell(row=row, column=col[ROLE_AMOUNT]).value) or 0,
            "payment_type": (ws.cell(row=row, column=payment_col).value or None) if payment_col else None,
            "currency": (ws.cell(row=row, column=currency_col).value or None) if currency_col else None,
            "note": (ws.cell(row=row, column=notes_col).value or "") if notes_col else "",
            # The table's own persisted Rate/Amount(base currency) -- None if
            # the role doesn't exist, or this row has nothing pinned yet
            # (e.g. entered directly in Excel, not through the app). Prefer
            # DynamicSchema.convert_transaction(tx) over reading these
            # directly unless you specifically want "only if pinned."
            "rate": amount_value(ws.cell(row=row, column=rate_col).value) if rate_col else None,
            "base_amount": amount_value(ws.cell(row=row, column=base_col).value) if base_col else None,
        })
    if date_col:
        # A row with a blank/garbled date (a real error a spreadsheet edit
        # can introduce -- see transaction_validator.py) must not crash the
        # sort: group real dates first (newest first, tiebroken by row),
        # anything invalid sorts after, in row order. Normalize datetime to
        # date too -- openpyxl usually yields datetime, but a bare date
        # slipping in (e.g. via an external tool) would otherwise crash the
        # comparison (datetime and date don't compare to each other).
        valid = lambda d: isinstance(d, (Date, datetime))
        norm = lambda d: d.date() if isinstance(d, datetime) else d
        result.sort(key=lambda tx: (valid(tx["date"]), norm(tx["date"]) if valid(tx["date"]) else 0, tx["_row"]), reverse=True)
    else:
        result.reverse()  # no date column — row order (append order) is the best signal
    return result
