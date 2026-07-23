"""
core/prefs.py — tiny in-memory session preferences (not persisted to disk).
Remembers the last payment type and currency used per year, so repeat
entries (e.g. a run of Card purchases) don't require re-picking them each time.
"""
from __future__ import annotations

_last_payment_type: dict[int, str] = {}
_last_currency: dict[int, str] = {}
_last_deleted: dict | None = None  # one slot: the most recently deleted transaction, from any page


def get_last_payment_type(year: int) -> str | None:
    return _last_payment_type.get(year)


def set_last_payment_type(year: int, payment_type: str) -> None:
    _last_payment_type[year] = payment_type


def get_last_currency(year: int) -> str | None:
    return _last_currency.get(year)


def set_last_currency(year: int, currency: str) -> None:
    _last_currency[year] = currency


def set_last_deleted(entry: dict) -> None:
    """Record the just-deleted transaction (year + everything
    add_transaction() needs) so an "Undo" button can re-add it. One slot
    only, session-scoped -- a second delete simply replaces it, matching
    the plain "undo my last action" expectation rather than a full stack."""
    global _last_deleted
    _last_deleted = entry


def pop_last_deleted() -> dict | None:
    """Returns and clears the recorded entry -- undoing consumes it, so
    clicking "Undo" twice in a row doesn't re-add the same row twice."""
    global _last_deleted
    entry, _last_deleted = _last_deleted, None
    return entry


def has_last_deleted() -> bool:
    return _last_deleted is not None
