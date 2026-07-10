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


class YearSchema(ABC):
    EXPENSE_TYPE: str = ""

    def __init__(self, file_path: Path, year: int):
        self.file_path = file_path
        self.year = year

    def is_expense_type(self, type_: str) -> bool:
        """Whether `type_` counts as an expense (used for the category-breakdown chart)."""
        return type_ == self.EXPENSE_TYPE

    @abstractmethod
    def get_categories(self) -> list[str]:
        """Categories for the dropdown, in sheet order."""

    @abstractmethod
    def get_types(self) -> list[str]:
        """Transaction types for the dropdown, in sheet order."""

    def get_payment_types(self) -> list[str] | None:
        """Payment types for the dropdown, or None if this year has no such field."""
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
    ) -> None:
        """Write a new transaction row. Raises SheetFullError if the month is full."""

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
    ) -> None:
        """Replace an existing transaction (as returned by transactions_for_month)
        with new values. Raises TransactionNotFoundError if `tx` no longer
        matches what's on disk, or SheetFullError if the target month is full."""

    @abstractmethod
    def delete_transaction(self, tx: dict) -> None:
        """Remove a transaction (as returned by transactions_for_month).
        Raises TransactionNotFoundError if `tx` no longer matches what's on disk."""

    @abstractmethod
    def month_summary(self, month: int) -> dict:
        """Return {"income": float, "expense": float, "invest": float, "balance": float}
        for the given month (1-12), computed from raw cell values."""

    @abstractmethod
    def transactions_for_month(self, month: int) -> list[dict]:
        """Return every transaction in the given month (1-12), newest first."""
