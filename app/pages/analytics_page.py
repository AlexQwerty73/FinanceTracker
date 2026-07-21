"""
app/pages/analytics_page.py — AnalyticsPage: multi-month/year views a
single month can't show — cumulative balance and cash-flow trends over a
selectable period (monthly or daily granularity: one axis is the period,
the other is the running balance), and a category breakdown pie for the
selected period. Every trend stops at the current month/day — no
projected "0" future periods on the line. A fully independent page — its
own Period/Granularity controls anchor every query at today's date, no
external "which month am I viewing" input needed. Refreshed lazily (only
when shown) since it reads every month in the selected range rather than
just one.
"""
from __future__ import annotations

import calendar
from datetime import date as Date

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import QGridLayout, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from core.excel import registry
from core.excel.base import MONTH_NAMES
from core.excel.workbook_io import WorkbookLockedError
from core.themes import FIELD_HEIGHT, c, font_size

from ..components.charts import BalanceLineChart, CategoryPieChart, IncomeExpenseLineChart
from ..components.transaction_fields import input_style
from ..components.widgets import NoWheelComboBox, card, scrollable_area

_PERIODS = ["Last 6 months", "Last 12 months", "This year", "All time"]
_GRANULARITIES = ["Monthly", "Daily"]


def _control_label(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setFont(QFont("Segoe UI", font_size("label")))
    lbl.setStyleSheet(f"color:{c('t2')}; background:transparent;")
    return lbl


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

        outer_lay = QVBoxLayout(self)
        outer_lay.setContentsMargins(0, 0, 0, 0)

        content = QWidget()
        content.setStyleSheet("background:transparent;")
        outer_lay.addWidget(scrollable_area(content))

        lay = QVBoxLayout(content)
        lay.setContentsMargins(4, 4, 4, 20)
        lay.setSpacing(16)

        controls = QHBoxLayout()
        controls.addWidget(_control_label("Period"))
        self._period_combo = NoWheelComboBox()
        self._period_combo.addItems(_PERIODS)
        self._period_combo.setCurrentText("Last 12 months")
        self._period_combo.setFixedHeight(FIELD_HEIGHT)
        self._period_combo.setStyleSheet(input_style())
        self._period_combo.currentTextChanged.connect(self._on_controls_changed)
        controls.addWidget(self._period_combo)

        controls.addSpacing(24)
        controls.addWidget(_control_label("Granularity"))
        self._granularity_combo = NoWheelComboBox()
        self._granularity_combo.addItems(_GRANULARITIES)
        self._granularity_combo.setFixedHeight(FIELD_HEIGHT)
        self._granularity_combo.setStyleSheet(input_style())
        self._granularity_combo.currentTextChanged.connect(self._on_controls_changed)
        controls.addWidget(self._granularity_combo)

        controls.addStretch()
        lay.addLayout(controls)

        self._status = QLabel("")
        self._status.setWordWrap(True)
        self._status.setStyleSheet(f"color:{c('err_c')}; background:transparent;")
        lay.addWidget(self._status)

        trend_box, trend_lay = card("Balance over time")
        self._balance_line = BalanceLineChart()
        trend_lay.addWidget(self._balance_line)
        lay.addWidget(trend_box)

        growth_box, growth_lay = card("Balance growth, month over month (%)")
        growth_helper = QLabel(
            "Always monthly, regardless of the Granularity control above — a % change needs two "
            "comparable points, which a single day doesn't have the way a month boundary does."
        )
        growth_helper.setWordWrap(True)
        growth_helper.setFont(QFont("Segoe UI", font_size("micro")))
        growth_helper.setStyleSheet(f"color:{c('t3')}; background:transparent;")
        growth_lay.addWidget(growth_helper)
        self._growth_grid = QGridLayout()
        self._growth_grid.setSpacing(4)
        growth_lay.addLayout(self._growth_grid)
        self._growth_cell_widgets: list[QWidget] = []
        lay.addWidget(growth_box)

        income_expense_box, income_expense_lay = card("Income vs Expense")
        self._income_expense_line = IncomeExpenseLineChart()
        income_expense_lay.addWidget(self._income_expense_line)
        lay.addWidget(income_expense_box)

        cash_box, cash_lay = card("Cash flow")
        self._cash_flow = BalanceLineChart()
        cash_lay.addWidget(self._cash_flow)
        lay.addWidget(cash_box)

        card_box, card_lay = card("Card flow")
        self._card_flow = BalanceLineChart()
        card_lay.addWidget(self._card_flow)
        lay.addWidget(card_box)

        pies_row = QHBoxLayout()
        pies_row.setSpacing(16)
        expense_pie_box, expense_pie_lay = card("Expenses by category (selected period)")
        self._pie = CategoryPieChart()
        expense_pie_lay.addWidget(self._pie)
        pies_row.addWidget(expense_pie_box, 1)

        income_pie_box, income_pie_lay = card("Income by category (selected period)")
        self._income_pie = CategoryPieChart()
        income_pie_lay.addWidget(self._income_pie)
        pies_row.addWidget(income_pie_box, 1)
        lay.addLayout(pies_row)

    def _on_controls_changed(self, _text: str = "") -> None:
        self.refresh()

    def refresh(self) -> None:
        selection = self._period_combo.currentText()
        daily = self._granularity_combo.currentText() == "Daily"
        today = Date.today()
        periods = _periods_for_selection(selection, today.year, today.month)
        period_start = Date(periods[0][0], periods[0][1], 1) if periods else today

        # One {series_name: [(label, running_total, x), ...]} dict instead
        # of a parallel list/variable per series — adding Income/Expense as
        # two more tracked series (on top of balance/cash/card) means one
        # more dict key each, not two more parameters threaded through both
        # _append_*_points() methods.
        points: dict[str, list[tuple[str, float, float]]] = {k: [] for k in ("balance", "cash", "card", "income", "expense")}
        totals: dict[str, float] = dict.fromkeys(("balance", "cash", "card"), 0.0)
        expense_breakdown: dict[str, float] = {}
        income_breakdown: dict[str, float] = {}

        try:
            for y, m in periods:
                schema = registry.get_schema_for_date(Date(y, m, 1))
                has_cash_tracking = schema.has_cash_tracking()
                txs = schema.transactions_for_month(m)

                for tx in txs:
                    cat = tx.get("category") or "Other"
                    amt = schema.convert_transaction(tx)
                    if schema.is_expense_type(tx.get("type")):
                        expense_breakdown[cat] = expense_breakdown.get(cat, 0.0) + amt
                    elif schema.is_income_type(tx.get("type")):
                        income_breakdown[cat] = income_breakdown.get(cat, 0.0) + amt

                if daily and schema.HAS_DAILY_DATES:
                    self._append_daily_points(schema, txs, y, m, today, has_cash_tracking, period_start, points, totals)
                else:
                    self._append_monthly_points(schema, txs, y, m, has_cash_tracking, period_start, points, totals)

            growth_points = self._compute_growth_points(periods)
        except (ValueError, WorkbookLockedError) as exc:
            self._status.setText(str(exc))
            return

        self._status.setText("")
        # Balance always has full coverage (every period contributes,
        # tracked or not) — use its span as the shared x-axis for every
        # chart so they stay visually aligned even where cash/card-flow
        # data is sparser (e.g. a stretch with no tagged transactions at all).
        x_values = [p[2] for p in points["balance"]]
        shared_range = (min(x_values), max(x_values)) if x_values else None
        if shared_range is not None:
            pad = (shared_range[1] - shared_range[0]) * 0.02 or 1
            shared_range = (shared_range[0] - pad, shared_range[1] + pad)
        self._balance_line.update_data(points["balance"], shared_range)
        self._rebuild_growth_grid(growth_points)
        income_expense_points = [
            (label, income, expense, x)
            for (label, income, x), (_, expense, _x) in zip(points["income"], points["expense"])
        ]
        self._income_expense_line.update_data(income_expense_points, shared_range)
        self._cash_flow.update_data(points["cash"], shared_range)
        self._card_flow.update_data(points["card"], shared_range)
        self._pie.update_data(expense_breakdown)
        self._income_pie.update_data(income_breakdown)

    def _compute_growth_points(self, periods: list[tuple[int, int]]) -> list[tuple[int, int, float]]:
        """% change in cumulative Balance from the previous month to this
        one — always month-level, independent of the Granularity toggle (a
        % change needs two comparable points, which a single day doesn't
        have) — so this is its own pass rather than reusing points["balance"],
        which is either already exactly this (Monthly mode) or one point
        per day (Daily mode). Returns (year, month, pct) rather than a
        pre-formatted label so the grid can group by year itself."""
        growth_points: list[tuple[int, int, float]] = []
        prev_month_balance = None
        month_running = 0.0
        for y, m in periods:
            schema = registry.get_schema_for_date(Date(y, m, 1))
            month_running += schema.month_summary(m)["balance"]
            if prev_month_balance:  # None or 0 -- either way, no defined % change to show
                pct = (month_running - prev_month_balance) / abs(prev_month_balance) * 100
                growth_points.append((y, m, pct))
            prev_month_balance = month_running
        return growth_points

    def _rebuild_growth_grid(self, points: list[tuple[int, int, float]]) -> None:
        """One row per year (a year label in column 0, then each month's
        "Mon +X.X%" cell in the column matching its month number) instead
        of repeating the year in every single cell — years already line up
        as sections, no per-cell "'25"/"'26" suffix needed."""
        for w in self._growth_cell_widgets:
            self._growth_grid.removeWidget(w)
            w.deleteLater()
        self._growth_cell_widgets = []

        if not points:
            empty_lbl = QLabel("Not enough months to compare yet.")
            empty_lbl.setStyleSheet(f"color:{c('t3')}; background:transparent;")
            self._growth_grid.addWidget(empty_lbl, 0, 0)
            self._growth_cell_widgets.append(empty_lbl)
            return

        years = sorted({y for y, _, _ in points})
        by_year: dict[int, dict[int, float]] = {y: {} for y in years}
        for y, m, pct in points:
            by_year[y][m] = pct

        for row, y in enumerate(years):
            year_lbl = QLabel(str(y))
            year_lbl.setFont(QFont("Segoe UI", font_size("label"), QFont.Weight.Bold))
            year_lbl.setStyleSheet(f"color:{c('t1')}; background:transparent;")
            self._growth_grid.addWidget(year_lbl, row, 0)
            self._growth_cell_widgets.append(year_lbl)

            for m, pct in by_year[y].items():
                cell = QWidget()
                cell.setStyleSheet("background:transparent;")
                cell_lay = QHBoxLayout(cell)
                cell_lay.setContentsMargins(0, 0, 0, 0)
                cell_lay.setSpacing(4)
                month_lbl = QLabel(MONTH_NAMES[m - 1][:3])
                month_lbl.setStyleSheet(f"color:{c('t3')}; background:transparent;")
                cell_lay.addWidget(month_lbl)
                pct_lbl = QLabel(f"{pct:+.1f}%")
                pct_lbl.setFont(QFont("Segoe UI", font_size("label"), QFont.Weight.Bold))
                pct_lbl.setStyleSheet(f"color:{c('income_c') if pct >= 0 else c('expense_c')}; background:transparent;")
                cell_lay.addWidget(pct_lbl)
                self._growth_grid.addWidget(cell, row, m)
                self._growth_cell_widgets.append(cell)

    @staticmethod
    def _cash_card_delta(schema, tx: dict) -> tuple[float, float]:
        """(cash_delta, card_delta) for one transaction — same detection as
        Schema.month_summary()'s "cash"/"card" figures. card_delta is
        *derived* (balance_delta - cash_delta), not tagged from the row's
        own Payment field — most rows have no recorded payment method, so a
        tagged-only figure would sit at 0 nearly everywhere."""
        t = tx.get("type")
        payment = tx.get("payment_type")
        amt = schema.convert_transaction(tx)
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
        points: dict[str, list[tuple[str, float, float]]], totals: dict[str, float],
    ) -> None:
        label = f"{MONTH_NAMES[m - 1][:3]} '{y % 100:02d}"
        x = (Date(y, m, 1) - period_start).days
        summary = schema.month_summary(m)
        totals["balance"] += summary["balance"]
        points["balance"].append((label, totals["balance"], x))
        # Income/Expense are per-month figures on their own chart, not a
        # running total (unlike Balance/Cash/Card, which are cumulative) —
        # the point is "how much in this specific month", not "how much
        # ever".
        points["income"].append((label, summary["income"], x))
        points["expense"].append((label, summary["expense"], x))

        if has_cash_tracking:
            cash_net = card_net = 0.0
            for tx in txs:
                cash_delta, card_delta = cls._cash_card_delta(schema, tx)
                cash_net += cash_delta
                card_net += card_delta
            totals["cash"] += cash_net
            points["cash"].append((label, totals["cash"], x))
            totals["card"] += card_net
            points["card"].append((label, totals["card"], x))

    @classmethod
    def _append_daily_points(
        cls, schema, txs: list[dict], y: int, m: int, today: Date, has_cash_tracking: bool, period_start: Date,
        points: dict[str, list[tuple[str, float, float]]], totals: dict[str, float],
    ) -> None:
        is_current_month = (y, m) == (today.year, today.month)
        net_by_day: dict[Date, float] = {}
        income_by_day: dict[Date, float] = {}
        expense_by_day: dict[Date, float] = {}
        cash_net_by_day: dict[Date, float] = {}
        card_net_by_day: dict[Date, float] = {}

        for tx in txs:
            raw_date = tx.get("date")
            if raw_date is None:
                continue
            day = raw_date.date() if hasattr(raw_date, "date") else raw_date
            if is_current_month and day > today:
                continue
            amt = schema.convert_transaction(tx)
            if schema.is_income_type(tx.get("type")):
                net_by_day[day] = net_by_day.get(day, 0.0) + amt
                income_by_day[day] = income_by_day.get(day, 0.0) + amt
            elif schema.is_expense_type(tx.get("type")):
                net_by_day[day] = net_by_day.get(day, 0.0) - amt
                expense_by_day[day] = expense_by_day.get(day, 0.0) + amt
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
            totals["balance"] += net_by_day.get(day, 0.0)
            points["balance"].append((label, totals["balance"], x))
            points["income"].append((label, income_by_day.get(day, 0.0), x))
            points["expense"].append((label, expense_by_day.get(day, 0.0), x))
            if has_cash_tracking:
                totals["cash"] += cash_net_by_day.get(day, 0.0)
                points["cash"].append((label, totals["cash"], x))
                totals["card"] += card_net_by_day.get(day, 0.0)
                points["card"].append((label, totals["card"], x))
