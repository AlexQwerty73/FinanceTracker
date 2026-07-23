"""
app/pages/dashboard_page.py — DashboardPage: at-a-glance totals and charts
for the viewed month only (how the balance progressed day by day, expense
and income breakdowns by category), plus a short preview of the most
recent transactions. The full, editable list lives on TransactionsPage;
multi-month/year views live on AnalyticsPage — this page stays tightly
scoped to "this month" so it never gets cluttered.
"""
from __future__ import annotations

from datetime import date as Date

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QCursor, QFont
from PyQt6.QtWidgets import (
    QGridLayout, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget,
)

from core import settings
from core.excel import registry
from core.excel.workbook_io import WorkbookLockedError
from core.format import fmt_amount
from core.themes import c, font_size, radius

from ..components.charts import CategoryPieChart, RunningBalanceChart
from ..components.widgets import bordered_box, card, scrollable_area, section_label

_FORECAST_MONTHS = 6
_FORECAST_MIN_MONTHS = 3

_TILES = [
    ("income", "Income", "income_c"),
    ("expense", "Expense", "expense_c"),
    ("invest", "Invest", "invest_c"),
    ("balance", "Balance", "t1"),
    ("cash", "Cash", "t1"),  # color/text overridden dynamically in refresh() — sign-dependent, not fixed
    ("card", "Card", "t1"),  # same — see _set_signed_tile()
]
_SIGNED_TILES = {"cash", "card"}
_TILES_PER_ROW = len(_TILES)

_PREVIEW_ROWS = 5


def _current_snapshot_total(schema) -> tuple[float, str] | None:
    """(total in `schema`'s base currency, snapshot date) from the
    Currencies page's applied net-worth snapshot's raw entered balances —
    None if snapshot use is switched off, nothing is active, or the
    active snapshot's currencies can't be converted (no current rate
    known). Deliberately the plain entered figures, not rolled forward via
    core/net_worth_ledger.balance_at() to today — the snapshot's own date
    is shown alongside so a stale snapshot reads as stale, not as a
    silently "corrected" number (see the snapshot-staleness hint on the
    Currencies page for the other half of that same nudge)."""
    if not settings.get_net_worth_snapshot_use_enabled():
        return None
    active_id = settings.get_active_net_worth_snapshot_id()
    if active_id is None:
        return None
    snapshot = next((s for s in settings.get_net_worth_snapshots() if s["id"] == active_id), None)
    if snapshot is None:
        return None
    base_currency = schema.get_base_currency()
    rates = schema.get_rates() if base_currency else None
    total = 0.0
    for currency, amounts in snapshot.get("balances", {}).items():
        amount = (amounts.get("cash", 0.0) or 0.0) + (amounts.get("card", 0.0) or 0.0)
        if base_currency is None:
            total += amount  # no currency tracking at all -- one implicit currency
            continue
        rate = 1.0 if currency == base_currency else (rates or {}).get(currency)
        if rate is None:
            continue
        total += amount * rate
    return total, snapshot["date"]


def _recent_average_balance() -> tuple[float, int] | None:
    """(average month_summary()["balance"], month count) over the last up
    to _FORECAST_MONTHS full (already-completed) months before today,
    walking backward across year boundaries via registry as needed —
    anchored at today regardless of which month the Dashboard happens to
    be viewing, since a forecast is inherently about "from now on". None
    if fewer than _FORECAST_MIN_MONTHS of those months could actually be
    read (a new install with little history yet, or an unregistered
    older year)."""
    today = Date.today()
    y, m = today.year, today.month
    values: list[float] = []
    for _ in range(_FORECAST_MONTHS):
        m -= 1
        if m == 0:
            m, y = 12, y - 1
        try:
            schema = registry.get_schema_for_date(Date(y, m, 1))
            values.append(schema.month_summary(m)["balance"])
        except (ValueError, WorkbookLockedError):
            break
    if len(values) < _FORECAST_MIN_MONTHS:
        return None
    return sum(values) / len(values), len(values)


