"""
app/components/rate_sync_worker.py — RateSyncWorker: a background QThread
that backfills core/rate_history.py's local cache from
core/rate_fetcher.py. Runs off the Qt main thread so a slow/unavailable
network never freezes the UI — mirrors core/watcher.py's FileWatcher (a
background thread reporting back via a Qt signal, never touched directly
by the UI thread).

Two modes, one worker class (kept as one to share the fetch/spacing/
signal plumbing rather than duplicating it):
- `RateSyncWorker()` (no targets) — the default, automatic mode, two
  passes: (1) `_unwritten_cells()` — every (currency, date) pair whose
  rate is *already cached* but whose own transaction row still has a
  blank Rate/Amount(base) cell (e.g. typed directly into Excel from a
  phone, or migrated under an older rule) gets that cell filled in
  immediately, no network call needed, the rate's already known; (2)
  `_missing_currency_dates()` — pairs with no cached rate at all get
  fetched, cached, and *then* also written to their cells the same way.
  Used for the app-launch sync and the Currencies page's blanket
  "Refresh rates" button.
- `RateSyncWorker(targets={...})` — explicit mode: fetches exactly the
  given (currency, date) pairs and **overwrites** whatever's already
  cached for them, missing or not. Used for "refresh this one
  transaction's rate" (transaction_dialog.py) and "refresh this date
  range" (currencies_page.py) — both cases where the user is deliberately
  asking to re-check a specific rate, not just fill gaps.
"""
from __future__ import annotations

import time
from datetime import date as Date

from PyQt6.QtCore import QThread, pyqtSignal

from core import rate_fetcher, rate_history
from core.excel import registry

_REQUEST_SPACING_SECONDS = 0.1


def _foreign_currency_dates() -> set[tuple[str, Date]]:
    """Every (currency, date) pair actually used by a foreign-currency
    transaction, across every currency-tracked year — the full universe
    _missing_currency_dates()/_unwritten_cells() both filter down from."""
    pairs: set[tuple[str, Date]] = set()
    for year in registry.supported_years():
        try:
            schema = registry.get_schema_for_date(Date(year, 1, 1))
        except ValueError:
            continue
        base = schema.get_base_currency()
        if base is None:
            continue  # this year's schema has no currency tracking at all
        for m in range(1, 13):
            for tx in schema.transactions_for_month(m):
                currency = tx.get("currency")
                date_val = tx.get("date")
                if not currency or currency == base or date_val is None:
                    continue
                d = date_val.date() if hasattr(date_val, "date") else date_val
                pairs.add((currency, d))
    return pairs


def _missing_currency_dates() -> set[tuple[str, Date]]:
    """Pairs with no cached rate at all yet -- need an actual network fetch."""
    return rate_history.missing_dates(_foreign_currency_dates())


def _unwritten_cells() -> set[tuple[str, Date]]:
    """Pairs that already have a cached rate (rate_history.json) but whose
    row(s) still have a blank Rate/Amount(base) cell -- these need a cell
    rewrite only, no network call, since the rate is already known."""
    pairs: set[tuple[str, Date]] = set()
    for year in registry.supported_years():
        try:
            schema = registry.get_schema_for_date(Date(year, 1, 1))
        except ValueError:
            continue
        base = schema.get_base_currency()
        if base is None:
            continue
        for m in range(1, 13):
            for tx in schema.transactions_for_month(m):
                currency = tx.get("currency")
                date_val = tx.get("date")
                if not currency or currency == base or date_val is None:
                    continue
                if tx.get("rate") is not None or tx.get("base_amount") is not None:
                    continue  # already written
                d = date_val.date() if hasattr(date_val, "date") else date_val
                if rate_history.get_rate(currency, d) is not None:
                    pairs.add((currency, d))
    return pairs


def _sync_current_rate(currency: str, date_: Date, rate: float) -> None:
    """If `date_` really is the most recent known date for `currency`,
    also overwrite every currency-tracked year's Lists!H:I "current rate"
    cell -- keeps the at-a-glance table honest too, not just per-
    transaction cells (see feedback_excel_immediate_sync.md). Skipped for
    a backfilled-but-older date, so a gap-filling sync can never regress
    the current rate to something stale."""
    latest = rate_history.get_latest_rate(currency)
    if latest is None or latest[0] != date_:
        return
    for year in registry.supported_years():
        try:
            registry.get_schema_for_date(Date(year, 1, 1)).update_current_rate(currency, rate)
        except ValueError:
            continue


def _write_rate_to_cells(currency: str, date_: Date, rate: float) -> None:
    """Push a known rate into every place the workbook itself should show
    it: the exact (currency, date) transaction row(s) via
    refresh_converted_amounts(), and Lists!H:I's "current rate" cell if
    this is genuinely the freshest date known for `currency`."""
    try:
        schema = registry.get_schema_for_date(date_)
    except ValueError:
        pass
    else:
        schema.refresh_converted_amounts(currency, date_, rate)
    _sync_current_rate(currency, date_, rate)


class RateSyncWorker(QThread):
    """Emits `sync_finished(int)` (count of dates successfully fetched)
    on the Qt main thread once the sync completes. Every network call
    happens inside run(), on this thread — the UI thread never blocks."""

    sync_finished = pyqtSignal(int)

    def __init__(self, parent=None, targets: set[tuple[str, Date]] | None = None):
        super().__init__(parent)
        self._explicit_targets = targets

    def run(self) -> None:
        updated = 0
        if self._explicit_targets is not None:
            targets = self._explicit_targets
        else:
            # Pass 1: rates already known (cached), just never written into
            # this specific row's cells -- no network call needed at all.
            for currency, d in _unwritten_cells():
                rate = rate_history.get_rate(currency, d)
                if rate is not None:
                    _write_rate_to_cells(currency, d, rate)
                    updated += 1
            targets = _missing_currency_dates()

        # Pass 2 (and the whole of explicit-targets mode): genuinely
        # missing rates -- one fetch per unique date covers every currency
        # published that day (see rate_fetcher.fetch_day), so a date with
        # e.g. 2 target currencies costs one HTTP round-trip, not two.
        dates_needed = sorted({d for _currency, d in targets})
        for d in dates_needed:
            rates = rate_fetcher.fetch_day(d)
            if rates:
                for currency, date_ in targets:
                    if date_ == d and currency in rates:
                        rate_history.set_rate(currency, date_, rates[currency])
                        # Any transaction already saved with an earlier
                        # (e.g. current-table fallback) rate for this exact
                        # (currency, date) needs its Rate/Amount(base) cells
                        # brought in line with what the app now knows —
                        # the workbook is the source of truth, not this cache.
                        _write_rate_to_cells(currency, date_, rates[currency])
                updated += 1
            time.sleep(_REQUEST_SPACING_SECONDS)
        self.sync_finished.emit(updated)
