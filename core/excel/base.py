"""
core/excel/base.py — YearSchema: the interface every year's workbook layout
(2025, 2026, ...) implements. One instance is bound to one year's file.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date as Date
from pathlib import Path

MONTH_NAMES = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]


class SheetFullError(Exception):
    """Raised when a month sheet has no empty row left within its safe range."""


class TransactionNotFoundError(Exception):
    """Raised when a transaction dict no longer matches what's on disk —
    the file changed (externally, or a stale dashboard) since it was read."""


class CategoryExistsError(Exception):
    """Raised when adding a category that (case-insensitively) already exists."""


class CategoryInUseError(Exception):
    """Raised when deleting a category that's still used by at least one
    transaction — merge it into another category, or reassign those
    transactions, first."""


class YearSchema(ABC):
    EXPENSE_TYPE: str = ""
    INCOME_TYPE: str = ""
    CASH_IN_TYPE: str | None = None  # the type that moves money *into* cash (e.g. "To Cash"); None if not tracked
    HAS_DAILY_DATES: bool = True  # False for years with no Date column (e.g. 2025)

    def __init__(self, file_path: Path, year: int):
        self.file_path = file_path
        self.year = year

    def is_expense_type(self, type_: str) -> bool:
        """Whether `type_` counts as an expense (used for charts)."""
        return type_ == self.EXPENSE_TYPE

    def is_income_type(self, type_: str) -> bool:
        """Whether `type_` counts as income (used for charts)."""
        return type_ == self.INCOME_TYPE

    def is_cash_in_type(self, type_: str) -> bool:
        """Whether `type_` moves money into cash (e.g. a "To Cash" transfer —
        matches the sheet's own Q10 cash-in formula, which is NOT the same
        as its Income type)."""
        return self.CASH_IN_TYPE is not None and type_ == self.CASH_IN_TYPE

    def is_cash_out_type(self, type_: str) -> bool:
        """Whether `type_` alone (with no payment-type field to check, e.g.
        2025) identifies a cash expense. Years that track cash via a
        Payment type column instead (e.g. 2026) leave this False always —
        cash-out there is `is_expense_type(type_) and payment_type == "Cash"`."""
        return False

    def has_cash_tracking(self) -> bool:
        """Whether this year's schema can compute a cash-flow figure at all."""
        return self.CASH_IN_TYPE is not None

    @abstractmethod
    def get_categories(self) -> list[str]:
        """Categories for the dropdown, in sheet order."""

    @abstractmethod
    def add_category(self, name: str) -> None:
        """Append a new category. Raises CategoryExistsError if it already exists."""

    @abstractmethod
    def rename_category(self, old_name: str, new_name: str) -> int:
        """Rename a category everywhere it appears (the category list itself,
        every month sheet, and AllData where applicable). Returns the number
        of transaction rows updated. Raises CategoryExistsError if new_name
        already exists as a different category."""

    @abstractmethod
    def delete_category(self, name: str) -> None:
        """Remove a category from the dropdown list. Raises CategoryInUseError
        if any transaction still uses it (merge it into another category, or
        reassign those transactions, first), or ValueError if it doesn't
        exist."""

    @abstractmethod
    def merge_category(self, source: str, target: str) -> int:
        """Reassign every transaction using `source` to `target` (every month
        sheet, and AllData where applicable), then remove `source` from the
        category list. Returns the number of transaction rows updated.
        Raises ValueError if source == target or either name isn't a real
        category."""

    @abstractmethod
    def reorder_categories(self, new_order: list[str]) -> None:
        """Change the order categories appear in (dropdowns, this page's own
        list) to `new_order` — must contain exactly the same categories as
        get_categories(), just reordered. Raises ValueError otherwise."""

    @abstractmethod
    def get_types(self) -> list[str]:
        """Transaction types for the dropdown, in sheet order."""

    def get_payment_types(self) -> list[str] | None:
        """Payment types for the dropdown, or None if this year has no such field."""
        return None

    def get_currencies(self) -> list[str] | None:
        """Currencies for the dropdown, or None if this year has no such field."""
        return None

    def get_base_currency(self) -> str | None:
        """The currency month/dashboard totals are computed and displayed in,
        or None if this year has no currency tracking (amounts are already
        in a single implicit currency, e.g. Schema2025/Schema2026's Kč)."""
        return None

    def to_base_amount(self, amount: float, currency: str | None, date: Date | None = None) -> float:
        """Convert one transaction's native amount(+currency) to this
        year's base currency. If `date` is given and a historical rate for
        that exact day is cached (core/rate_history.py, backfilled by
        RateSyncWorker from ČNB/NBU), that's used — otherwise falls back
        to the file's *current* rate table, same as before `date` support
        existed. Default: no currency tracking, amount is already the
        only currency in use, unchanged."""
        return amount

    def refresh_converted_amounts(self, currency: str, date: Date, rate: float) -> int:
        """Rewrite the Rate/Amount (base currency) columns (if this
        schema's template has them) for every transaction on `date` in
        `currency`, using `rate` — called after a background rate sync
        fetches an improved rate for that exact (currency, date) pair.
        Default: no such columns exist, nothing to rewrite. Returns the
        number of rows updated."""
        return 0

    def resolve_rate(self, currency: str | None, date: Date | None) -> float | None:
        """The rate (native currency -> base) for one unit of `currency` on
        `date` — 1.0 for the base currency itself, else prefers a cached
        historical rate, falls back to the file's current rate table.
        Genuinely `None` (not a misleading fake 1.0) if nothing is known
        at all yet — used to prefill the rate-override field in the
        transaction dialog, and internally by to_base_amount()/
        _write_transaction(). Default: no currency tracking, nothing to
        resolve."""
        return None

    def convert_transaction(self, tx: dict) -> float:
        """The base-currency amount for one transaction dict (as returned
        by transactions_for_month()) — the single place every page should
        call for this instead of calling to_base_amount() itself (see
        DynamicSchema's implementation: prefers a persisted Amount(base)
        cell, else resolves fresh via to_base_amount() — Income and
        Expense use the exact same rule, pinned to the transaction's own
        date). Default: no currency tracking, the amount is already in the
        only currency in use, unchanged."""
        return tx.get("amount") or 0.0

    def get_rates(self) -> dict[str, float] | None:
        """The raw currency -> rate-to-base table, or None if this year has
        no currency tracking. Exposed (on top of to_base_amount()) for
        converting between two arbitrary currencies, not just currency ->
        base — e.g. the Currencies page's "total right now, in currency X"
        figure, where X isn't necessarily this year's own base currency."""
        return None

    def update_current_rate(self, currency: str, rate: float) -> None:
        """Overwrite this year's "current rate" table for `currency` --
        called after a background sync fetches a fresh rate. Default: no
        currency tracking, nothing to update."""
        return None

    @abstractmethod
    def add_transaction(
        self,
        date: Date,
        type_: str,
        category: str,
        amount: float,
        payment_type: str | None,
        note: str,
        currency: str | None = None,
        rate: float | None = None,
    ) -> None:
        """Write a new transaction row. Raises SheetFullError if the month is
        full. `rate` is an optional manual override (e.g. the real rate a
        bank card charged, including its own markup, vs. the official
        historical rate) — when given, it's used as-is instead of being
        resolved automatically, and persisted so it isn't silently
        overwritten by a later background sync. Ignored by schemas with no
        currency tracking."""

    @abstractmethod
    def update_transaction(
        self,
        tx: dict,
        date: Date,
        type_: str,
        category: str,
        amount: float,
        payment_type: str | None,
        note: str,
        currency: str | None = None,
        rate: float | None = None,
    ) -> None:
        """Replace an existing transaction (as returned by transactions_for_month)
        with new values. Raises TransactionNotFoundError if `tx` no longer
        matches what's on disk, or SheetFullError if the target month is full.
        `rate` — see add_transaction()."""

    @abstractmethod
    def delete_transaction(self, tx: dict) -> None:
        """Remove a transaction (as returned by transactions_for_month).
        Raises TransactionNotFoundError if `tx` no longer matches what's on disk."""

    @abstractmethod
    def month_summary(self, month: int) -> dict:
        """Return {"income": float, "expense": float, "invest": float, "balance": float,
        "cash": float | None, "card": float | None, "untracked": float | None}
        for the given month (1-12), computed from raw cell values.

        "cash" is the month's net cash movement (cash-in/cash-out
        type+payment detection). "card" is *derived*, not tagged from
        individual rows — it's balance - cash, i.e. whatever of the
        month's income/expense didn't move through cash. Most rows have no
        recorded payment method (especially 2025's older data, all
        predating the Payment column), so a tagged-only figure would stay
        at 0 nearly everywhere and tell you nothing; the derived figure at
        least moves with the month's real activity. Both are None if this
        year has no cash tracking at all (has_cash_tracking() is False).

        For a year with currency tracking, every figure here is already
        converted to the year's base currency (see to_base_amount())."""

    @abstractmethod
    def transactions_for_month(self, month: int) -> list[dict]:
        """Return every transaction in the given month (1-12), newest first."""
