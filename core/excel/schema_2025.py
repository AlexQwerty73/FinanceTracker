"""
core/excel/schema_2025.py — adapter for the legacy 2025 workbook layout.
Archival year: transactions are rarely added, but backdated entries must
still work.

Month sheets: header row 3, data rows 4-103 (SUMIF totals cap at row 103).
Original columns: A Category, B Type, C Amount, D Notes — no Date column.
Column E was blank on every month sheet (a spacer before the "Totals"
summary block that starts at F) so a Payment type column ("Cash"/"Card",
matching 2026's) was added there — this is new, not in the original sheet,
written lazily: the header only appears on a given month's sheet once a
transaction is first written to it via the app. "Total investments" only
sums category "Crypto" (matching the sheet's own formula, not "Stocks"
too, even though Stocks is a category).

Categories sheet: flat list, A1:A26, no header. No dedicated Types list —
the four types the app offers are hardcoded below: three original
("Income", "Expenses", "Savings") plus "Cash Expense", added here (not in
the original sheet). It predates the Payment type column above and is kept
for backward compatibility, but Payment type is now the more direct way to
mark a cash expense (Type "Expenses" + Payment "Cash", same as 2026) —
either way is recognized by is_cash_out_type()/is_expense_type()+payment
checks elsewhere in the app. Caveat: the sheet's own "Total Expenses"
formula (SUMIF on "Expenses" only) won't include rows typed "Cash Expense",
so that cell in Excel will read slightly low — this app's own totals count
both, "Cash Expense" included, correctly.

There's a single source of truth per transaction (the month sheet row
itself), so edit/delete need no cross-sheet content matching.
"""
from __future__ import annotations

from datetime import date as Date

from . import workbook_io
from ._formula import amount_value
from ._rows import find_empty_row
from .base import CategoryExistsError, MONTH_NAMES, SheetFullError, TransactionNotFoundError, YearSchema

DATA_START_ROW = 4
MAX_DATA_ROW = 103  # binding constraint: SUMIF($B$4:$B$103,...) totals

COL_CATEGORY, COL_TYPE, COL_AMOUNT, COL_NOTES = range(1, 5)
COL_PAYMENT = 5  # column E — added; blank in the original sheet
PAYMENT_HEADER_ROW = DATA_START_ROW - 1  # = 3, same header row as A-D

CATEGORIES_SHEET = "Categories"

INCOME_TYPE, EXPENSE_TYPE, SAVINGS_TYPE, CASH_EXPENSE_TYPE = "Income", "Expenses", "Savings", "Cash Expense"
TYPES = [INCOME_TYPE, EXPENSE_TYPE, SAVINGS_TYPE, CASH_EXPENSE_TYPE]
EXPENSE_TYPES = {EXPENSE_TYPE, CASH_EXPENSE_TYPE}
INVEST_CATEGORIES = {"Crypto"}
CASH_IN_TYPE = SAVINGS_TYPE  # this year's closest equivalent to 2026's "To Cash"
CASH_OUT_TYPE = CASH_EXPENSE_TYPE
PAYMENT_TYPES = ["Cash", "Card"]  # matches 2026's Payment type options


