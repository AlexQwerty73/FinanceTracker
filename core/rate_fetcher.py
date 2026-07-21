"""
core/rate_fetcher.py — combines every source in core/rate_sources/* into
one "rate for this day" result, since no single free source covers every
currency this app tracks. Pure functions, no PyQt import — directly
runnable from a scratch script, and the only thing
app/components/rate_sync_worker.py's background QThread calls into.

Modular by design (see core/rate_sources/__init__.py): each source fails
independently, and the "which currency comes from where" mapping lives
entirely in _triangulate_uah()/fetch_day() below — swap, add, or remove
a source there without touching anything else. Right now:
- rate_sources/cnb.py — Czech National Bank daily fixing: direct CZK
  rates for most currencies (not UAH).
- rate_sources/nbu.py — National Bank of Ukraine: UAH rates against
  USD/EUR/etc.; used only to triangulate CZK<->UAH via ČNB's own USD
  rate for the same day. If NBU is unreachable, UAH is simply missing
  from that day's result — every other currency ČNB provided is
  unaffected.
"""
from __future__ import annotations

from datetime import date as Date, timedelta

from .rate_sources import cnb, nbu


def _triangulate_uah(date: Date, cnb_rates: dict[str, float]) -> float | None:
    """CZK-per-UAH = (CZK-per-USD, from ČNB) / (UAH-per-USD, from NBU),
    both for the same day. None if either source has nothing for this
    date — never raises, never affects the other currencies."""
    if "USD" not in cnb_rates:
        return None
    nbu_rates = nbu.fetch_day(date)
    if not nbu_rates or nbu_rates.get("USD", 0) <= 0:
        return None
    return cnb_rates["USD"] / nbu_rates["USD"]


def fetch_day(date: Date) -> dict[str, float] | None:
    """One day's rates, CZK per unit, combined across every source. None
    only if every source failed — a partial result (e.g. ČNB worked, NBU
    didn't) still returns whatever succeeded."""
    rates = dict(cnb.fetch_day(date) or {})

    uah_rate = _triangulate_uah(date, rates)
    if uah_rate is not None:
        rates["UAH"] = uah_rate

    return rates or None


def fetch_day_near(date: Date, max_lookback_days: int = 7) -> tuple[Date, dict[str, float]] | None:
    """Steps backward from `date` until fetch_day() returns real data
    (handles weekends/holidays, when nothing is published) or gives up.
    Returns (actual business day used, its full rate table), or None if
    nothing was found in range."""
    for offset in range(max_lookback_days + 1):
        try_date = date - timedelta(days=offset)
        rates = fetch_day(try_date)
        if rates:
            return try_date, rates
    return None


def fetch_rate_near(currency: str, date: Date, max_lookback_days: int = 7) -> tuple[Date, float] | None:
    """Convenience wrapper for a single currency — (actual business day
    used, rate), or None if not found in range or unavailable from every
    source that could provide it."""
    found = fetch_day_near(date, max_lookback_days)
    if found is None:
        return None
    actual_date, rates = found
    rate = rates.get(currency)
    return (actual_date, rate) if rate is not None else None
