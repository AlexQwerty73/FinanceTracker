"""
dev_tests/test_duplicates_outliers.py — core/duplicates.py's currency
awareness: two transactions with the same date/category/native-amount but
different currencies must NOT be flagged as duplicates of each other, and
category outlier statistics must be computed in base currency (not raw
native amounts) so a multi-currency category's mean/stdev isn't distorted.
Also covers the ignore-signature strengthening (amount included, so a
reused row number after a delete doesn't silently inherit an old ignore).

Run directly: python dev_tests/test_duplicates_outliers.py
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dev_tests._isolation import isolate

_SCRATCH = isolate()

from PyQt6.QtWidgets import QApplication
_app = QApplication.instance() or QApplication([])

from core.excel.template_model import (
    ROLE_AMOUNT, ROLE_CATEGORY, ROLE_CURRENCY, ROLE_DATE, ROLE_NOTES, ROLE_PAYMENT, ROLE_RATE, ROLE_TYPE, Template,
)
from core.excel import templates as tpl_builder, template_model
from core.excel.schema_dynamic import DynamicSchema
from core.excel import registry
from core.duplicates import detect_duplicates, detect_outliers
from core.excel.transaction_validator import detect_invalid_rows


def run(scratch: Path) -> None:
    file_path = scratch / "test.xlsx"
    tpl = Template(
        id="t", name="T",
        columns=[ROLE_DATE, ROLE_CATEGORY, ROLE_TYPE, ROLE_PAYMENT, ROLE_CURRENCY, ROLE_AMOUNT, ROLE_RATE, ROLE_NOTES],
        categories=["Food", "Utilities"], types=["Income", "Expense"], income_type="Income", expense_type="Expense",
        payment_types=["Cash", "Card"], currencies=["CZK", "USD"], base_currency="CZK",
    )
    tpl_builder.create_custom_workbook(file_path, 2026, tpl)
    template_model.save_template(tpl)
    from core import settings, config
    settings.register_candidate(2026, file_path, tpl.id)
    config.FILE_PATHS[2026] = file_path
    registry.invalidate(2026)
    schema = DynamicSchema(file_path, 2026, tpl)

    # Same day/category/native-amount, different currency -- must NOT
    # be flagged as a duplicate of each other.
    schema.add_transaction(date(2026, 4, 5), "Expense", "Food", 100, "Cash", "usd", "USD")
    schema.add_transaction(date(2026, 4, 5), "Expense", "Food", 100, "Cash", "czk", "CZK")
    dups = detect_duplicates()
    assert not [g for g in dups if g.period_label == "2026-04-05" and g.category == "Food"]

    # A genuine same-currency duplicate IS still flagged.
    schema.add_transaction(date(2026, 4, 6), "Expense", "Food", 77, "Cash", "dup 1", "CZK")
    schema.add_transaction(date(2026, 4, 6), "Expense", "Food", 77, "Cash", "dup 2", "CZK")
    dups2 = detect_duplicates()
    assert len([g for g in dups2 if g.period_label == "2026-04-06"]) == 1

    # Outlier stats are computed in base currency: a tight native-CZK
    # cluster plus one USD row that's modest natively but large once
    # converted must flag the USD row.
    for i, amt in enumerate([95, 100, 105, 98, 102, 97, 103, 99, 101, 96]):
        schema.add_transaction(date(2026, 5, i + 1), "Expense", "Utilities", amt, "Cash", f"normal {i}", "CZK")
    schema.add_transaction(date(2026, 5, 20), "Expense", "Utilities", 20, "Cash", "usd outlier", "USD", rate=25.0)
    outliers = detect_outliers()
    util_outliers = [o for o in outliers if o.category == "Utilities"]
    assert any(o.tx.get("note") == "usd outlier" for o in util_outliers)

    # Ignore signatures include the amount -- outlier|year|month|row|amount,
    # invalid|year|month|row|amount (4 pipe separators, not 3).
    assert all(sig.count("|") == 4 for sig in (o.signature for o in outliers))
    schema.add_transaction(date(2026, 6, 1), "Expense", "Food", -5, "Cash", "bad amount", "CZK")
    bad_rows = detect_invalid_rows()
    assert bad_rows and bad_rows[0].signature.count("|") == 4

    print("test_duplicates_outliers: ALL CHECKS PASSED")


if __name__ == "__main__":
    run(_SCRATCH)