class Schema2025(YearSchema):
    EXPENSE_TYPE = EXPENSE_TYPE
    INCOME_TYPE = INCOME_TYPE
    CASH_IN_TYPE = CASH_IN_TYPE
    HAS_DAILY_DATES = False

    def is_expense_type(self, type_: str) -> bool:
        return type_ in EXPENSE_TYPES

    def is_cash_out_type(self, type_: str) -> bool:
        return type_ == CASH_OUT_TYPE

    def get_payment_types(self) -> list[str] | None:
        return list(PAYMENT_TYPES)

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

    def add_category(self, name: str) -> None:
        wb = workbook_io.load(self.file_path, data_only=False)
        workbook_io.invalidate(self.file_path)
        ws = wb[CATEGORIES_SHEET]
        row = 1
        while ws.cell(row=row, column=1).value is not None:
            if str(ws.cell(row=row, column=1).value).strip().lower() == name.lower():
                raise CategoryExistsError(f'Category "{name}" already exists.')
            row += 1
        ws.cell(row=row, column=1).value = name
        workbook_io.save(wb, self.file_path)

    def rename_category(self, old_name: str, new_name: str) -> int:
        wb = workbook_io.load(self.file_path, data_only=False)
        workbook_io.invalidate(self.file_path)
        ws_cat = wb[CATEGORIES_SHEET]

        row = 1
        rename_row = None
        while ws_cat.cell(row=row, column=1).value is not None:
            v = str(ws_cat.cell(row=row, column=1).value).strip()
            if new_name != old_name and v.lower() == new_name.lower():
                raise CategoryExistsError(f'Category "{new_name}" already exists.')
            if v == old_name:
                rename_row = row
            row += 1
        if rename_row is not None:
            ws_cat.cell(row=rename_row, column=1).value = new_name

        count = 0
        for month_name in MONTH_NAMES:
            ws = wb[month_name]
            for r in range(DATA_START_ROW, MAX_DATA_ROW + 1):
                if ws.cell(row=r, column=COL_CATEGORY).value == old_name:
                    ws.cell(row=r, column=COL_CATEGORY).value = new_name
                    count += 1

        workbook_io.save(wb, self.file_path)
        return count

    # ── internal: operate on an already-open workbook, no load/save ────────

    def _ensure_payment_header(self, ws) -> None:
        if ws.cell(row=PAYMENT_HEADER_ROW, column=COL_PAYMENT).value is None:
            ws.cell(row=PAYMENT_HEADER_ROW, column=COL_PAYMENT).value = "Payment type"

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

        self._ensure_payment_header(ws)
        ws.cell(row=row, column=COL_CATEGORY).value = category
        ws.cell(row=row, column=COL_TYPE).value = type_
        ws.cell(row=row, column=COL_AMOUNT).value = amount
        ws.cell(row=row, column=COL_NOTES).value = note
        ws.cell(row=row, column=COL_PAYMENT).value = payment_type

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
        for col in range(COL_CATEGORY, COL_PAYMENT + 1):
            ws.cell(row=row, column=col).value = None

    # ── public API ──────────────────────────────────────────────────────

    def add_transaction(
        self, date: Date, type_: str, category: str, amount: float,
        payment_type: str | None, note: str,
    ) -> None:
        wb = workbook_io.load(self.file_path, data_only=False)
        workbook_io.invalidate(self.file_path)
        self._write_transaction(wb, date, type_, category, amount, payment_type, note)
        workbook_io.save(wb, self.file_path)

    def update_transaction(
        self, tx: dict, date: Date, type_: str, category: str, amount: float,
        payment_type: str | None, note: str,
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
            if self.is_income_type(t):
                income += amount
            elif self.is_expense_type(t):
                expense += amount
            if category in INVEST_CATEGORIES:
                invest += amount

            if self.is_cash_in_type(t):
                cash += amount
            elif self.is_cash_out_type(t):
                cash -= amount
            elif self.is_expense_type(t) and payment == "Cash":
                cash -= amount

        balance = income - expense
        has_tracking = self.has_cash_tracking()
        return {
            "income": income,
            "expense": expense,
            "invest": invest,
            "balance": balance,
            "cash": cash if has_tracking else None,
            # Card isn't tracked directly (most rows have no recorded
            # payment method) — it's everything else: whatever of the
            # month's balance didn't move through cash. Derived, not
            # tagged, so it always exactly closes the balance = cash+card
            # gap by construction.
            "card": (balance - cash) if has_tracking else None,
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
                "payment_type": ws.cell(row=row, column=COL_PAYMENT).value or None,
                "note": ws.cell(row=row, column=COL_NOTES).value or "",
            })
        result.reverse()  # no date column — row order (append order) is the best ordering signal
        return result
