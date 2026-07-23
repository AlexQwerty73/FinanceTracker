"""
dev_tests/test_net_worth_ledger.py — core/net_worth_ledger.py's balance_at()
formula: balance(target) = snapshot_balance + (movement_before(target) -
movement_before(snapshot_date)) must correctly reconstruct history both
before and after the snapshot date, and compute_full_ledger()'s monthly
history must be permanent-once-written (extend_net_worth_snapshot_history
never overwrites an already-frozen month).

Run directly: python dev_tests/test_net_worth_ledger.py
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
    ROLE_AMOUNT, ROLE_CATEGORY, ROLE_CURRENCY, ROLE_DATE, ROLE_PAYMENT, ROLE_TYPE, Template,
)
from core.excel import templates as tpl_builder, template_model
from core.excel.schema_dynamic import DynamicSchema
from core.excel import registry
from core.net_worth_ledger import balance_at, compute_full_ledger


def run(scratch: Path) -> None:
    file_path = scratch / "test.xlsx"
    tpl = Template(
        id="t", name="T",
        columns=[ROLE_DATE, ROLE_CATEGORY, ROLE_TYPE, ROLE_PAYMENT, ROLE_CURRENCY, ROLE_AMOUNT],
        categories=["Salary", "Food"], types=["Income", "Expense", "To Cash"],
        income_type="Income", expense_type="Expense", cash_in_type="To Cash",
        payment_types=["Cash", "Card"], currencies=["CZK"], base_currency="CZK",
    )
    tpl_builder.create_custom_workbook(file_path, 2026, tpl)
    template_model.save_template(tpl)
    from core import settings, config
    settings.register_candidate(2026, file_path, tpl.id)
    config.FILE_PATHS[2026] = file_path
    registry.invalidate(2026)
    schema = DynamicSchema(file_path, 2026, tpl)

    # Jan: +1000 income (card). Feb: -200 expense (cash). Mar: +500 income (card).
    schema.add_transaction(date(2026, 1, 10), "Income", "Salary", 1000, "Card", "", "CZK")
    schema.add_transaction(date(2026, 2, 10), "Expense", "Food", 200, "Cash", "", "CZK")
    schema.add_transaction(date(2026, 3, 10), "Income", "Salary", 500, "Card", "", "CZK")

    all_txs = [(schema, tx) for m in range(1, 4) for tx in schema.transactions_for_month(m)]

    # Snapshot taken today (2026-03-15) with cash=-200, card=1500 (matches
    # the running total of the three transactions above).
    snapshot_date = date(2026, 3, 15)
    snapshot_balance = {"cash": -200.0, "card": 1500.0}

    # Balance at Jan 1 (before any transaction) must back out both moves.
    jan1 = balance_at(all_txs, "CZK", snapshot_date, snapshot_balance, date(2026, 1, 1))
    assert abs(jan1["cash"] - 0.0) < 1e-6
    assert abs(jan1["card"] - 0.0) < 1e-6

    # Balance at Feb 15 (after Jan's income AND Feb 10's cash expense --
    # both are dated on or before Feb 15, so both are already reflected).
    feb15 = balance_at(all_txs, "CZK", snapshot_date, snapshot_balance, date(2026, 2, 15))
    assert abs(feb15["cash"] - (-200.0)) < 1e-6
    assert abs(feb15["card"] - 1000.0) < 1e-6

    # Balance at a future date (Apr 1, after the snapshot) equals the
    # snapshot itself (no transactions after Mar 10).
    apr1 = balance_at(all_txs, "CZK", snapshot_date, snapshot_balance, date(2026, 4, 1))
    assert abs(apr1["cash"] - (-200.0)) < 1e-6
    assert abs(apr1["card"] - 1500.0) < 1e-6

    # compute_full_ledger: opening (before the very first transaction) and
    # monthly_history should agree with the same hand-computed values.
    opening, monthly_history = compute_full_ledger(all_txs, ["CZK"], snapshot_date, {"CZK": snapshot_balance})
    assert abs(opening["CZK"]["card"] - 0.0) < 1e-6
    assert "2026-02-01" in monthly_history
    assert abs(monthly_history["2026-02-01"]["CZK"]["card"] - 1000.0) < 1e-6

    # extend_net_worth_snapshot_history never overwrites an existing month.
    from core import settings
    snap_id = settings.add_net_worth_snapshot(
        snapshot_date.isoformat(), "2026-03-15T12:00:00", {"CZK": snapshot_balance},
        opening, monthly_history,
    )
    frozen_before = settings.get_net_worth_snapshots()[0]["monthly_history"]["2026-02-01"]
    settings.extend_net_worth_snapshot_history(snap_id, {"2026-02-01": {"CZK": {"cash": 99999, "card": 99999}}})
    frozen_after = settings.get_net_worth_snapshots()[0]["monthly_history"]["2026-02-01"]
    assert frozen_before == frozen_after, "an already-frozen month must never be overwritten"

    print("test_net_worth_ledger: ALL CHECKS PASSED")


if __name__ == "__main__":
    run(_SCRATCH)
