"""
core/net_worth_ledger.py — pure net-worth math: cash/card movement
classification and the "balance at any date, anchored to a real snapshot"
formula. Dependency-free (no PyQt import) so both
app/pages/currencies_page.py and app/components/net_worth_snapshot_dialog.py
can import it directly without a circular import between the page and its
own dialog (see feedback_modular_structure.md).
"""
from __future__ import annotations

from datetime import date as Date, timedelta


def native_cash_card_delta(schema, tx: dict) -> tuple[float, float]:
    """Same classification as AnalyticsPage._cash_card_delta, but in the
    transaction's own native currency units (no base-currency conversion)
    — net worth needs "how much of currency X moved through cash/card",
    not a cross-currency total."""
    t, payment, amt = tx.get("type"), tx.get("payment_type"), tx.get("amount") or 0
    cash_delta = 0.0
    if schema.is_cash_in_type(t):
        cash_delta += amt
    elif schema.is_cash_out_type(t) or (schema.is_expense_type(t) and payment == "Cash"):
        cash_delta -= amt
    balance_delta = amt if schema.is_income_type(t) else (-amt if schema.is_expense_type(t) else 0.0)
    return cash_delta, balance_delta - cash_delta


def tx_date(tx: dict) -> Date | None:
    d = tx.get("date")
    return d.date() if hasattr(d, "date") else d


def movement_before(all_txs, currency: str, cutoff_date: Date | None) -> tuple[float, float]:
    """(cash_delta, card_delta) summed over every transaction in `currency`
    dated on or before `cutoff_date` (`None` means "everything"). A
    transaction with no date at all (an undated legacy year) always
    counts as "before" — it's necessarily older data."""
    cash_moved = card_moved = 0.0
    for schema, tx in all_txs:
        if tx.get("currency") != currency:
            continue
        if cutoff_date is not None:
            d = tx_date(tx)
            if d is not None and d > cutoff_date:
                continue
        cd, kd = native_cash_card_delta(schema, tx)
        cash_moved += cd
        card_moved += kd
    return cash_moved, card_moved


def earliest_tx_date(all_txs) -> Date | None:
    dates = [d for _schema, tx in all_txs if (d := tx_date(tx)) is not None]
    return min(dates) if dates else None


def month_starts(from_date: Date, to_date: Date) -> list[Date]:
    """The 1st of every month from from_date's month through to_date's
    month, inclusive. Empty if from_date > to_date."""
    if from_date > to_date:
        return []
    starts = []
    y, m = from_date.year, from_date.month
    while (y, m) <= (to_date.year, to_date.month):
        starts.append(Date(y, m, 1))
        m += 1
        if m > 12:
            m, y = 1, y + 1
    return starts


def balance_at(all_txs, currency: str, snapshot_date: Date, snapshot_balance: dict, target_date: Date) -> dict:
    """{"cash", "card"} at `target_date`, anchored to a snapshot taken on
    `snapshot_date` with `snapshot_balance` — works for a `target_date`
    before OR after the snapshot via the same formula: balance(target) =
    snapshot + (movement up to target − movement up to snapshot), which
    is negative (correctly subtracting) when target is the earlier date."""
    cash_at_snapshot, card_at_snapshot = movement_before(all_txs, currency, snapshot_date)
    cash_at_target, card_at_target = movement_before(all_txs, currency, target_date)
    return {
        "cash": snapshot_balance.get("cash", 0.0) + (cash_at_target - cash_at_snapshot),
        "card": snapshot_balance.get("card", 0.0) + (card_at_target - card_at_snapshot),
    }


def compute_full_ledger(all_txs, currencies, snapshot_date: Date, balances: dict) -> tuple[dict, dict]:
    """(opening, monthly_history) for a brand-new snapshot — `opening` is
    the balance the instant before the very first transaction; `monthly_history`
    covers the 1st of every month from the earliest transaction's month
    through the snapshot's own month."""
    earliest = earliest_tx_date(all_txs)
    opening: dict = {}
    monthly_history: dict = {}
    for currency in currencies:
        balance = balances.get(currency, {"cash": 0.0, "card": 0.0})
        if earliest is not None:
            opening[currency] = balance_at(all_txs, currency, snapshot_date, balance, earliest - timedelta(days=1))
            for month_start in month_starts(earliest, snapshot_date):
                monthly_history.setdefault(month_start.isoformat(), {})[currency] = balance_at(
                    all_txs, currency, snapshot_date, balance, month_start
                )
        else:
            opening[currency] = dict(balance)
    return opening, monthly_history
