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

_cache: dict | None = None  # populated on first load(); nothing else ever writes this file


def load() -> dict:
    """{"USD": {"2026-03-15": 22.9, ...}, "EUR": {...}, ...} — cached in
    memory after the first read, since get_rate() is called once per
    foreign-currency row by month_summary()/convert_transaction(), and
    re-parsing the whole (only-ever-growing) file from disk every single
    time was real, avoidable overhead on every page refresh. Nothing but
    save() (below) ever writes this file, so the cache can't go stale."""
    global _cache
    if _cache is None:
        if not RATE_HISTORY_PATH.exists():
            _cache = {}
        else:
            try:
                _cache = json.loads(RATE_HISTORY_PATH.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                _cache = {}
    return _cache


def save(data: dict) -> None:
    global _cache
    RATE_HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    # Atomic: write to a sibling temp file, then rename over the real path,
    # so a crash mid-write can't leave a half-written, unparseable file.
    tmp_path = RATE_HISTORY_PATH.with_suffix(".tmp.json")
    tmp_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    tmp_path.replace(RATE_HISTORY_PATH)
    _cache = data


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


def is_manual(currency: str, date: Date) -> bool:
    """Whether this exact (currency, date) pair's cached rate came from a
    manual override (e.g. the real, worse rate a bank card charged) rather
    than an official source. Comparing a row's cell against "the cache
    value a moment ago" can't reliably tell a manual entry apart from an
    auto-resolved one that happens to read the same number (they're
    tautologically equal right after the manual write itself creates that
    cache entry) -- so this is tracked explicitly instead. Day-level, same
    granularity as the cache itself (a documented, accepted limitation:
    a manual correction protects the whole day for that currency, not
    just the one transaction it was typed for)."""
    return date.isoformat() in load().get("_manual", {}).get(currency, [])


def set_manual(currency: str, date: Date) -> None:
    """Mark this (currency, date) pair as manually-priced -- an explicit,
    permanent refresh (RateSyncWorker's targets= mode) must never silently
    overwrite it; see is_manual()."""
    data = load()
    days = data.setdefault("_manual", {}).setdefault(currency, [])
    iso = date.isoformat()
    if iso not in days:
        days.append(iso)
    save(data)
