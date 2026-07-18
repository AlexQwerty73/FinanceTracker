"""
core/excel/schema_dynamic.py — DynamicSchema: reads/writes a workbook
generated from a user-configurable Template (core/excel/template_model.py)
instead of a hardcoded column layout. One instance per (file, template)
pair, constructed by the registry once it resolves a year's registered
template id to something other than the two fixed presets.

Column positions come from template.columns (an ordered list of roles)
rather than module-level constants — everything else (row scanning,
formula-free Amount parsing, save/load) reuses the exact same helpers
Schema2025/Schema2026 already use, so this is deliberately close to a
parameterized version of schema_2025.py's simpler (no-AllData-mirror)
approach.

Scope, per the approved plan: no Excel-native Totals/SUMIF block, no
AllData-style mirror log, cash-out is payment-based only (no legacy
type-based hack). Investment tracking mirrors Schema2025/Schema2026's
category-membership approach (a fixed set of category names counts
toward "invest" regardless of Income/Expense type), just sourced from
template.invest_categories instead of a module constant.
"""
from __future__ import annotations

from datetime import date as Date, datetime

from . import workbook_io
from ._formula import amount_value
from ._rows import find_empty_row
from .base import CategoryExistsError, MONTH_NAMES, SheetFullError, TransactionNotFoundError, YearSchema
from .template_model import (
    ROLE_AMOUNT, ROLE_CATEGORY, ROLE_CURRENCY, ROLE_DATE, ROLE_NOTES, ROLE_PAYMENT, ROLE_TYPE, Template,
)

DATA_START_ROW = 2
MAX_DATA_ROW = 500  # generous — no real formula ties this down for a fresh custom file

LISTS_SHEET = "Lists"
LISTS_CATEGORIES_COL, LISTS_TYPES_COL, LISTS_PAYMENT_COL = 1, 2, 3
LISTS_CURRENCY_COL = 4  # currency codes list (dropdown source)
LISTS_RATE_CURRENCY_COL, LISTS_RATE_VALUE_COL = 8, 9  # small Currency -> Rate table, columns H:I


