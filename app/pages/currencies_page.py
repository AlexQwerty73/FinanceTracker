"""
app/pages/currencies_page.py — CurrenciesPage: net worth / opening-balance
across every currency-tracked year. All-time / all-years by design (not
scoped to the TopBar's selected month) — refreshed lazily when the page
becomes visible, mirroring Analytics/Categories.

Net worth entry happens through a single "Take snapshot" form (opens
TakeSnapshotDialog) instead of inline per-currency fields — one form, one
date (always today), every currency at once. Saving it computes and
permanently freezes (core.net_worth_ledger.compute_full_ledger) both the
balance before the very first transaction ("opening") and the balance at
the 1st of every month since — a real historical ledger, not a live
recalculation. Every stored snapshot (not just the active one) keeps that
ledger extending forward every time this page is opened
(_extend_all_snapshots()), for as long as it isn't deleted from
ManageSnapshotsDialog — so switching which snapshot is active later still
has an up-to-date ledger. One page-wide "Use snapshot" checkbox decides
whether the active snapshot's numbers are actually applied at all
(settings.get/set_net_worth_snapshot_use_enabled) — independent of which
snapshot is currently marked active.

"Total right now" converts the active snapshot's cash+card figures into
one chosen currency at *today's* rate (read fresh from whichever
currency-tracked year's Lists sheet is most current).

"Movement by currency" (a per-currency chart + transaction list) draws
straight from the applied snapshot's own frozen monthly_history when one
exists — real historical cash+card totals, not a relative-to-zero running
sum — falling back to the old 0-anchored behavior when no snapshot is
applied. Deliberately native-currency (no base-currency conversion, no
today's-rate dependency) — that's also why this stays a Currencies-page
feature instead of living on Analytics (which is a converted,
cross-currency aggregate; see "Ideas — not yet built" for that trade-off).
"""
from __future__ import annotations

from datetime import date as Date

