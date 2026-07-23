"""
core/excel/schema_2026.py — adapter for the 2026+ workbook layout.

Month sheets: header row 1, data rows 2-54 (every SUMIF/SUMIFS total on the
sheet caps its range at row 54 — writing past it would silently fall outside
the formulas). Columns: A Date, B Type, C Category, D Amount, E Net Change
(growing-range SUMIFS, generated per row), F Payment type, G Notes.

AllData: open-ended transaction log mirroring every row added to a month
sheet. Columns: A Date, B Type, C Category, D Amount, E Net Change (simpler
SUMIFS, no EOMONTH clamp). It has no Payment type / Notes columns and no
back-reference to its source row, so relocating a mirror row for edit/delete
is done by content match (date + type + category + amount) rather than by
row number — the month sheet is always the source of truth for the exact row.

Lists: Categories in A2:A16, Types in B2:B4, Payment type in C2:C3.
"""
from __future__ import annotations

from datetime import date as Date, datetime

from . import workbook_io
from ._formula import amount_value
from ._match import amounts_close, same_date
from ._rows import find_empty_row, find_next_open_row
from .base import (
    CategoryExistsError, CategoryInUseError, MONTH_NAMES, SheetFullError, TransactionNotFoundError, YearSchema,
)

DATA_START_ROW = 2
MAX_DATA_ROW = 54  # binding constraint: SUMIF(B2:B54,...) totals

COL_DATE, COL_TYPE, COL_CATEGORY, COL_AMOUNT, COL_NET, COL_PAYMENT, COL_NOTES = range(1, 8)

ALLDATA_SHEET = "AllData"
ALL_COL_DATE, ALL_COL_TYPE, ALL_COL_CATEGORY, ALL_COL_AMOUNT, ALL_COL_NET = range(1, 6)

LISTS_SHEET = "Lists"
LISTS_CATEGORIES_COL, LISTS_TYPES_COL, LISTS_PAYMENT_COL = 1, 2, 3

INVEST_CATEGORIES = {"Crypto", "Stocks"}
INCOME_TYPE, EXPENSE_TYPE = "Income", "Expense"
CASH_IN_TYPE = "To Cash"  # matches the sheet's own Q10 cash-in formula


def _read_list_column(ws, col: int) -> list[str]:
    values: list[str] = []
    row = 2
    while True:
        v = ws.cell(row=row, column=col).value
        if v is None:
            break
        values.append(str(v))
        row += 1
    return values


def _remove_list_row(ws, col: int, name: str) -> None:
    """Shift every row after `name`'s row up by one — Lists columns are
    packed, no-gap lists (_read_list_column reads until the first blank
    cell), so removing an entry means closing the gap, not just blanking
    it. Only touches `col` — Lists packs Categories/Types/Payment type
    into independent columns on the same sheet, each its own length."""
    row = 2
    target_row = None
    while ws.cell(row=row, column=col).value is not None:
        if str(ws.cell(row=row, column=col).value) == name:
            target_row = row
            break
        row += 1
    if target_row is None:
        return
    r = target_row
    while ws.cell(row=r + 1, column=col).value is not None:
        ws.cell(row=r, column=col).value = ws.cell(row=r + 1, column=col).value
        r += 1
    ws.cell(row=r, column=col).value = None


def _month_net_change_formula(row: int) -> str:
    return (
        f'=SUMIFS($D$2:D{row}, $A$2:A{row}, ">"&EOMONTH(A{row},-1), $B$2:B{row}, "Income")'
        f' - SUMIFS($D$2:D{row}, $A$2:A{row}, ">"&EOMONTH(A{row},-1), $B$2:B{row}, "Expense")'
    )


def _alldata_net_change_formula(row: int) -> str:
    return f'=SUMIFS($D$2:D{row}, $B$2:B{row}, "Income") - SUMIFS($D$2:D{row}, $B$2:B{row}, "Expense")'


