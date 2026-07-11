"""
app/pages/analytics_page.py — AnalyticsPage: multi-month/year views a
single month can't show — cumulative balance and cash-flow trends over a
selectable period (monthly or daily granularity: one axis is the period,
the other is the running balance), a GitHub-style daily-expense heatmap for
a chosen year, and a category breakdown pie for the selected period. Every
trend stops at the current month/day — no projected "0" future periods on
the line. Refreshed lazily (only when shown, or when the shared month
changes while it's the active page) since it reads every month in the
selected range rather than just one.
"""
from __future__ import annotations

import calendar
from datetime import date as Date

from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QScrollArea, QVBoxLayout, QWidget

from core.excel import registry
from core.excel.base import MONTH_NAMES
from core.excel.workbook_io import WorkbookLockedError
from core.themes import c

from ..components.charts import BalanceLineChart, CalendarHeatmap, CategoryPieChart
from ..components.transaction_fields import input_style
from ..components.widgets import NoWheelComboBox, bordered_box

_PERIODS = ["Last 6 months", "Last 12 months", "This year", "All time"]
_GRANULARITIES = ["Monthly", "Daily"]


def _section_label(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
    lbl.setStyleSheet(f"color:{c('t2')}; background:transparent;")
    return lbl


def _control_label(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setFont(QFont("Segoe UI", 9))
    lbl.setStyleSheet(f"color:{c('t2')}; background:transparent;")
    return lbl


def _card(title: str) -> tuple[QWidget, QVBoxLayout]:
    box = bordered_box(c("panel_bg"), c("panel_bd"), radius=14)
    lay = QVBoxLayout(box)
    lay.setContentsMargins(20, 16, 20, 16)
    lay.setSpacing(8)
    lay.addWidget(_section_label(title))
    return box, lay


def _periods_for_selection(selection: str, end_year: int, end_month: int) -> list[tuple[int, int]]:
    floor = registry.min_supported_period()
    today = Date.today()
    ceiling = min(registry.max_supported_period(), (today.year, today.month))
    end_year, end_month = min((end_year, end_month), ceiling)

    if selection == "All time":
        periods = []
        y, m = floor
        while (y, m) <= ceiling:
            periods.append((y, m))
            m += 1
            if m == 13:
                y, m = y + 1, 1
        return periods

    if selection == "This year":
        return [(end_year, m) for m in range(1, 13) if floor <= (end_year, m) <= ceiling]

    count = 6 if selection == "Last 6 months" else 12
    periods: list[tuple[int, int]] = []
    y, m = end_year, end_month
    while len(periods) < count:
        periods.append((y, m))
        if (y, m) <= floor:
            break
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    periods.reverse()
    return periods


class AnalyticsPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._year = Date.today().year
        self._month = Date.today().month

        outer_lay = QVBoxLayout(self)
        outer_lay.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet(f"""
            QScrollArea {{ background:transparent; border:none; }}
            QScrollBar:vertical {{ background:transparent; width:8px; }}
            QScrollBar::handle:vertical {{ background:{c('in_bd')}; border-radius:4px; min-height:24px; }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height:0; }}
        """)
        outer_lay.addWidget(scroll)

        content = QWidget()
        content.setStyleSheet("background:transparent;")
        scroll.setWidget(content)

        lay = QVBoxLayout(content)
        lay.setContentsMargins(4, 4, 4, 20)
        lay.setSpacing(16)

        controls = QHBoxLayout()
        controls.addWidget(_control_label("Period"))
        self._period_combo = NoWheelComboBox()
        self._period_combo.addItems(_PERIODS)
        self._period_combo.setCurrentText("Last 12 months")
        self._period_combo.setFixedHeight(30)
        self._period_combo.setStyleSheet(input_style())
        self._period_combo.currentTextChanged.connect(self._on_controls_changed)
        controls.addWidget(self._period_combo)

        controls.addSpacing(24)
        controls.addWidget(_control_label("Granularity"))
        self._granularity_combo = NoWheelComboBox()
        self._granularity_combo.addItems(_GRANULARITIES)
        self._granularity_combo.setFixedHeight(30)
        self._granularity_combo.setStyleSheet(input_style())
        self._granularity_combo.currentTextChanged.connect(self._on_controls_changed)
        controls.addWidget(self._granularity_combo)

        controls.addSpacing(24)
        controls.addWidget(_control_label("Heatmap year"))
        self._year_combo = NoWheelComboBox()
        self._year_combo.addItems([str(y) for y in registry.supported_years()])
        default_year = str(Date.today().year)
        if self._year_combo.findText(default_year) >= 0:
            self._year_combo.setCurrentText(default_year)
        self._year_combo.setFixedHeight(30)
        self._year_combo.setStyleSheet(input_style())
        self._year_combo.currentTextChanged.connect(self._on_controls_changed)
        controls.addWidget(self._year_combo)
        controls.addStretch()
        lay.addLayout(controls)

        self._status = QLabel("")
        self._status.setWordWrap(True)
        self._status.setStyleSheet(f"color:{c('err_c')}; background:transparent;")
        lay.addWidget(self._status)

        trend_box, trend_lay = _card("Balance over time")
        self._balance_line = BalanceLineChart()
        trend_lay.addWidget(self._balance_line)
        lay.addWidget(trend_box)

        cash_box, cash_lay = _card("Cash flow")
        self._cash_flow = BalanceLineChart()
        cash_lay.addWidget(self._cash_flow)
        lay.addWidget(cash_box)

        card_box, card_lay = _card("Card flow")
        self._card_flow = BalanceLineChart()
        card_lay.addWidget(self._card_flow)
        lay.addWidget(card_box)

        heat_box, heat_lay = _card("Daily expenses")
        self._heatmap = CalendarHeatmap()
        heat_lay.addWidget(self._heatmap)
        lay.addWidget(heat_box)

        pies_row = QHBoxLayout()
        pies_row.setSpacing(16)
        expense_pie_box, expense_pie_lay = _card("Expenses by category (selected period)")
        self._pie = CategoryPieChart()
        expense_pie_lay.addWidget(self._pie)
        pies_row.addWidget(expense_pie_box, 1)

        income_pie_box, income_pie_lay = _card("Income by category (selected period)")
        self._income_pie = CategoryPieChart()
        income_pie_lay.addWidget(self._income_pie)
        pies_row.addWidget(income_pie_box, 1)
        lay.addLayout(pies_row)

    def _on_controls_changed(self, _text: str = "") -> None:
        self.refresh(self._year, self._month)

    def refresh(self, year: int, month: int) -> None:
        self._year, self._month = year, month
        selection = self._period_combo.currentText()
        daily = self._granularity_combo.currentText() == "Daily"
        today = Date.today()
        periods = _periods_for_selection(selection, year, month)
        period_start = Date(periods[0][0], periods[0][1], 1) if periods else today

        balance_points: list[tuple[str, float, float]] = []
        cash_points: list[tuple[str, float, float]] = []
        card_points: list[tuple[str, float, float]] = []
        expense_breakdown: dict[str, float] = {}
        income_breakdown: dict[str, float] = {}
        balance_total = 0.0
        cash_total = 0.0
        card_total = 0.0

        try:
            for y, m in periods:
                schema = registry.get_schema_for_date(Date(y, m, 1))
                has_cash_tracking = schema.has_cash_tracking()
                txs = schema.transactions_for_month(m)

                for tx in txs:
                    cat = tx.get("category") or "Other"
                    amt = tx.get("amount") or 0
                    if schema.is_expense_type(tx.get("type")):
                        expense_breakdown[cat] = expense_breakdown.get(cat, 0.0) + amt
                    elif schema.is_income_type(tx.get("type")):
                        income_breakdown[cat] = income_breakdown.get(cat, 0.0) + amt

                if daily and schema.HAS_DAILY_DATES:
                    balance_total, cash_total, card_total = self._append_daily_points(
                        schema, txs, y, m, today, has_cash_tracking, period_start,
                        balance_points, cash_points, card_points, balance_total, cash_total, card_total,
                    )
                else:
                    balance_total, cash_total, card_total = self._append_monthly_points(
                        schema, txs, y, m, has_cash_tracking, period_start,
                        balance_points, cash_points, card_points, balance_total, cash_total, card_total,
                    )
        except WorkbookLockedError as exc:
            self._status.setText(str(exc))
            return

        self._status.setText("")
        # Balance always has full coverage (every period contributes,
        # tracked or not) — use its span as the shared x-axis for all three
        # charts so they stay visually aligned even where cash/card-flow
        # data is sparser (e.g. a stretch with no tagged transactions at all).
        x_values = [p[2] for p in balance_points]
        shared_range = (min(x_values), max(x_values)) if x_values else None
        if shared_range is not None:
            pad = (shared_range[1] - shared_range[0]) * 0.02 or 1
            shared_range = (shared_range[0] - pad, shared_range[1] + pad)
        self._balance_line.update_data(balance_points, shared_range)
        self._cash_flow.update_data(cash_points, shared_range)
        self._card_flow.update_data(card_points, shared_range)
        self._pie.update_data(expense_breakdown)
        self._income_pie.update_data(income_breakdown)

        self._refresh_heatmap()

    @staticmethod
    def _cash_card_delta(schema, tx: dict) -> tuple[float, float]:
        """(cash_delta, card_delta) for one transaction — same detection as
        Schema.month_summary()'s "cash"/"card" figures. card_delta is
        *derived* (balance_delta - cash_delta), not tagged from the row's
        own Payment field — most rows have no recorded payment method, so a
        tagged-only figure would sit at 0 nearly everywhere."""
        t = tx.get("type")
        payment = tx.get("payment_type")
        amt = tx.get("amount") or 0
        cash_delta = 0.0
        if schema.is_cash_in_type(t):
            cash_delta += amt
        elif schema.is_cash_out_type(t) or (schema.is_expense_type(t) and payment == "Cash"):
            cash_delta -= amt

        balance_delta = 0.0
        if schema.is_income_type(t):
            balance_delta += amt
        elif schema.is_expense_type(t):
            balance_delta -= amt

        return cash_delta, balance_delta - cash_delta

    @classmethod
    def _append_monthly_points(
        cls, schema, txs: list[dict], y: int, m: int, has_cash_tracking: bool, period_start: Date,
        balance_points: list[tuple[str, float, float]], cash_points: list[tuple[str, float, float]],
        card_points: list[tuple[str, float, float]], balance_total: float, cash_total: float, card_total: float,
    ) -> tuple[float, float, float]:
        label = f"{MONTH_NAMES[m - 1][:3]} '{y % 100:02d}"
        x = (Date(y, m, 1) - period_start).days
        summary = schema.month_summary(m)
        balance_total += summary["balance"]
        balance_points.append((label, balance_total, x))

        if has_cash_tracking:
            cash_net = card_net = 0.0
            for tx in txs:
                cash_delta, card_delta = cls._cash_card_delta(schema, tx)
                cash_net += cash_delta
                card_net += card_delta
            cash_total += cash_net
            cash_points.append((label, cash_total, x))
            card_total += card_net
            card_points.append((label, card_total, x))

        return balance_total, cash_total, card_total

    @classmethod
    def _append_daily_points(
        cls, schema, txs: list[dict], y: int, m: int, today: Date, has_cash_tracking: bool, period_start: Date,
        balance_points: list[tuple[str, float, float]], cash_points: list[tuple[str, float, float]],
        card_points: list[tuple[str, float, float]], balance_total: float, cash_total: float, card_total: float,
    ) -> tuple[float, float, float]:
        is_current_month = (y, m) == (today.year, today.month)
        net_by_day: dict[Date, float] = {}
        cash_net_by_day: dict[Date, float] = {}
        card_net_by_day: dict[Date, float] = {}

        for tx in txs:
            raw_date = tx.get("date")
            if raw_date is None:
                continue
            day = raw_date.date() if hasattr(raw_date, "date") else raw_date
            if is_current_month and day > today:
                continue
            amt = tx.get("amount") or 0
            if schema.is_income_type(tx.get("type")):
                net_by_day[day] = net_by_day.get(day, 0.0) + amt
            elif schema.is_expense_type(tx.get("type")):
                net_by_day[day] = net_by_day.get(day, 0.0) - amt
            if has_cash_tracking:
                cash_delta, card_delta = cls._cash_card_delta(schema, tx)
                cash_net_by_day[day] = cash_net_by_day.get(day, 0.0) + cash_delta
                card_net_by_day[day] = card_net_by_day.get(day, 0.0) + card_delta

        days_in_month = calendar.monthrange(y, m)[1]
        last_day = min(today.day, days_in_month) if is_current_month else days_in_month
        for day_num in range(1, last_day + 1):
            day = Date(y, m, day_num)
            label = f"{day_num:02d} {MONTH_NAMES[m - 1][:3]}"
            x = (day - period_start).days
            balance_total += net_by_day.get(day, 0.0)
            balance_points.append((label, balance_total, x))
            if has_cash_tracking:
                cash_total += cash_net_by_day.get(day, 0.0)
                cash_points.append((label, cash_total, x))
                card_total += card_net_by_day.get(day, 0.0)
                card_points.append((label, card_total, x))

        return balance_total, cash_total, card_total

    def _refresh_heatmap(self) -> None:
        heat_year_text = self._year_combo.currentText()
        if not heat_year_text:
            return
        heat_year = int(heat_year_text)
        try:
            heat_schema = registry.get_schema_for_date(Date(heat_year, 1, 1))
        except ValueError:
            self._heatmap.update_data(None, heat_year)
            return

        if not heat_schema.HAS_DAILY_DATES:
            self._heatmap.update_data(None, heat_year)
            return

        daily: dict[tuple[int, int], float] = {}
        try:
            for m in range(1, 13):
                for tx in heat_schema.transactions_for_month(m):
                    date_val = tx.get("date")
                    if date_val is not None and heat_schema.is_expense_type(tx.get("type")):
                        key = (m, date_val.day)
                        daily[key] = daily.get(key, 0.0) + (tx.get("amount") or 0)
        except WorkbookLockedError as exc:
            self._status.setText(str(exc))
            daily = {}

        today = Date.today()
        end_date = today if heat_year == today.year else None
        self._heatmap.update_data(daily, heat_year, end_date)