class DashboardPage(QWidget):
    view_all_clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._year = Date.today().year
        self._month = Date.today().month

        outer_lay = QVBoxLayout(self)
        outer_lay.setContentsMargins(0, 0, 0, 0)

        content = QWidget()
        content.setStyleSheet("background:transparent;")
        outer_lay.addWidget(scrollable_area(content))

        lay = QVBoxLayout(content)
        lay.setContentsMargins(4, 4, 4, 20)
        lay.setSpacing(16)

        self._status = QLabel("")
        self._status.setWordWrap(True)
        self._status.setStyleSheet(f"color:{c('err_c')}; background:transparent;")
        lay.addWidget(self._status)

        tiles_grid = QGridLayout()
        tiles_grid.setSpacing(10)
        self._tile_labels: dict[str, QLabel] = {}
        for i, (key, title, color_key) in enumerate(_TILES):
            box = bordered_box(c("panel_bg"), c("panel_bd"), radius=radius("lg"))
            box_lay = QVBoxLayout(box)
            box_lay.setContentsMargins(16, 12, 16, 12)
            box_lay.setSpacing(2)
            title_lbl = QLabel(title)
            title_lbl.setFont(QFont("Segoe UI", font_size("label")))
            title_lbl.setStyleSheet(f"color:{c('t2')}; background:transparent;")
            value_row = QHBoxLayout()
            value_row.setSpacing(6)
            value_lbl = QLabel("0.00")
            value_lbl.setFont(QFont("Segoe UI", font_size("stat"), QFont.Weight.Bold))
            value_lbl.setStyleSheet(f"color:{c(color_key)}; background:transparent;")
            value_row.addWidget(value_lbl)
            if key == "balance":
                self._growth_badge_lbl = QLabel("")
                self._growth_badge_lbl.setFont(QFont("Segoe UI", font_size("micro"), QFont.Weight.Bold))
                self._growth_badge_lbl.setVisible(False)
                value_row.addWidget(self._growth_badge_lbl)
            value_row.addStretch()
            box_lay.addWidget(title_lbl)
            box_lay.addLayout(value_row)
            tiles_grid.addWidget(box, i // _TILES_PER_ROW, i % _TILES_PER_ROW)
            self._tile_labels[key] = value_lbl
        lay.addLayout(tiles_grid)

        self._forecast_box = bordered_box(c("panel_bg"), c("panel_bd"), radius=radius("lg"))
        self._forecast_box.setVisible(False)
        forecast_lay = QVBoxLayout(self._forecast_box)
        forecast_lay.setContentsMargins(16, 12, 16, 12)
        forecast_lay.setSpacing(2)
        forecast_title = QLabel("Cash-flow forecast")
        forecast_title.setFont(QFont("Segoe UI", font_size("label")))
        forecast_title.setStyleSheet(f"color:{c('t2')}; background:transparent;")
        forecast_lay.addWidget(forecast_title)
        self._forecast_lbl = QLabel("")
        self._forecast_lbl.setWordWrap(True)
        self._forecast_lbl.setFont(QFont("Segoe UI", font_size("stat"), QFont.Weight.Bold))
        self._forecast_lbl.setStyleSheet(f"color:{c('t1')}; background:transparent;")
        forecast_lay.addWidget(self._forecast_lbl)
        self._forecast_note_lbl = QLabel("")
        self._forecast_note_lbl.setWordWrap(True)
        self._forecast_note_lbl.setFont(QFont("Segoe UI", font_size("micro")))
        self._forecast_note_lbl.setStyleSheet(f"color:{c('t3')}; background:transparent;")
        forecast_lay.addWidget(self._forecast_note_lbl)
        lay.addWidget(self._forecast_box)

        balance_box, balance_lay = card("Balance this month")
        self._balance_chart = RunningBalanceChart()
        balance_lay.addWidget(self._balance_chart)
        lay.addWidget(balance_box)

        pies_row = QHBoxLayout()
        pies_row.setSpacing(16)
        expense_box, expense_lay = card("Expenses by category")
        self._expense_pie = CategoryPieChart()
        expense_lay.addWidget(self._expense_pie)
        pies_row.addWidget(expense_box, 1)

        income_box, income_lay = card("Income by category")
        self._income_pie = CategoryPieChart()
        income_lay.addWidget(self._income_pie)
        pies_row.addWidget(income_box, 1)
        lay.addLayout(pies_row)

        preview_box = bordered_box(c("panel_bg"), c("panel_bd"), radius=radius("xl"))
        preview_lay = QVBoxLayout(preview_box)
        preview_lay.setContentsMargins(20, 16, 20, 16)
        preview_lay.setSpacing(6)

        preview_hdr = QHBoxLayout()
        preview_hdr.addWidget(section_label("Recent transactions"))
        preview_hdr.addStretch()
        view_all_btn = QPushButton("View all →")
        view_all_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        view_all_btn.setStyleSheet(f"""
            QPushButton {{ background:transparent; color:{c('ac')}; border:none; }}
            QPushButton:hover {{ text-decoration:underline; }}
        """)
        view_all_btn.clicked.connect(self.view_all_clicked.emit)
        preview_hdr.addWidget(view_all_btn)
        preview_lay.addLayout(preview_hdr)

        self._preview_rows: list[QWidget] = []
        self._preview_list_lay = QVBoxLayout()
        self._preview_list_lay.setSpacing(2)
        preview_lay.addLayout(self._preview_list_lay)
        self._empty_lbl = QLabel("No transactions yet this month.")
        self._empty_lbl.setStyleSheet(f"color:{c('t3')}; background:transparent;")
        preview_lay.addWidget(self._empty_lbl)
        lay.addWidget(preview_box)

    def refresh(self, year: int, month: int) -> None:
        self._year, self._month = year, month
        try:
            schema = registry.get_schema_for_date(Date(year, month, 1))
        except ValueError as exc:
            self._status.setText(str(exc))
            return

        try:
            summary = schema.month_summary(month)
            txs = schema.transactions_for_month(month)
        except WorkbookLockedError as exc:
            self._status.setText(str(exc))
            return

        base_currency = schema.get_base_currency()
        self._status.setText("")
        self._refresh_growth_badge(year, month, summary["balance"])
        for key, _title, _color in _TILES:
            if key in _SIGNED_TILES:
                continue
            self._tile_labels[key].setText(fmt_amount(summary[key], base_currency))
        for key in _SIGNED_TILES:
            self._set_signed_tile(key, summary.get(key), base_currency)

        expense_breakdown: dict[str, float] = {}
        income_breakdown: dict[str, float] = {}
        for tx in txs:
            cat = tx.get("category") or "Other"
            amt = schema.convert_transaction(tx)
            if schema.is_expense_type(tx.get("type")):
                expense_breakdown[cat] = expense_breakdown.get(cat, 0.0) + amt
            elif schema.is_income_type(tx.get("type")):
                income_breakdown[cat] = income_breakdown.get(cat, 0.0) + amt
        self._expense_pie.update_data(expense_breakdown)
        self._income_pie.update_data(income_breakdown)

        self._balance_chart.update_data(self._build_running_balance(schema, txs))
        self._render_preview(schema, txs[:_PREVIEW_ROWS])
        self._refresh_forecast(schema)

    def _refresh_forecast(self, schema) -> None:
        """'At this rate, cash lasts ~N months' — current balance from the
        applied net-worth snapshot (Currencies page), divided by the
        average net monthly spend over the last few full months. Hidden
        entirely (not shown as a misleading number) unless there's both an
        applied snapshot and enough recent history to average — no
        recurring-expense detection, just the plain trend, per the user's
        own choice of the simple version over a subscription-based one."""
        total = _current_snapshot_total(schema)
        recent = _recent_average_balance()
        if total is None or recent is None:
            self._forecast_box.setVisible(False)
            return
        current_balance, snapshot_date = total
        avg_balance, month_count = recent
        if avg_balance >= 0 or current_balance <= 0:
            # Net saving lately, or nothing left to project from -- "cash
            # lasts forever" isn't a useful number to show either way.
            self._forecast_box.setVisible(False)
            return

        months_left = current_balance / -avg_balance
        self._forecast_box.setVisible(True)
        self._forecast_lbl.setText(f"~{months_left:.1f} months")
        self._forecast_note_lbl.setText(
            f"At the average net spend over the last {month_count} months, based on the net worth "
            f"snapshot from {snapshot_date}."
        )

    def _refresh_growth_badge(self, year: int, month: int, this_month_balance: float) -> None:
        """'+X.X%' next to the Balance tile, vs. the previous calendar
        month's own balance — hidden entirely (not shown as a misleading
        0%) if that previous month's year isn't registered, or its own
        balance was exactly 0 (no defined % change), matching the same
        rule Analytics' growth grid already uses."""
        prev_month, prev_year = (12, year - 1) if month == 1 else (month - 1, year)
        try:
            prev_schema = registry.get_schema_for_date(Date(prev_year, prev_month, 1))
            prev_balance = prev_schema.month_summary(prev_month)["balance"]
        except (ValueError, WorkbookLockedError):
            self._growth_badge_lbl.setVisible(False)
            return
        if not prev_balance:  # None or 0 -- no defined % change to show
            self._growth_badge_lbl.setVisible(False)
            return
        pct = (this_month_balance - prev_balance) / abs(prev_balance) * 100
        self._growth_badge_lbl.setText(f"{pct:+.1f}% vs last month")
        self._growth_badge_lbl.setStyleSheet(
            f"color:{c('income_c') if pct >= 0 else c('expense_c')}; background:transparent;"
        )
        self._growth_badge_lbl.setVisible(True)

    def _set_signed_tile(self, key: str, value: float | None, base_currency: str | None = None) -> None:
        lbl = self._tile_labels[key]
        if value is None:
            lbl.setText("N/A")
            lbl.setStyleSheet(f"color:{c('t3')}; background:transparent;")
        else:
            sign = "+" if value >= 0 else "-"
            lbl.setText(f"{sign}{fmt_amount(abs(value), base_currency)}")
            lbl.setStyleSheet(f"color:{c('income_c') if value >= 0 else c('expense_c')}; background:transparent;")

    def _build_running_balance(self, schema, txs: list[dict]) -> list[tuple[int, float]] | None:
        if not schema.HAS_DAILY_DATES:
            return None
        daily_delta: dict[int, float] = {}
        for tx in txs:
            d = tx.get("date")
            if d is None:
                continue
            amt = schema.convert_transaction(tx)
            if schema.is_income_type(tx.get("type")):
                daily_delta[d.day] = daily_delta.get(d.day, 0.0) + amt
            elif schema.is_expense_type(tx.get("type")):
                daily_delta[d.day] = daily_delta.get(d.day, 0.0) - amt
        if not daily_delta:
            return []
        running = 0.0
        points = []
        for day in range(1, max(daily_delta) + 1):
            running += daily_delta.get(day, 0.0)
            points.append((day, running))
        return points

    def _render_preview(self, schema, txs: list[dict]) -> None:
        for row in self._preview_rows:
            self._preview_list_lay.removeWidget(row)
            row.deleteLater()
        self._preview_rows.clear()

        self._empty_lbl.setVisible(len(txs) == 0)
        for tx in txs:
            row = QWidget()
            row.setStyleSheet("background:transparent;")
            row_lay = QHBoxLayout(row)
            row_lay.setContentsMargins(0, 4, 0, 4)

            date_val = tx.get("date")
            date_str = date_val.strftime("%Y-%m-%d") if date_val else tx.get("month", "")
            left = QLabel(f"{date_str}  ·  {tx.get('category') or ''}")
            left.setStyleSheet(f"color:{c('t1')}; background:transparent;")
            row_lay.addWidget(left, 1)

            is_expense = schema.is_expense_type(tx.get("type"))
            amount_color = c("expense_c") if is_expense else c("income_c")
            sign = "-" if is_expense else "+"
            tx_currency = tx.get("currency") or schema.get_base_currency()
            amount_lbl = QLabel(f"{sign}{fmt_amount(tx.get('amount') or 0, tx_currency)}")
            amount_lbl.setStyleSheet(f"color:{amount_color}; background:transparent; font-weight:bold;")
            row_lay.addWidget(amount_lbl)

            self._preview_list_lay.addWidget(row)
            self._preview_rows.append(row)