def _find_alldata_row_by_content(ws_all, date_val, type_: str, category: str, amount: float) -> int | None:
    end = max(ws_all.max_row, DATA_START_ROW)
    for row in range(DATA_START_ROW, end + 1):
        d = ws_all.cell(row=row, column=ALL_COL_DATE).value
        if d is None:
            continue
        if (same_date(d, date_val)
                and ws_all.cell(row=row, column=ALL_COL_TYPE).value == type_
                and ws_all.cell(row=row, column=ALL_COL_CATEGORY).value == category
                and amounts_close(amount_value(ws_all.cell(row=row, column=ALL_COL_AMOUNT).value), amount)):
            return row
    return None


class Schema2026(YearSchema):
    EXPENSE_TYPE = EXPENSE_TYPE
    INCOME_TYPE = INCOME_TYPE
    CASH_IN_TYPE = CASH_IN_TYPE

    def get_categories(self) -> list[str]:
        wb = workbook_io.load(self.file_path, data_only=False)
        return _read_list_column(wb[LISTS_SHEET], LISTS_CATEGORIES_COL)

    def get_types(self) -> list[str]:
        wb = workbook_io.load(self.file_path, data_only=False)
        return _read_list_column(wb[LISTS_SHEET], LISTS_TYPES_COL)

    def get_payment_types(self) -> list[str] | None:
        wb = workbook_io.load(self.file_path, data_only=False)
        return _read_list_column(wb[LISTS_SHEET], LISTS_PAYMENT_COL)

    def add_category(self, name: str) -> None:
        wb = workbook_io.load(self.file_path, data_only=False)
        workbook_io.invalidate(self.file_path)
        ws = wb[LISTS_SHEET]
        existing = _read_list_column(ws, LISTS_CATEGORIES_COL)
        if any(name.lower() == e.lower() for e in existing):
            raise CategoryExistsError(f'Category "{name}" already exists.')
        row = find_next_open_row(ws, 2, LISTS_CATEGORIES_COL)
        ws.cell(row=row, column=LISTS_CATEGORIES_COL).value = name
        workbook_io.save(wb, self.file_path)

    def rename_category(self, old_name: str, new_name: str) -> int:
        wb = workbook_io.load(self.file_path, data_only=False)
        workbook_io.invalidate(self.file_path)
        ws_lists = wb[LISTS_SHEET]
        existing = _read_list_column(ws_lists, LISTS_CATEGORIES_COL)
        if new_name != old_name and any(new_name.lower() == e.lower() for e in existing):
            raise CategoryExistsError(f'Category "{new_name}" already exists.')

        for row in range(2, 2 + len(existing)):
            if ws_lists.cell(row=row, column=LISTS_CATEGORIES_COL).value == old_name:
                ws_lists.cell(row=row, column=LISTS_CATEGORIES_COL).value = new_name
                break

        count = 0
        for month_name in MONTH_NAMES:
            ws = wb[month_name]
            for row in range(DATA_START_ROW, MAX_DATA_ROW + 1):
                if ws.cell(row=row, column=COL_CATEGORY).value == old_name:
                    ws.cell(row=row, column=COL_CATEGORY).value = new_name
                    count += 1

        ws_all = wb[ALLDATA_SHEET]
        end = max(ws_all.max_row, DATA_START_ROW)
        for row in range(DATA_START_ROW, end + 1):
            if ws_all.cell(row=row, column=ALL_COL_CATEGORY).value == old_name:
                ws_all.cell(row=row, column=ALL_COL_CATEGORY).value = new_name

        workbook_io.save(wb, self.file_path)
        return count

    def delete_category(self, name: str) -> None:
        wb = workbook_io.load(self.file_path, data_only=False)
        workbook_io.invalidate(self.file_path)
        ws_lists = wb[LISTS_SHEET]
        if name not in _read_list_column(ws_lists, LISTS_CATEGORIES_COL):
            raise ValueError(f'Category "{name}" does not exist.')

        count = 0
        for month_name in MONTH_NAMES:
            ws = wb[month_name]
            for row in range(DATA_START_ROW, MAX_DATA_ROW + 1):
                if ws.cell(row=row, column=COL_CATEGORY).value == name:
                    count += 1
        if count > 0:
            raise CategoryInUseError(
                f'Category "{name}" is used by {count} transaction(s) — merge it into another category first.'
            )

        _remove_list_row(ws_lists, LISTS_CATEGORIES_COL, name)
        workbook_io.save(wb, self.file_path)

    def merge_category(self, source: str, target: str) -> int:
        if source == target:
            raise ValueError("Source and target categories must be different.")
        wb = workbook_io.load(self.file_path, data_only=False)
        workbook_io.invalidate(self.file_path)
        ws_lists = wb[LISTS_SHEET]
        existing = _read_list_column(ws_lists, LISTS_CATEGORIES_COL)
        if source not in existing:
            raise ValueError(f'Category "{source}" does not exist.')
        if target not in existing:
            raise ValueError(f'Category "{target}" does not exist.')

        count = 0
        for month_name in MONTH_NAMES:
            ws = wb[month_name]
            for row in range(DATA_START_ROW, MAX_DATA_ROW + 1):
                if ws.cell(row=row, column=COL_CATEGORY).value == source:
                    ws.cell(row=row, column=COL_CATEGORY).value = target
                    count += 1

        ws_all = wb[ALLDATA_SHEET]
        end = max(ws_all.max_row, DATA_START_ROW)
        for row in range(DATA_START_ROW, end + 1):
            if ws_all.cell(row=row, column=ALL_COL_CATEGORY).value == source:
                ws_all.cell(row=row, column=ALL_COL_CATEGORY).value = target

        _remove_list_row(ws_lists, LISTS_CATEGORIES_COL, source)
        workbook_io.save(wb, self.file_path)
        return count

    def reorder_categories(self, new_order: list[str]) -> None:
        if sorted(new_order) != sorted(self.get_categories()):
            raise ValueError("New order must contain exactly the same categories.")
        wb = workbook_io.load(self.file_path, data_only=False)
        workbook_io.invalidate(self.file_path)
        ws_lists = wb[LISTS_SHEET]
        for i, name in enumerate(new_order):
            ws_lists.cell(row=2 + i, column=LISTS_CATEGORIES_COL).value = name
        workbook_io.save(wb, self.file_path)

    # ── internal: operate on an already-open workbook, no load/save ────────

    def _write_transaction(
        self, wb, date: Date, type_: str, category: str, amount: float,
        payment_type: str | None, note: str,
    ) -> None:
        ws = wb[MONTH_NAMES[date.month - 1]]
        row = find_empty_row(ws, DATA_START_ROW, MAX_DATA_ROW, COL_DATE)
        if row is None:
            raise SheetFullError(
                f"{MONTH_NAMES[date.month - 1]} {date.year} is full "
                f"(max {MAX_DATA_ROW - DATA_START_ROW + 1} transactions) — "
                f"can't add another row without breaking the sheet's formulas."
            )

        dt = datetime(date.year, date.month, date.day)
        ws.cell(row=row, column=COL_DATE).value = dt
        ws.cell(row=row, column=COL_TYPE).value = type_
        ws.cell(row=row, column=COL_CATEGORY).value = category
        ws.cell(row=row, column=COL_AMOUNT).value = amount
        ws.cell(row=row, column=COL_NET).value = _month_net_change_formula(row)
        ws.cell(row=row, column=COL_PAYMENT).value = payment_type
        ws.cell(row=row, column=COL_NOTES).value = note

        ws_all = wb[ALLDATA_SHEET]
        row_all = find_next_open_row(ws_all, DATA_START_ROW, ALL_COL_DATE)
        ws_all.cell(row=row_all, column=ALL_COL_DATE).value = dt
        ws_all.cell(row=row_all, column=ALL_COL_TYPE).value = type_
        ws_all.cell(row=row_all, column=ALL_COL_CATEGORY).value = category
        ws_all.cell(row=row_all, column=ALL_COL_AMOUNT).value = amount
        ws_all.cell(row=row_all, column=ALL_COL_NET).value = _alldata_net_change_formula(row_all)

    def _clear_transaction(self, wb, tx: dict) -> None:
        ws = wb[MONTH_NAMES[tx["date"].month - 1]]
        row = tx["_row"]
        if not (
            same_date(ws.cell(row=row, column=COL_DATE).value, tx["date"])
            and ws.cell(row=row, column=COL_TYPE).value == tx["type"]
            and ws.cell(row=row, column=COL_CATEGORY).value == tx["category"]
        ):
            raise TransactionNotFoundError(
                "This transaction no longer matches what's in the file (it may "
                "have changed externally). Refresh the dashboard and try again."
            )
        for col in range(COL_DATE, COL_NOTES + 1):
            ws.cell(row=row, column=col).value = None

        ws_all = wb[ALLDATA_SHEET]
        row_all = _find_alldata_row_by_content(ws_all, tx["date"], tx["type"], tx["category"], tx["amount"])
        if row_all is not None:
            for col in range(ALL_COL_DATE, ALL_COL_NET + 1):
                ws_all.cell(row=row_all, column=col).value = None

    # ── public API ──────────────────────────────────────────────────────

    def add_transaction(
        self, date: Date, type_: str, category: str, amount: float,
        payment_type: str | None, note: str, currency: str | None = None, rate: float | None = None,
    ) -> None:
        # currency/rate are unused here — 2026 has no multi-currency concept,
        # kept only so callers can pass them uniformly across every schema.
        wb = workbook_io.load(self.file_path, data_only=False)
        workbook_io.invalidate(self.file_path)
        self._write_transaction(wb, date, type_, category, amount, payment_type, note)
        workbook_io.save(wb, self.file_path)

    def update_transaction(
        self, tx: dict, date: Date, type_: str, category: str, amount: float,
        payment_type: str | None, note: str, currency: str | None = None, rate: float | None = None,
    ) -> None:
        wb = workbook_io.load(self.file_path, data_only=False)
        workbook_io.invalidate(self.file_path)
        self._clear_transaction(wb, tx)
        self._write_transaction(wb, date, type_, category, amount, payment_type, note)
        workbook_io.save(wb, self.file_path)

    def delete_transaction(self, tx: dict) -> None:
        wb = workbook_io.load(self.file_path, data_only=False)
        workbook_io.invalidate(self.file_path)
        self._clear_transaction(wb, tx)
        workbook_io.save(wb, self.file_path)

    def month_summary(self, month: int) -> dict:
        wb = workbook_io.load(self.file_path, data_only=False)
        ws = wb[MONTH_NAMES[month - 1]]

        income = expense = invest = cash = 0.0
        for row in range(DATA_START_ROW, MAX_DATA_ROW + 1):
            t = ws.cell(row=row, column=COL_TYPE).value
            if t is None:
                continue
            amount = amount_value(ws.cell(row=row, column=COL_AMOUNT).value) or 0
            category = ws.cell(row=row, column=COL_CATEGORY).value
            payment = ws.cell(row=row, column=COL_PAYMENT).value
            if t == INCOME_TYPE:
                income += amount
            elif t == EXPENSE_TYPE:
                expense += amount
            if category in INVEST_CATEGORIES:
                invest += amount

            if self.is_cash_in_type(t):
                cash += amount
            elif t == EXPENSE_TYPE and payment == "Cash":
                cash -= amount

        balance = income - expense
        has_tracking = self.has_cash_tracking()
        return {
            "income": income,
            "expense": expense,
            "invest": invest,
            "balance": balance,
            "cash": cash if has_tracking else None,
            # See Schema2025.month_summary — card is derived (balance minus
            # cash), not tagged from individual rows.
            "card": (balance - cash) if has_tracking else None,
        }

    def transactions_for_month(self, month: int) -> list[dict]:
        wb = workbook_io.load(self.file_path, data_only=False)
        month_name = MONTH_NAMES[month - 1]
        ws = wb[month_name]

        result = []
        for row in range(DATA_START_ROW, MAX_DATA_ROW + 1):
            d = ws.cell(row=row, column=COL_DATE).value
            if d is None:
                continue
            result.append({
                "_row": row,
                "month": month_name,
                "date": d,
                "type": ws.cell(row=row, column=COL_TYPE).value,
                "category": ws.cell(row=row, column=COL_CATEGORY).value,
                "amount": amount_value(ws.cell(row=row, column=COL_AMOUNT).value) or 0,
                "payment_type": ws.cell(row=row, column=COL_PAYMENT).value,
                "note": ws.cell(row=row, column=COL_NOTES).value or "",
            })
        result.sort(key=lambda tx: (tx["date"], tx["_row"]), reverse=True)
        return result
