"""
core/excel/transaction_validator.py — flags rows whose raw cell content
doesn't hold up: a mistake sitting in the table must be visible, not
silently coerced away or "corrected" by the app (see
feedback_excel_presentable_mobile.md's underlying principle and this
round's whole reason for existing). No PyQt import — mirrors
core/duplicates.py's shape, surfaced the same way on review_page.py.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date as Date, datetime

from . import registry
from .base import YearSchema

CONSISTENCY_TOLERANCE = 0.01


@dataclass
class InvalidRow:
    signature: str
    year: int
    schema: YearSchema
    tx: dict
    problems: list[str]


def _row_problems(schema: YearSchema, tx: dict) -> list[str]:
    problems = []
    if schema.HAS_DAILY_DATES and not isinstance(tx.get("date"), (Date, datetime)):
        problems.append("missing or invalid date")
    if (tx.get("amount") or 0) <= 0:
        problems.append("amount is not a positive number")
    currencies = schema.get_currencies()
    if currencies is not None and tx.get("currency") and tx["currency"] not in currencies:
        problems.append(f'currency "{tx["currency"]}" is not in the Lists sheet')
    rate, base_amount = tx.get("rate"), tx.get("base_amount")
    if rate is not None and rate <= 0:
        problems.append("rate is not a positive number")
    if rate is not None and base_amount is not None and abs((tx.get("amount") or 0) * rate - base_amount) > CONSISTENCY_TOLERANCE:
        problems.append(f"Amount(base) {base_amount:g} doesn't match Amount x Rate ({(tx.get('amount') or 0) * rate:.2f})")
    return problems


def detect_invalid_rows(ignored_signatures: set[str] | None = None) -> list[InvalidRow]:
    ignored_signatures = ignored_signatures or set()
    found: list[InvalidRow] = []
    for year in registry.supported_years():
        try:
            schema = registry.get_schema_for_date(Date(year, 1, 1))
        except ValueError:
            continue
        for m in range(1, 13):
            for tx in schema.transactions_for_month(m):
                problems = _row_problems(schema, tx)
                if not problems:
                    continue
                signature = f"invalid|{year}|{tx['month']}|{tx['_row']}"
                if signature in ignored_signatures:
                    continue
                found.append(InvalidRow(signature=signature, year=year, schema=schema, tx=tx, problems=problems))
    return found