class DynamicSchema(YearSchema):
    def __init__(self, file_path, year: int, template: Template):
        super().__init__(file_path, year)
        self.template = template
        self.EXPENSE_TYPE = template.expense_type
        self.INCOME_TYPE = template.income_type
        self.CASH_IN_TYPE = template.cash_in_type
        self.HAS_DAILY_DATES = template.has_daily_dates()
        self.INVEST_CATEGORIES = set(template.invest_categories or [])
        self._col = {role: i + 1 for i, role in enumerate(template.columns)}

    def get_payment_types(self) -> list[str] | None:
        if ROLE_PAYMENT not in self._col:
            return None
        return list(self.template.payment_types or [])

    def get_currencies(self) -> list[str] | None:
        if ROLE_CURRENCY not in self._col:
            return None
        return list(self.template.currencies or [])

    def get_base_currency(self) -> str | None:
        if ROLE_CURRENCY not in self._col:
            return None
        return self.template.base_currency

    def to_base_amount(self, amount: float, currency: str | None) -> float:
        if ROLE_CURRENCY not in self._col:
            return amount
        return self._convert(amount, currency, self._read_rates())

    def get_rates(self) -> dict[str, float] | None:
        if ROLE_CURRENCY not in self._col:
            return None
        return self._read_rates()

    def _convert(self, amount: float, currency: str | None, rates: dict[str, float]) -> float:
        if not currency or currency == self.template.base_currency:
            return amount
        rate = rates.get(currency)
        # unknown/blank rate — don't crash, don't silently zero the
        # transaction out; treat it as unconverted until the user fills
        # in a real rate on the Lists sheet.
        return amount * rate if rate is not None else amount

    def _read_rates(self) -> dict[str, float]:
        wb = workbook_io.load(self.file_path, data_only=False)
        ws = wb[LISTS_SHEET]
        rates: dict[str, float] = {}
        row = 2
        while True:
            code = ws.cell(row=row, column=LISTS_RATE_CURRENCY_COL).value
            if code is None:
                break
            val = ws.cell(row=row, column=LISTS_RATE_VALUE_COL).value
            if isinstance(val, (int, float)):
                rates[str(code).strip()] = float(val)
            row += 1
        return rates

    # ── Lists sheet (Categories/Types/Payment) ──────────────────────────

    def get_categories(self) -> list[str]:
        wb = workbook_io.load(self.file_path, data_only=False)
        return self._read_list_column(wb[LISTS_SHEET], LISTS_CATEGORIES_COL)

    def get_types(self) -> list[str]:
        wb = workbook_io.load(self.file_path, data_only=False)
        return self._read_list_column(wb[LISTS_SHEET], LISTS_TYPES_COL)

    @staticmethod
    def _read_list_column(ws, col: int) -> list[str]:
        values: list[str] = []
        row = 2  # row 1 is the "Categories"/"Types"/"Payment type" header
        while True:
            v = ws.cell(row=row, column=col).value
            if v is None:
                break
            values.append(str(v).strip())
            row += 1
        return values

    def add_category(self, name: str) -> None:
        wb = workbook_io.load(self.file_path, data_only=False)
        workbook_io.invalidate(self.file_path)
        ws = wb[LISTS_SHEET]
        row = 2
        while ws.cell(row=row, column=LISTS_CATEGORIES_COL).value is not None:
            if str(ws.cell(row=row, column=LISTS_CATEGORIES_COL).value).strip().lower() == name.lower():
                raise CategoryExistsError(f'Category "{name}" already exists.')
            row += 1
        ws.cell(row=row, column=LISTS_CATEGORIES_COL).value = name
        workbook_io.save(wb, self.file_path)

    def rename_category(self, old_name: str, new_name: str) -> int:
        wb = workbook_io.load(self.file_path, data_only=False)
        workbook_io.invalidate(self.file_path)
        ws_lists = wb[LISTS_SHEET]

        row = 2
        rename_row = None
        while ws_lists.cell(row=row, column=LISTS_CATEGORIES_COL).value is not None:
            v = str(ws_lists.cell(row=row, column=LISTS_CATEGORIES_COL).value).strip()
            if new_name != old_name and v.lower() == new_name.lower():
                raise CategoryExistsError(f'Category "{new_name}" already exists.')
            if v == old_name:
                rename_row = row
            row += 1
        if rename_row is not None:
            ws_lists.cell(row=rename_row, column=LISTS_CATEGORIES_COL).value = new_name

        count = 0
        cat_col = self._col[ROLE_CATEGORY]
        for month_name in MONTH_NAMES:
            ws = wb[month_name]
            for r in range(DATA_START_ROW, MAX_DATA_ROW + 1):
                if ws.cell(row=r, column=cat_col).value == old_name:
                    ws.cell(row=r, column=cat_col).value = new_name
                    count += 1

        workbook_io.save(wb, self.file_path)
        return count

    # ── internal: operate on an already-open workbook, no load/save ────────

    def _write_transaction(
        self, wb, date: Date, type_: str, category: str, amount: float,
        payment_type: str | None, note: str, currency: str | None = None,
    ) -> None:
        ws = wb[MONTH_NAMES[date.month - 1]]
        row = find_empty_row(ws, DATA_START_ROW, MAX_DATA_ROW, self._col[ROLE_CATEGORY])
        if row is None:
            raise SheetFullError(
                f"{MONTH_NAMES[date.month - 1]} {date.year} is full "
                f"(max {MAX_DATA_ROW - DATA_START_ROW + 1} transactions)."
            )

        if ROLE_DATE in self._col:
            ws.cell(row=row, column=self._col[ROLE_DATE]).value = datetime(date.year, date.month, date.day)
        ws.cell(row=row, column=self._col[ROLE_CATEGORY]).value = category
        ws.cell(row=row, column=self._col[ROLE_TYPE]).value = type_
        ws.cell(row=row, column=self._col[ROLE_AMOUNT]).value = amount
        if ROLE_PAYMENT in self._col:
            ws.cell(row=row, column=self._col[ROLE_PAYMENT]).value = payment_type
        if ROLE_CURRENCY in self._col:
            ws.cell(row=row, column=self._col[ROLE_CURRENCY]).value = currency
        if ROLE_NOTES in self._col:
            ws.cell(row=row, column=self._col[ROLE_NOTES]).value = note

    def _clear_transaction(self, wb, tx: dict) -> None:
        ws = wb[tx["month"]]
        row = tx["_row"]
        if not (
            ws.cell(row=row, column=self._col[ROLE_TYPE]).value == tx["type"]
            and ws.cell(row=row, column=self._col[ROLE_CATEGORY]).value == tx["category"]
        ):
            raise TransactionNotFoundError(
                "This transaction no longer matches what's in the file (it may "
                "have changed externally). Refresh the dashboard and try again."
            )
        for col in self._col.values():
            ws.cell(row=row, column=col).value = None

    # ── public API ──────────────────────────────────────────────────────

    def add_transaction(
        self, date: Date, type_: str, category: str, amount: float,
        payment_type: str | None, note: str, currency: str | None = None,
    ) -> None:
        wb = workbook_io.load(self.file_path, data_only=False)
        workbook_io.invalidate(self.file_path)
        self._write_transaction(wb, date, type_, category, amount, payment_type, note, currency)
        workbook_io.save(wb, self.file_path)

    def update_transaction(
        self, tx: dict, date: Date, type_: str, category: str, amount: float,
        payment_type: str | None, note: str, currency: str | None = None,
    ) -> None:
        wb = workbook_io.load(self.file_path, data_only=False)
        workbook_io.invalidate(self.file_path)
        self._clear_transaction(wb, tx)
        self._write_transaction(wb, date, type_, category, amount, payment_type, note, currency)
        workbook_io.save(wb, self.file_path)

    def delete_transaction(self, tx: dict) -> None:
        wb = workbook_io.load(self.file_path, data_only=False)
        workbook_io.invalidate(self.file_path)
        self._clear_transaction(wb, tx)
        workbook_io.save(wb, self.file_path)

    def month_summary(self, month: int) -> dict:
        wb = workbook_io.load(self.file_path, data_only=False)
        ws = wb[MONTH_NAMES[month - 1]]
        type_col, amount_col = self._col[ROLE_TYPE], self._col[ROLE_AMOUNT]
        cat_col = self._col[ROLE_CATEGORY]
        payment_col = self._col.get(ROLE_PAYMENT)
        currency_col = self._col.get(ROLE_CURRENCY)
        rates = self._read_rates() if currency_col else None

        income = expense = invest = cash = 0.0
        for row in range(DATA_START_ROW, MAX_DATA_ROW + 1):
            t = ws.cell(row=row, column=type_col).value
            if t is None:
                continue
            amount = amount_value(ws.cell(row=row, column=amount_col).value) or 0
            category = ws.cell(row=row, column=cat_col).value
            payment = ws.cell(row=row, column=payment_col).value if payment_col else None
            if currency_col:
                currency = ws.cell(row=row, column=currency_col).value
                amount = self._convert(amount, currency, rates)

            if self.is_income_type(t):
                income += amount
            elif self.is_expense_type(t):
                expense += amount
            if category in self.INVEST_CATEGORIES:
                invest += amount

            if self.is_cash_in_type(t):
                cash += amount
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
            "card": (balance - cash) if has_tracking else None,
        }

    def transactions_for_month(self, month: int) -> list[dict]:
        wb = workbook_io.load(self.file_path, data_only=False)
        month_name = MONTH_NAMES[month - 1]
        ws = wb[month_name]
        cat_col = self._col[ROLE_CATEGORY]
        date_col = self._col.get(ROLE_DATE)
        payment_col = self._col.get(ROLE_PAYMENT)
        currency_col = self._col.get(ROLE_CURRENCY)
        notes_col = self._col.get(ROLE_NOTES)

        result = []
        for row in range(DATA_START_ROW, MAX_DATA_ROW + 1):
            category = ws.cell(row=row, column=cat_col).value
            if category is None:
                continue
            result.append({
                "_row": row,
                "month": month_name,
                "date": ws.cell(row=row, column=date_col).value if date_col else None,
                "type": ws.cell(row=row, column=self._col[ROLE_TYPE]).value,
                "category": category,
                "amount": amount_value(ws.cell(row=row, column=self._col[ROLE_AMOUNT]).value) or 0,
                "payment_type": (ws.cell(row=row, column=payment_col).value or None) if payment_col else None,
                "currency": (ws.cell(row=row, column=currency_col).value or None) if currency_col else None,
                "note": (ws.cell(row=row, column=notes_col).value or "") if notes_col else "",
            })
        if date_col:
            result.sort(key=lambda tx: (tx["date"], tx["_row"]), reverse=True)
        else:
            result.reverse()  # no date column — row order (append order) is the best signal
        return result
