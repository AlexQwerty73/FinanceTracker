"""
core/prefs.py — tiny in-memory session preferences (not persisted to disk).
Remembers the last payment type and currency used per year, so repeat
entries (e.g. a run of Card purchases) don't require re-picking them each time.
"""
from __future__ import annotations

_last_payment_type: dict[int, str] = {}
_last_currency: dict[int, str] = {}


def get_last_payment_type(year: int) -> str | None:
    return _last_payment_type.get(year)


def set_last_payment_type(year: int, payment_type: str) -> None:
    _last_payment_type[year] = payment_type


def get_last_currency(year: int) -> str | None:
    return _last_currency.get(year)


def set_last_currency(year: int, currency: str) -> None:
    _last_currency[year] = currency