from PyQt6.QtGui import QColor, QFont
from PyQt6.QtWidgets import (
    QCheckBox, QGridLayout, QHBoxLayout, QLabel, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from core import rate_history, settings
from core.excel import registry
from core.excel.base import MONTH_NAMES, YearSchema
from core.format import fmt_amount
from core.net_worth_ledger import balance_at, month_starts
from core.themes import c, font_size

from ..components.charts import BalanceLineChart
from ..components.net_worth_snapshot_dialog import ManageSnapshotsDialog, TakeSnapshotDialog
from ..components.rate_sync_worker import RateSyncWorker
from ..components.transaction_fields import field_label, input_style
from ..components.widgets import NoWheelComboBox, card, scrollable_area, secondary_button, section_label


def _currency_tracked_years() -> list[int]:
    years = []
    for y in registry.supported_years():
        try:
            schema = registry.get_schema_for_date(Date(y, 1, 1))
        except ValueError:
            continue
        if schema.get_currencies() is not None:
            years.append(y)
    return years


def _currencies_needing_rate_source() -> list[str]:
    """Currencies actually used in a transaction that have never received
    a single cached exchange rate, despite the app-launch auto-sync
    having run for every used currency automatically — almost certainly
    means core/rate_fetcher.py genuinely has no source that covers this
    currency (see its own module docstring for the currently-wired
    sources), not just "hasn't been fetched yet". Per the project's
    modularity preference, this must be a visible, localized message, not
    a currency that silently never converts."""
    bases = {
        schema.get_base_currency()
        for y in _currency_tracked_years()
        if (schema := registry.get_schema_for_date(Date(y, 1, 1))).get_base_currency()
    }
    used = {tx.get("currency") for _schema, tx in _all_currency_transactions() if tx.get("currency")}
    cache = rate_history.load()
    return sorted(cur for cur in used - bases if not cache.get(cur))


def _all_currency_transactions() -> list[tuple[YearSchema, dict]]:
    """(schema, tx) for every transaction in every currency-tracked year,
    every month — the base dataset the net-worth ledger and the
    per-currency chart/list both scan over."""
    out = []
    for y in _currency_tracked_years():
        schema = registry.get_schema_for_date(Date(y, 1, 1))
        for m in range(1, 13):
            for tx in schema.transactions_for_month(m):
                if tx.get("currency"):
                    out.append((schema, tx))
    return out


def _sort_key(item: tuple[YearSchema, dict]) -> tuple:
    date_val = item[1].get("date")
    if date_val is None:
        return (0,)
    if hasattr(date_val, "date"):
        date_val = date_val.date()
    return (1, date_val)


class CurrenciesPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._all_txs: list[tuple[YearSchema, dict]] = []
        self._currencies: list[str] = []
        self._opening_labels: dict[str, tuple[QLabel, QLabel]] = {}
        self._rate_sync: RateSyncWorker | None = None

        outer_lay = QVBoxLayout(self)
        outer_lay.setContentsMargins(0, 0, 0, 0)

        content = QWidget()
        content.setStyleSheet("background:transparent;")
        outer_lay.addWidget(scrollable_area(content))

        lay = QVBoxLayout(content)
        lay.setContentsMargins(4, 4, 4, 20)
        lay.setSpacing(16)

        hdr = QLabel("Currencies")
        hdr.setFont(QFont("Segoe UI", font_size("title"), QFont.Weight.Bold))
        hdr.setStyleSheet(f"color:{c('t1')}; background:transparent;")
        lay.addWidget(hdr)

        # ── Net worth card ───────────────────────────────────────────────
        self._nw_box, nw_lay = card("Net worth")
        nw_helper = QLabel(
            "Take a snapshot of what you actually have — Opening balance (before your first "
            "recorded transaction) and the balance at the start of every month are worked out "
            "and frozen automatically."
        )
        nw_helper.setWordWrap(True)
        nw_helper.setFont(QFont("Segoe UI", font_size("micro")))
        nw_helper.setStyleSheet(f"color:{c('t3')}; background:transparent;")
        nw_lay.addWidget(nw_helper)
        self._nw_empty_lbl = QLabel(
            "No file with currency tracking is active yet — activate one from "
            "Manage Files to use this page."
        )
        self._nw_empty_lbl.setWordWrap(True)
        self._nw_empty_lbl.setStyleSheet(f"color:{c('t3')}; background:transparent;")
        nw_lay.addWidget(self._nw_empty_lbl)

        self._nw_grid_host = QWidget()
        self._nw_grid_host.setStyleSheet("background:transparent;")
        self._nw_grid = QGridLayout(self._nw_grid_host)
        self._nw_grid.setSpacing(8)
        nw_lay.addWidget(self._nw_grid_host)

        snapshot_row = QHBoxLayout()
        snapshot_row.setContentsMargins(0, 8, 0, 0)
        take_btn = secondary_button("Take snapshot")
        take_btn.clicked.connect(self._on_take_snapshot_clicked)
        snapshot_row.addWidget(take_btn)
        manage_btn = secondary_button("Manage snapshots")
        manage_btn.clicked.connect(self._on_manage_snapshots_clicked)
        snapshot_row.addWidget(manage_btn)
        self._use_snapshot_check = QCheckBox("Use snapshot in calculations")
        self._use_snapshot_check.toggled.connect(self._on_use_toggled)
        snapshot_row.addWidget(self._use_snapshot_check)
        snapshot_row.addStretch()
        nw_lay.addLayout(snapshot_row)

        self._snapshot_status_lbl = QLabel("")
        self._snapshot_status_lbl.setWordWrap(True)
        self._snapshot_status_lbl.setFont(QFont("Segoe UI", font_size("micro")))
        self._snapshot_status_lbl.setStyleSheet(f"color:{c('t3')}; background:transparent;")
        nw_lay.addWidget(self._snapshot_status_lbl)

        self._total_row_host = QWidget()
        self._total_row_host.setStyleSheet("background:transparent;")
        total_row = QHBoxLayout(self._total_row_host)
        total_row.setContentsMargins(0, 8, 0, 0)
        total_row.addWidget(field_label("Total right now, in"))
        self._total_currency_combo = NoWheelComboBox()
        self._total_currency_combo.setFixedWidth(90)
        self._total_currency_combo.setStyleSheet(input_style())
        self._total_currency_combo.currentTextChanged.connect(self._refresh_total)
        total_row.addWidget(self._total_currency_combo)
        total_row.addStretch()
        self._total_lbl = QLabel("—")
        self._total_lbl.setFont(QFont("Segoe UI", font_size("stat"), QFont.Weight.Bold))
        self._total_lbl.setStyleSheet(f"color:{c('ac')}; background:transparent;")
        total_row.addWidget(self._total_lbl)
        nw_lay.addWidget(self._total_row_host)

        rate_sync_row = QHBoxLayout()
        rate_sync_row.setContentsMargins(0, 8, 0, 0)
        self._refresh_rates_btn = secondary_button("Refresh rates")
        self._refresh_rates_btn.clicked.connect(self._on_refresh_rates_clicked)
        rate_sync_row.addWidget(self._refresh_rates_btn)
        self._rate_sync_status = QLabel("")
        self._rate_sync_status.setFont(QFont("Segoe UI", font_size("micro")))
        self._rate_sync_status.setStyleSheet(f"color:{c('t3')}; background:transparent;")
        rate_sync_row.addWidget(self._rate_sync_status)
        rate_sync_row.addStretch()
        nw_lay.addLayout(rate_sync_row)

        self._no_rate_warning_lbl = QLabel("")
        self._no_rate_warning_lbl.setWordWrap(True)
        self._no_rate_warning_lbl.setFont(QFont("Segoe UI", font_size("micro")))
        self._no_rate_warning_lbl.setStyleSheet(f"color:{c('err_c')}; background:transparent;")
        self._no_rate_warning_lbl.setVisible(False)
        nw_lay.addWidget(self._no_rate_warning_lbl)

        lay.addWidget(self._nw_box)

        # ── Per-currency movement card ─────────────────────────────────────
        move_box, move_lay = card("Movement by currency")
        picker_row = QHBoxLayout()
        picker_row.addWidget(field_label("Currency"))
        self._currency_combo = NoWheelComboBox()
        self._currency_combo.setFixedWidth(90)
        self._currency_combo.setStyleSheet(input_style())
        self._currency_combo.currentTextChanged.connect(self._refresh_currency_detail)
        picker_row.addWidget(self._currency_combo)
        picker_row.addStretch()
        move_lay.addLayout(picker_row)

        self._chart_anchor_lbl = QLabel("")
        self._chart_anchor_lbl.setFont(QFont("Segoe UI", font_size("micro")))
        self._chart_anchor_lbl.setStyleSheet(f"color:{c('t3')}; background:transparent;")
        move_lay.addWidget(self._chart_anchor_lbl)

        self._chart = BalanceLineChart()
        move_lay.addWidget(self._chart)

        move_lay.addWidget(section_label("Transactions in this currency"))
        self._table = QTableWidget(0, 6)
        self._table.setHorizontalHeaderLabels(["Date", "Type", "Category", "Payment", "Amount", "Note"])
        self._table.verticalHeader().setVisible(False)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self._table.horizontalHeader().setStretchLastSection(True)
        for col, width in [(0, 90), (1, 90), (2, 140), (3, 80), (4, 100)]:
            self._table.setColumnWidth(col, width)
        self._table.setMinimumHeight(260)
        self._table.setStyleSheet(f"""
            QTableWidget {{ background:{c('panel_bg')}; color:{c('t1')}; border:1px solid {c('panel_bd')};
                border-radius:10px; gridline-color:{c('sep')}; }}
            QHeaderView::section {{ background:transparent; color:{c('t2')}; border:none;
                border-bottom:1px solid {c('sep')}; padding:6px; }}
            QTableWidget::item {{ padding:4px; }}
        """)
        move_lay.addWidget(self._table)
        lay.addWidget(move_box)

    # ── refresh (all-time, no month/year args — mirrors Categories) ──────

    def refresh(self) -> None:
        self._all_txs = _all_currency_transactions()
        seen = {tx.get("currency") for _schema, tx in self._all_txs if tx.get("currency")}
        configured: set[str] = set()
        for y in _currency_tracked_years():
            schema = registry.get_schema_for_date(Date(y, 1, 1))
            configured |= set(schema.get_currencies() or [])
        self._currencies = sorted(seen | configured)

        missing_sources = _currencies_needing_rate_source()
        self._no_rate_warning_lbl.setVisible(bool(missing_sources))
        if missing_sources:
            self._no_rate_warning_lbl.setText(
                f"No exchange rate source found for: {', '.join(missing_sources)} — these transactions "
                "won't convert correctly until a rate is entered manually or a source is added."
            )

        has_tracking = bool(_currency_tracked_years())
        self._nw_empty_lbl.setVisible(not has_tracking)
        self._nw_grid_host.setVisible(has_tracking)
        self._total_row_host.setVisible(has_tracking)

        if not has_tracking:
            self._table.setRowCount(0)
            self._chart.update_data([])
            self._currency_combo.clear()
            self._total_currency_combo.clear()
            return

        self._extend_all_snapshots()
        self._rebuild_net_worth_display()
        self._reload_combo(self._currency_combo)
        self._reload_combo(self._total_currency_combo)
        self._refresh_total()
        self._refresh_currency_detail()

    def _reload_combo(self, combo: NoWheelComboBox) -> None:
        prev = combo.currentText()
        combo.blockSignals(True)
        combo.clear()
        combo.addItems(self._currencies)
        if prev in self._currencies:
            combo.setCurrentText(prev)
        combo.blockSignals(False)

    # ── historical rate sync (on demand) ──────────────────────────────────

    def _on_refresh_rates_clicked(self) -> None:
        if self._rate_sync is not None and self._rate_sync.isRunning():
            return
        self._refresh_rates_btn.setEnabled(False)
        self._rate_sync_status.setText("Refreshing…")
        self._rate_sync = RateSyncWorker(self)
        self._rate_sync.sync_finished.connect(self._on_rate_sync_finished)
        self._rate_sync.start()

    def _on_rate_sync_finished(self, updated: int) -> None:
        self._refresh_rates_btn.setEnabled(True)
        self._rate_sync_status.setText(
            f"Updated {updated} day(s) of rates." if updated else "No new rates found (offline, or already up to date)."
        )
        self.refresh()

    # ── net worth: snapshots ────────────────────────────────────────────

    def _active_snapshot(self) -> dict | None:
        """The currently-active snapshot's full record, or None if there
        isn't one — regardless of whether "Use snapshot" is ticked (that
        check is the caller's job; this is just "which one is selected")."""
        active_id = settings.get_active_net_worth_snapshot_id()
        if active_id is None:
            return None
        for snap in settings.get_net_worth_snapshots():
            if snap["id"] == active_id:
                return snap
        return None

    _STALE_SNAPSHOT_DAYS = 60

    def _staleness_suffix(self, snapshot_date_iso: str) -> str:
        """A quiet one-line nudge appended to the snapshot status label
        when the active snapshot is more than _STALE_SNAPSHOT_DAYS old —
        the monthly ledger keeps extending itself automatically, but the
        entered *balances* only ever update when the user takes a fresh
        snapshot, so an old one silently drifts from reality the longer
        it goes untouched. No modal, no repeated nagging -- just this."""
        age_days = (Date.today() - Date.fromisoformat(snapshot_date_iso)).days
        if age_days <= self._STALE_SNAPSHOT_DAYS:
            return ""
        return f" Snapshot is {age_days} days old — consider taking a fresh one."

    def _applied_snapshot(self) -> dict | None:
        """The snapshot whose numbers should actually be used right now —
        None if "Use snapshot" is off, or nothing is active."""
        if not settings.get_net_worth_snapshot_use_enabled():
            return None
        return self._active_snapshot()

    def _extend_all_snapshots(self) -> None:
        """Every stored snapshot (active or not) grows its monthly ledger
        to cover through the current month, for as long as it exists —
        see module docstring. Cheap: only computes months that aren't
        already recorded."""
        today = Date.today()
        for snap in settings.get_net_worth_snapshots():
            snapshot_date = Date.fromisoformat(snap["date"])
            have = set(snap.get("monthly_history", {}).keys())
            missing = [d for d in month_starts(snapshot_date, today) if d.isoformat() not in have]
            if not missing:
                continue
            new_entries: dict = {}
            for month_start in missing:
                for currency, balance in snap["balances"].items():
                    new_entries.setdefault(month_start.isoformat(), {})[currency] = balance_at(
                        self._all_txs, currency, snapshot_date, balance, month_start
                    )
            settings.extend_net_worth_snapshot_history(snap["id"], new_entries)

    def _rebuild_net_worth_display(self) -> None:
        while self._nw_grid.count():
            item = self._nw_grid.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self._opening_labels = {}

        for col, h in enumerate(["Currency", "Opening cash", "Opening card"]):
            lbl = QLabel(h)
            lbl.setFont(QFont("Segoe UI", font_size("label"), QFont.Weight.Bold))
            lbl.setStyleSheet(f"color:{c('t2')}; background:transparent;")
            self._nw_grid.addWidget(lbl, 0, col)

        for row, currency in enumerate(self._currencies, start=1):
            name_lbl = QLabel(currency)
            name_lbl.setStyleSheet(f"color:{c('t1')}; background:transparent; font-weight:bold;")
            self._nw_grid.addWidget(name_lbl, row, 0)
            cash_lbl = QLabel("")
            cash_lbl.setStyleSheet(f"color:{c('t2')}; background:transparent;")
            card_lbl = QLabel("")
            card_lbl.setStyleSheet(f"color:{c('t2')}; background:transparent;")
            self._nw_grid.addWidget(cash_lbl, row, 1)
            self._nw_grid.addWidget(card_lbl, row, 2)
            self._opening_labels[currency] = (cash_lbl, card_lbl)

        self._refresh_opening_labels()

    def _refresh_opening_labels(self) -> None:
        snapshot = self._applied_snapshot()
        self._use_snapshot_check.blockSignals(True)
        self._use_snapshot_check.setEnabled(self._active_snapshot() is not None)
        self._use_snapshot_check.setChecked(settings.get_net_worth_snapshot_use_enabled())
        self._use_snapshot_check.blockSignals(False)

        active = self._active_snapshot()
        if active is None:
            self._snapshot_status_lbl.setText("No snapshot yet — click \"Take snapshot\" to get started.")
        elif snapshot is None:
            text = f"Active snapshot: {active['date']} — currently not applied (tick \"Use snapshot\")."
            self._snapshot_status_lbl.setText(text + self._staleness_suffix(active["date"]))
        else:
            text = f"Active snapshot: {snapshot['date']} (taken {snapshot['taken_at'][:16].replace('T', ' ')})."
            self._snapshot_status_lbl.setText(text + self._staleness_suffix(snapshot["date"]))

        for currency, (cash_lbl, card_lbl) in self._opening_labels.items():
            opening = snapshot.get("opening", {}).get(currency) if snapshot is not None else None
            if opening is None:
                cash_lbl.setText("—")
                card_lbl.setText("—")
            else:
                cash_lbl.setText(fmt_amount(opening["cash"], currency))
                card_lbl.setText(fmt_amount(opening["card"], currency))

    def _on_take_snapshot_clicked(self) -> None:
        dlg = TakeSnapshotDialog(self._currencies, self._all_txs, parent=self)
        if dlg.exec():
            self.refresh()

    def _on_manage_snapshots_clicked(self) -> None:
        dlg = ManageSnapshotsDialog(parent=self)
        dlg.exec()
        self.refresh()

    def _on_use_toggled(self, checked: bool) -> None:
        settings.set_net_worth_snapshot_use_enabled(checked)
        self._refresh_opening_labels()
        self._refresh_total()
        self._refresh_currency_detail()

    # ── total right now ───────────────────────────────────────────────────

    def _latest_rate_schema(self) -> YearSchema | None:
        years = _currency_tracked_years()
        if not years:
            return None
        target = Date.today().year if Date.today().year in years else max(years)
        return registry.get_schema_for_date(Date(target, 1, 1))

    def _refresh_total(self, *_args) -> None:
        to_currency = self._total_currency_combo.currentText()
        if not to_currency or not self._currencies:
            self._total_lbl.setText("—")
            return
        schema = self._latest_rate_schema()
        rates = schema.get_rates() if schema is not None else None
        if not rates:
            self._total_lbl.setText("—")
            return

        snapshot = self._applied_snapshot()
        if snapshot is None:
            self._total_lbl.setText("—")
            return

        to_rate = rates.get(to_currency)
        if to_rate is None:
            self._total_lbl.setText("—")
            return

        total = 0.0
        for currency, amounts in snapshot.get("balances", {}).items():
            amount = (amounts.get("cash", 0.0) or 0.0) + (amounts.get("card", 0.0) or 0.0)
            from_rate = rates.get(currency)
            if from_rate is None or amount == 0:
                continue
            total += amount * from_rate / to_rate
        self._total_lbl.setText(fmt_amount(total, to_currency))

    # ── per-currency movement ─────────────────────────────────────────────

    def _refresh_currency_detail(self, *_args) -> None:
        currency = self._currency_combo.currentText()
        filtered = [(schema, tx) for schema, tx in self._all_txs if tx.get("currency") == currency]

        snapshot = self._applied_snapshot()
        history = snapshot.get("monthly_history", {}) if snapshot is not None else {}
        currency_history = {month_iso: entry[currency] for month_iso, entry in history.items() if currency in entry}

        if currency_history:
            points = []
            for i, month_iso in enumerate(sorted(currency_history)):
                bal = currency_history[month_iso]
                month_date = Date.fromisoformat(month_iso)
                label = f"{MONTH_NAMES[month_date.month - 1][:3]} '{month_date.year % 100:02d}"
                points.append((label, bal["cash"] + bal["card"], float(i)))
            self._chart.update_data(points)
            self._chart_anchor_lbl.setText(
                f"Real balance history, anchored to the {currency} snapshot taken {snapshot['date']}."
            )
        else:
            # No applied snapshot (or this currency wasn't part of it) --
            # fall back to a relative-to-zero running total, same as before
            # snapshots existed at all.
            monthly: dict[tuple[int, int], float] = {}
            for schema, tx in filtered:
                date_val = tx.get("date")
                if date_val is None:
                    continue
                key = (date_val.year, date_val.month)
                t = tx.get("type")
                amt = tx.get("amount") or 0
                if schema.is_income_type(t):
                    monthly[key] = monthly.get(key, 0.0) + amt
                elif schema.is_expense_type(t):
                    monthly[key] = monthly.get(key, 0.0) - amt

            points = []
            running = 0.0
            for i, key in enumerate(sorted(monthly)):
                running += monthly[key]
                points.append((f"{MONTH_NAMES[key[1] - 1][:3]} '{key[0] % 100:02d}", running, float(i)))
            self._chart.update_data(points)
            self._chart_anchor_lbl.setText(
                "No snapshot applied — showing movement relative to zero, not a real balance."
            )

        rows = sorted(filtered, key=_sort_key, reverse=True)
        self._table.setRowCount(len(rows))
        for row, (schema, tx) in enumerate(rows):
            date_val = tx.get("date")
            date_str = date_val.strftime("%Y-%m-%d") if date_val else tx.get("month", "")
            self._table.setItem(row, 0, QTableWidgetItem(date_str))
            self._table.setItem(row, 1, QTableWidgetItem(tx.get("type") or ""))
            self._table.setItem(row, 2, QTableWidgetItem(tx.get("category") or ""))
            self._table.setItem(row, 3, QTableWidgetItem(tx.get("payment_type") or ""))
            amount_item = QTableWidgetItem(fmt_amount(tx.get("amount") or 0, currency))
            is_expense = schema.is_expense_type(tx.get("type"))
            amount_item.setForeground(QColor(c("expense_c") if is_expense else c("income_c")))
            self._table.setItem(row, 4, amount_item)
            self._table.setItem(row, 5, QTableWidgetItem(tx.get("note") or ""))
