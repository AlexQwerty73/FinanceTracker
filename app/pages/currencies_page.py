"""
app/pages/currencies_page.py — CurrenciesPage: net worth / opening-balance
snapshot across every currency-tracked year, plus a per-currency
balance-over-time view and transaction list. All-time / all-years by
design (not scoped to the TopBar's selected month) — refreshed lazily
when the page becomes visible, mirroring Analytics/Categories.

Opening balance: the user enters *today's* real cash+card amount per
currency; this page subtracts the net effect of every recorded
transaction in that currency (income adds, expense subtracts, cash/card
split the same way AnalyticsPage._cash_card_delta classifies it — but in
NATIVE currency units here, not converted to any base currency) to back
out what the balance must have been before the first transaction.

"Total right now" converts every currency's current cash+card figure
into one chosen currency at *today's* rate (read fresh from whichever
currency-tracked year's Lists sheet is most current) — a deliberately
different number from any transaction's own converted total, which used
whatever rate was in effect when it was read, not necessarily today's.
"""
from __future__ import annotations

from datetime import date as Date

from PyQt6.QtGui import QColor, QFont
from PyQt6.QtWidgets import (
    QGridLayout, QHBoxLayout, QLabel, QLineEdit, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

from core import settings
from core.excel import registry
from core.excel.base import MONTH_NAMES, YearSchema
from core.format import fmt_amount
from core.themes import c, font_size

from ..components.charts import BalanceLineChart
from ..components.transaction_fields import field_label, input_style
from ..components.widgets import NoWheelComboBox, card, scrollable_area, section_label


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


def _all_currency_transactions() -> list[tuple[YearSchema, dict]]:
    """(schema, tx) for every transaction in every currency-tracked year,
    every month — the base dataset both the net-worth calc and the
    per-currency chart/list scan over."""
    out = []
    for y in _currency_tracked_years():
        schema = registry.get_schema_for_date(Date(y, 1, 1))
        for m in range(1, 13):
            for tx in schema.transactions_for_month(m):
                if tx.get("currency"):
                    out.append((schema, tx))
    return out


def _native_cash_card_delta(schema, tx: dict) -> tuple[float, float]:
    """Same classification as AnalyticsPage._cash_card_delta, but in the
    transaction's own native currency units (no base-currency conversion)
    — this page needs "how much of currency X moved through cash/card",
    not a cross-currency total."""
    t, payment, amt = tx.get("type"), tx.get("payment_type"), tx.get("amount") or 0
    cash_delta = 0.0
    if schema.is_cash_in_type(t):
        cash_delta += amt
    elif schema.is_cash_out_type(t) or (schema.is_expense_type(t) and payment == "Cash"):
        cash_delta -= amt
    balance_delta = amt if schema.is_income_type(t) else (-amt if schema.is_expense_type(t) else 0.0)
    return cash_delta, balance_delta - cash_delta


def _sort_key(item: tuple[YearSchema, dict]) -> tuple:
    date_val = item[1].get("date")
    if date_val is None:
        return (0,)
    if hasattr(date_val, "date"):
        date_val = date_val.date()
    return (1, date_val)


def _parse_amount(text: str) -> float:
    try:
        return float(text.strip().replace(",", "."))
    except ValueError:
        return 0.0


class CurrenciesPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._all_txs: list[tuple[YearSchema, dict]] = []
        self._currencies: list[str] = []
        self._nw_rows: dict[str, tuple[QLineEdit, QLineEdit, QLabel, QLabel]] = {}

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
            "Enter what you actually have right now — the opening balance "
            "(before your first recorded transaction) is worked out automatically."
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

        lay.addWidget(self._nw_box)

        # ── Per-currency movement card ───────────────────────────────────
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
        saved = set(settings.get_net_worth().keys())
        self._currencies = sorted(seen | saved)

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

        self._rebuild_net_worth_grid()
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

    # ── net worth grid ────────────────────────────────────────────────────

    def _rebuild_net_worth_grid(self) -> None:
        while self._nw_grid.count():
            item = self._nw_grid.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self._nw_rows = {}

        for col, h in enumerate(["Currency", "Cash", "Card", "Opening cash", "Opening card"]):
            lbl = QLabel(h)
            lbl.setFont(QFont("Segoe UI", font_size("label"), QFont.Weight.Bold))
            lbl.setStyleSheet(f"color:{c('t2')}; background:transparent;")
            self._nw_grid.addWidget(lbl, 0, col)

        saved = settings.get_net_worth()
        for row, currency in enumerate(self._currencies, start=1):
            entry = saved.get(currency, {})
            name_lbl = QLabel(currency)
            name_lbl.setStyleSheet(f"color:{c('t1')}; background:transparent; font-weight:bold;")
            self._nw_grid.addWidget(name_lbl, row, 0)

            cash_field = QLineEdit(f"{entry.get('cash', 0.0) or 0.0:g}")
            cash_field.setFixedWidth(90)
            cash_field.setStyleSheet(input_style())
            card_field = QLineEdit(f"{entry.get('card', 0.0) or 0.0:g}")
            card_field.setFixedWidth(90)
            card_field.setStyleSheet(input_style())
            self._nw_grid.addWidget(cash_field, row, 1)
            self._nw_grid.addWidget(card_field, row, 2)

            opening_cash_lbl = QLabel("")
            opening_cash_lbl.setStyleSheet(f"color:{c('t2')}; background:transparent;")
            opening_card_lbl = QLabel("")
            opening_card_lbl.setStyleSheet(f"color:{c('t2')}; background:transparent;")
            self._nw_grid.addWidget(opening_cash_lbl, row, 3)
            self._nw_grid.addWidget(opening_card_lbl, row, 4)

            self._nw_rows[currency] = (cash_field, card_field, opening_cash_lbl, opening_card_lbl)
            cash_field.editingFinished.connect(lambda cur=currency: self._on_net_worth_edited(cur))
            card_field.editingFinished.connect(lambda cur=currency: self._on_net_worth_edited(cur))

            self._recompute_opening(currency)

    def _recompute_opening(self, currency: str) -> None:
        cash_field, card_field, opening_cash_lbl, opening_card_lbl = self._nw_rows[currency]
        cash_input = _parse_amount(cash_field.text())
        card_input = _parse_amount(card_field.text())

        cash_moved = card_moved = 0.0
        for schema, tx in self._all_txs:
            if tx.get("currency") != currency:
                continue
            cd, kd = _native_cash_card_delta(schema, tx)
            cash_moved += cd
            card_moved += kd

        opening_cash_lbl.setText(fmt_amount(cash_input - cash_moved, currency))
        opening_card_lbl.setText(fmt_amount(card_input - card_moved, currency))

    def _on_net_worth_edited(self, currency: str) -> None:
        cash_field, card_field, *_rest = self._nw_rows[currency]
        settings.set_net_worth_entry(currency, _parse_amount(cash_field.text()), _parse_amount(card_field.text()))
        self._recompute_opening(currency)
        self._refresh_total()

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

        saved = settings.get_net_worth()
        to_rate = rates.get(to_currency)
        if to_rate is None:
            self._total_lbl.setText("—")
            return

        total = 0.0
        for currency in self._currencies:
            entry = saved.get(currency, {})
            amount = (entry.get("cash", 0.0) or 0.0) + (entry.get("card", 0.0) or 0.0)
            from_rate = rates.get(currency)
            if from_rate is None or amount == 0:
                continue
            total += amount * from_rate / to_rate
        self._total_lbl.setText(fmt_amount(total, to_currency))

    # ── per-currency movement ─────────────────────────────────────────────

    def _refresh_currency_detail(self, *_args) -> None:
        currency = self._currency_combo.currentText()
        filtered = [(schema, tx) for schema, tx in self._all_txs if tx.get("currency") == currency]

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
