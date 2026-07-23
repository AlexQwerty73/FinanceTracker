"""
dev_tests/test_rate_protection.py — manual/bank exchange-rate protection:
a rate the user overrides by hand (e.g. the real, worse rate a bank card
charged) must never be silently overwritten by a background/blanket rate
refresh, but an explicit "refresh THIS transaction" click still replaces
that exact row. Also covers the read-order fix in convert_transaction()/
month_summary() (prefer the row's own Rate cell over re-resolving from
cache/current-table) — see core/rate_history.py's is_manual()/set_manual()
and DynamicSchema.refresh_converted_amounts()'s `rows` parameter.

Run directly: python dev_tests/test_rate_protection.py
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
    ROLE_AMOUNT, ROLE_BASE_AMOUNT, ROLE_CATEGORY, ROLE_CURRENCY, ROLE_DATE, ROLE_NOTES,
    ROLE_PAYMENT, ROLE_RATE, ROLE_TYPE, Template,
)
from core.excel import templates as tpl_builder
from core.excel.schema_dynamic import DynamicSchema
from core.excel import registry
import core.rate_history as rate_history
import core.rate_fetcher as rate_fetcher
from app.components.rate_sync_worker import RateSyncWorker
from app.components.transaction_dialog import TransactionDialog


def run(scratch) -> None:
    file_path = scratch / "test.xlsx"
    tpl = Template(
        id="t", name="T",
        columns=[ROLE_DATE, ROLE_CATEGORY, ROLE_TYPE, ROLE_PAYMENT, ROLE_CURRENCY, ROLE_AMOUNT, ROLE_RATE, ROLE_BASE_AMOUNT, ROLE_NOTES],
        categories=["Food", "Bills"], types=["Income", "Expense"], income_type="Income", expense_type="Expense",
        payment_types=["Cash", "Card"], currencies=["CZK", "USD"], base_currency="CZK",
    )
    tpl_builder.create_custom_workbook(file_path, 2026, tpl)
    from core import settings, config
    from core.excel import template_model
    template_model.save_template(tpl)  # registry needs this to resolve the template id
    settings.register_candidate(2026, file_path, tpl.id)
    config.FILE_PATHS[2026] = file_path
    registry.invalidate(2026)
    schema = DynamicSchema(file_path, 2026, tpl)

    fake_rates: dict = {}
    rate_fetcher.fetch_day = lambda d: {"USD": fake_rates[d]} if d in fake_rates else None

    def run_worker(targets=None, force_rows=None):
        RateSyncWorker(targets=targets, force_rows=force_rows).run()

    day = date(2026, 3, 10)
    fake_rates[day] = 23.0

    schema.add_transaction(day, "Expense", "Food", 100, "Card", "manual bank rate", "USD", rate=25.0)
    schema.add_transaction(day, "Expense", "Bills", 50, "Card", "auto", "USD")
    txs = schema.transactions_for_month(3)
    row_a = next(t for t in txs if t["category"] == "Food")
    row_b = next(t for t in txs if t["category"] == "Bills")
    assert row_a["rate"] == 25.0

    # Targeted refresh of row B only -- row A (manual) must be untouched.
    fake_rates[day] = 22.5
    run_worker(targets={("USD", day)}, force_rows={row_b["_row"]})
    txs = schema.transactions_for_month(3)
    assert next(t for t in txs if t["category"] == "Food")["rate"] == 25.0
    assert next(t for t in txs if t["category"] == "Bills")["rate"] == 22.5

    # Blanket refresh of the same day -- the whole day is marked manual
    # (row A's override), so nothing on it updates, not even row B.
    fake_rates[day] = 21.0
    assert rate_history.is_manual("USD", day)
    run_worker(targets={("USD", day)})
    txs = schema.transactions_for_month(3)
    assert next(t for t in txs if t["category"] == "Food")["rate"] == 25.0
    assert next(t for t in txs if t["category"] == "Bills")["rate"] == 22.5

    # A rate typed straight into the Rate cell (simulating a phone entry,
    # no Amount(base) filled in) must still be used by convert_transaction().
    tx_a = next(t for t in schema.transactions_for_month(3) if t["category"] == "Food")
    converted = schema.convert_transaction(tx_a)
    assert abs(converted - tx_a["amount"] * tx_a["rate"]) < 1e-6

    # Deleting rate_history.json entirely must not change any total --
    # everything needed is already in the cells.
    before = schema.month_summary(3)["expense"]
    rate_history.RATE_HISTORY_PATH.unlink()
    rate_history._cache = None
    after = schema.month_summary(3)["expense"]
    assert abs(before - after) < 1e-6

    # Reopening the edit dialog on the manual row shows ITS OWN rate, not
    # a freshly re-resolved one.
    dlg = TransactionDialog(tx=tx_a, source_schema=schema)
    assert abs(float(dlg._rate_field.text()) - 25.0) < 1e-6

    print("test_rate_protection: ALL CHECKS PASSED")


if __name__ == "__main__":
    run(_SCRATCH)
