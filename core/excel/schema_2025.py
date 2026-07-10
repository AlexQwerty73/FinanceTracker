"""
core/excel/schema_2025.py — adapter for the legacy 2025 workbook layout.
Archival year: transactions are rarely added, but backdated entries must
still work.

Month sheets: header row 3, data rows 4-103 (SUMIF totals cap at row 103).
Columns: A Category, B Type, C Amount, D Notes — no Date column, no
Payment type. "Total investments" only sums category "Crypto" (matching the
sheet's own formula, not "Stocks" too, even though Stocks is a category).

Categories sheet: flat list, A1:A26, no header. No dedicated Types list —
the three types actually used across the workbook are hardcoded below.
There's a single source of truth per transaction (the month sheet row
itself), so edit/delete need no cross-sheet content matching.
"""
from __future__ import annotations

from datetime import date as Date

from . import workbook_io
from ._formula import amount_value
from ._rows import find_empty_row
from .base import MONTH_NAMES, SheetFullError, TransactionNotFoundError, YearSchema

DATA_START_ROW = 4
MAX_DATA_ROW = 103  # binding constraint: SUMIF($B$4:$B$103,...) totals

COL_CATEGORY, COL_TYPE, COL_AMOUNT, COL_NOTES = range(1, 5)

CATEGORIES_SHEET = "Categories"

TYPES = ["Income", "Expenses", "Savings"]
INVEST_CATEGORIES = {"Crypto"}
INCOME_TYPE, EXPENSE_TYPE = "Income", "Expenses"


class Schema2025(YearSchema):
    EXPENSE_TYPE = EXPENSE_TYPE

    def get_categories(self) -> list[str]:
        wb = workbook_io.load(self.file_path, data_only=False)
        ws = wb[CATEGORIES_SHEET]
        values: list[str] = []
        row = 1
        while True:
            v = ws.cell(row=row, column=1).value
            if v is None:
                break
            values.append(str(v).strip())
            row += 1
        return values

    def get_types(self) -> list[str]:
        return list(TYPES)

    # ── internal: operate on an already-open workbook, no load/save ────────

    def _write_transaction(
        self, wb, date: Date, type_: str, category: str, amount: float,
        payment_type: str | None, note: str,
    ) -> None:
        ws = wb[MONTH_NAMES[date.month - 1]]
        row = find_empty_row(ws, DATA_START_ROW, MAX_DATA_ROW, COL_CATEGORY)
        if row is None:
            raise SheetFullError(
                f"{MONTH_NAMES[date.month - 1]} {date.year} is full "
                f"(max {MAX_DATA_ROW - DATA_START_ROW + 1} transactions) — "
                f"can't add another row without breaking the sheet's formulas."
            )

        ws.cell(row=row, column=COL_CATEGORY).value = category
        ws.cell(row=row, column=COL_TYPE).value = type_
        ws.cell(row=row, column=COL_AMOUNT).value = amount
        ws.cell(row=row, column=COL_NOTES).value = note

    def _clear_transaction(self, wb, tx: dict) -> None:
        ws = wb[tx["month"]]
        row = tx["_row"]
        if not (
            ws.cell(row=row, column=COL_TYPE).value == tx["type"]
            and ws.cell(row=row, column=COL_CATEGORY).value == tx["category"]
        ):
            raise TransactionNotFoundError(
                "This transaction no longer matches what's in the file (it may "
                "have changed externally). Refresh the dashboard and try again."
            )
        for col in range(COL_CATEGORY, COL_NOTES + 1):
            ws.cell(row=row, column=col).value = None

    # ── public API ──────────────────────────────────────────────────────

    def add_transaction(
        self, date: Date, type_: str, category: str, amount: float,
        payment_type: str | None, note: str,
    ) -> None:
        wb = workbook_io.load(self.file_path, data_only=False)
        self._write_transaction(wb, date, type_, category, amount, payment_type, note)
        workbook_io.save(wb, self.file_path)

    def update_transaction(
        self, tx: dict, date: Date, type_: str, category: str, amount: float,
        payment_type: str | None, note: str,
    ) -> None:
        wb = workbook_io.load(self.file_path, data_only=False)
        self._clear_transaction(wb, tx)
        self._write_transaction(wb, date, type_, category, amount, payment_type, note)
        workbook_io.save(wb, self.file_path)

    def delete_transaction(self, tx: dict) -> None:
        wb = workbook_io.load(self.file_path, data_only=False)
        self._clear_transaction(wb, tx)
        workbook_io.save(wb, self.file_path)

    def month_summary(self, month: int) -> dict:
        wb = workbook_io.load(self.file_path, data_only=False)
        ws = wb[MONTH_NAMES[month - 1]]

        income = expense = invest = 0.0
        for row in range(DATA_START_ROW, MAX_DATA_ROW + 1):
            t = ws.cell(row=row, column=COL_TYPE).value
            if t is None:
                continue
            amount = amount_value(ws.cell(row=row, column=COL_AMOUNT).value) or 0
            category = ws.cell(row=row, column=COL_CATEGORY).value
            if t == INCOME_TYPE:
                income += amount
            elif t == EXPENSE_TYPE:
                expense += amount
            if category in INVEST_CATEGORIES:
                invest += amount

        return {
            "income": income,
            "expense": expense,
            "invest": invest,
            "balance": income - expense,
        }

    def transactions_for_month(self, month: int) -> list[dict]:
        wb = workbook_io.load(self.file_path, data_only=False)
        month_name = MONTH_NAMES[month - 1]
        ws = wb[month_name]

        result = []
        for row in range(DATA_START_ROW, MAX_DATA_ROW + 1):
            category = ws.cell(row=row, column=COL_CATEGORY).value
            if category is None:
                continue
            result.append({
                "_row": row,
                "month": month_name,
                "date": None,
                "type": ws.cell(row=row, column=COL_TYPE).value,
                "category": category,
                "amount": amount_value(ws.cell(row=row, column=COL_AMOUNT).value) or 0,
                "note": ws.cell(row=row, column=COL_NOTES).value or "",
            })
        result.reverse()  # no date column — row order (append order) is the best ordering signal
        return result
