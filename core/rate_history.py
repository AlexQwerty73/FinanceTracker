"""
core/rate_history.py — persisted, app-side cache of historical exchange
rates (currency -> CZK), keyed by the calendar date they apply to.
Separate from core/settings.py (this can grow much larger over time, one
entry per currency per day that ever had a foreign-currency transaction)
and from the Excel file entirely — no schema/template change, works
retroactively for transactions that already exist.

A cached (currency, date) entry is treated as permanent once written —
past exchange rates don't change after the fact, so this file only ever
grows, never needs invalidating. A missing entry (not yet fetched, or the
date's fetch failed) is simply absent — callers fall back to the file's
own *current* rate table (see DynamicSchema.to_base_amount()).

Dependency-free by design (no import of core.config), same reasoning as
core/settings.py — overridable path for isolated tests.
"""
from __future__ import annotations

import json
from datetime import date as Date
from pathlib import Path

RATE_HISTORY_DIR = Path.home() / ".financetracker"
RATE_HISTORY_PATH = RATE_HISTORY_DIR / "rate_history.json"


def load() -> dict:
    """{"USD": {"2026-03-15": 22.9, ...}, "EUR": {...}, ...}"""
    if not RATE_HISTORY_PATH.exists():
        return {}
    try:
        return json.loads(RATE_HISTORY_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def save(data: dict) -> None:
    RATE_HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    RATE_HISTORY_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")


def get_rate(currency: str, date: Date) -> float | None:
    return load().get(currency, {}).get(date.isoformat())


def set_rate(currency: str, date: Date, rate: float) -> None:
    data = load()
    data.setdefault(currency, {})[date.isoformat()] = rate
    save(data)


def missing_dates(currency_dates: set[tuple[str, Date]]) -> set[tuple[str, Date]]:
    """Given a set of (currency, date) pairs a caller wants rates for,
    return only the ones not already cached."""
    data = load()
    return {
        (currency, date) for currency, date in currency_dates
        if date.isoformat() not in data.get(currency, {})
    }


def get_latest_rate(currency: str) -> tuple[Date, float] | None:
    """The most recent cached (date, rate) for `currency` -- used by
    RateSyncWorker._sync_current_rate() to decide whether a just-fetched
    date is genuinely the freshest known one before overwriting the
    file's at-a-glance Lists!H:I "current rate" cell. None if nothing is
    cached at all yet for this currency."""
    entries = load().get(currency, {})
    if not entries:
        return None
    latest_iso = max(entries)
    return Date.fromisoformat(latest_iso), entries[latest_iso]
