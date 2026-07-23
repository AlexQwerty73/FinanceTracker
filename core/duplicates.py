"""
core/duplicates.py — pure detection of likely accidental double-entries
and outlier amounts, across every registered year. No PyQt import.

"Duplicate" = two or more transactions in the same year sharing the same
date + type + category + currency + amount: the classic "entered the
same purchase twice" mistake. Currency is part of the key so e.g. a
100 USD and a 100 UAH transaction on the same day/category are never
flagged as duplicates of each other just because their native amounts
happen to match. Years without real per-transaction dates (e.g. 2025 —
see YearSchema.HAS_DAILY_DATES) are skipped entirely, same as
core/subscriptions.py's own detection: without a real date, "same month,
same category, same amount" is far too loose (two separate, legitimate
purchases sharing a common round amount in the same category are
routine) and produced a flood of false positives when first tried
against real data.

"Outlier" = an expense whose amount (converted to the year's base
currency, so a multi-currency category's stats aren't skewed by treating
e.g. 100 UAH and 100 CZK as the same magnitude) sits more than
OUTLIER_STDEV_MULTIPLIER standard deviations above its own category's
mean (only evaluated for categories with enough history to know what
"normal" looks like) — worth a second look, not necessarily wrong.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date as Date
from statistics import mean, pstdev

from .excel import registry
from .excel.base import YearSchema

OUTLIER_MIN_CATEGORY_SAMPLES = 5  # need enough history to know what's "normal" for a category
OUTLIER_STDEV_MULTIPLIER = 3.0


@dataclass
class DuplicateGroup:
    signature: str
    year: int
    schema: YearSchema
    period_label: str
    type_: str
    category: str
    amount: float
    transactions: list[dict]  # each is the exact dict transactions_for_month() returned -- safe
                              # to pass straight into schema.delete_transaction()


@dataclass
class Outlier:
    signature: str
    year: int
    schema: YearSchema
    category: str
    tx: dict
    category_mean: float  # base currency (see detect_outliers) — not necessarily tx's own native currency
    category_stdev: float  # base currency, same reasoning


def detect_duplicates(ignored_signatures: set[str] | None = None) -> list[DuplicateGroup]:
    ignored_signatures = ignored_signatures or set()
    groups: list[DuplicateGroup] = []
    for year in registry.supported_years():
        try:
            schema = registry.get_schema_for_date(Date(year, 1, 1))
        except ValueError:
            continue
        if not schema.HAS_DAILY_DATES:
            continue

        by_key: dict[tuple, list[dict]] = {}
        for m in range(1, 13):
            for tx in schema.transactions_for_month(m):
                date_val = tx.get("date")
                if date_val is None:
                    continue
                d = date_val.date() if hasattr(date_val, "date") else date_val
                key = (d, tx.get("type"), tx.get("category"), tx.get("currency"), round(tx.get("amount") or 0.0, 2))
                by_key.setdefault(key, []).append(tx)

        for (d, type_, category, currency, amount), txs in by_key.items():
            if len(txs) < 2:
                continue
            signature = f"dup|{year}|{d.isoformat()}|{type_}|{category}|{currency}|{amount}"
            if signature in ignored_signatures:
                continue
            groups.append(DuplicateGroup(
                signature=signature, year=year, schema=schema, period_label=d.isoformat(),
                type_=type_, category=category, amount=amount, transactions=txs,
            ))

    groups.sort(key=lambda g: (g.year, g.period_label))
    return groups


def detect_outliers(ignored_signatures: set[str] | None = None) -> list[Outlier]:
    ignored_signatures = ignored_signatures or set()
    outliers: list[Outlier] = []
    for year in registry.supported_years():
        try:
            schema = registry.get_schema_for_date(Date(year, 1, 1))
        except ValueError:
            continue

        by_category: dict[str, list[dict]] = {}
        for m in range(1, 13):
            for tx in schema.transactions_for_month(m):
                if not schema.is_expense_type(tx.get("type")):
                    continue
                by_category.setdefault(tx.get("category") or "Other", []).append(tx)

        for category, txs in by_category.items():
            if len(txs) < OUTLIER_MIN_CATEGORY_SAMPLES:
                continue
            amounts = [schema.convert_transaction(tx) for tx in txs]
            avg = mean(amounts)
            spread = pstdev(amounts)
            if spread == 0:
                continue
            threshold = avg + OUTLIER_STDEV_MULTIPLIER * spread
            for tx, amount in zip(txs, amounts):
                if amount <= threshold:
                    continue
                # Amount in the signature too -- a deleted transaction blanks
                # its row, and a later add can reuse that same row number;
                # without the amount, an old ignore would silently carry
                # over to whatever unrelated new transaction lands there.
                signature = f"outlier|{year}|{tx.get('month')}|{tx.get('_row')}|{round(tx.get('amount') or 0.0, 2)}"
                if signature in ignored_signatures:
                    continue
                outliers.append(Outlier(
                    signature=signature, year=year, schema=schema, category=category, tx=tx,
                    category_mean=avg, category_stdev=spread,
                ))

    outliers.sort(key=lambda o: o.tx.get("amount") or 0.0, reverse=True)
    return outliers
