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
    QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QScrollArea,
    QVBoxLayout, QWidget,
)

from core.excel import registry
from core.excel.workbook_io import WorkbookLockedError
from core.format import fmt_amount
from core.themes import c

from ..components.charts import CategoryPieChart, RunningBalanceChart
from ..components.widgets import bordered_box

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


def _section_label(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
    lbl.setStyleSheet(f"color:{c('t2')}; background:transparent;")
    return lbl


def _card(title: str) -> tuple[QWidget, QVBoxLayout]:
    box = bordered_box(c("panel_bg"), c("panel_bd"), radius=14)
    lay = QVBoxLayout(box)
    lay.setContentsMargins(20, 16, 20, 16)
    lay.setSpacing(8)
    lay.addWidget(_section_label(title))
    return box, lay


class DashboardPage(QWidget):
    view_all_clicked = pyqtSignal()

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

        self._status = QLabel("")
        self._status.setWordWrap(True)
        self._status.setStyleSheet(f"color:{c('err_c')}; background:transparent;")
        lay.addWidget(self._status)

        tiles_grid = QGridLayout()
        tiles_grid.setSpacing(10)
        self._tile_labels: dict[str, QLabel] = {}
        for i, (key, title, color_key) in enumerate(_TILES):
            box = bordered_box(c("panel_bg"), c("panel_bd"), radius=12)
            box_lay = QVBoxLayout(box)
            box_lay.setContentsMargins(16, 12, 16, 12)
            box_lay.setSpacing(2)
            title_lbl = QLabel(title)
            title_lbl.setFont(QFont("Segoe UI", 9))
            title_lbl.setStyleSheet(f"color:{c('t2')}; background:transparent;")
            value_lbl = QLabel("0.00")
            value_lbl.setFont(QFont("Segoe UI", 16, QFont.Weight.Bold))
            value_lbl.setStyleSheet(f"color:{c(color_key)}; background:transparent;")
            box_lay.addWidget(title_lbl)
            box_lay.addWidget(value_lbl)
            tiles_grid.addWidget(box, i // _TILES_PER_ROW, i % _TILES_PER_ROW)
            self._tile_labels[key] = value_lbl
        lay.addLayout(tiles_grid)

        balance_box, balance_lay = _card("Balance this month")
        self._balance_chart = RunningBalanceChart()
        balance_lay.addWidget(self._balance_chart)
        lay.addWidget(balance_box)

        pies_row = QHBoxLayout()
        pies_row.setSpacing(16)
        expense_box, expense_lay = _card("Expenses by category")
        self._expense_pie = CategoryPieChart()
        expense_lay.addWidget(self._expense_pie)
        pies_row.addWidget(expense_box, 1)

        income_box, income_lay = _card("Income by category")
        self._income_pie = CategoryPieChart()
        income_lay.addWidget(self._income_pie)
        pies_row.addWidget(income_box, 1)
        lay.addLayout(pies_row)

        preview_box = bordered_box(c("panel_bg"), c("panel_bd"), radius=14)
        preview_lay = QVBoxLayout(preview_box)
        preview_lay.setContentsMargins(20, 16, 20, 16)
        preview_lay.setSpacing(6)

        preview_hdr = QHBoxLayout()
        preview_hdr.addWidget(_section_label("Recent transactions"))
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

        self._status.setText("")
        for key, _title, _color in _TILES:
            if key in _SIGNED_TILES:
                continue
            self._tile_labels[key].setText(fmt_amount(summary[key]))
        for key in _SIGNED_TILES:
            self._set_signed_tile(key, summary.get(key))

        expense_breakdown: dict[str, float] = {}
        income_breakdown: dict[str, float] = {}
        for tx in txs:
            cat = tx.get("category") or "Other"
            amt = tx.get("amount") or 0
            if schema.is_expense_type(tx.get("type")):
                expense_breakdown[cat] = expense_breakdown.get(cat, 0.0) + amt
            elif schema.is_income_type(tx.get("type")):
                income_breakdown[cat] = income_breakdown.get(cat, 0.0) + amt
        self._expense_pie.update_data(expense_breakdown)
        self._income_pie.update_data(income_breakdown)

        self._balance_chart.update_data(self._build_running_balance(schema, txs))
        self._render_preview(schema, txs[:_PREVIEW_ROWS])

    def _set_signed_tile(self, key: str, value: float | None) -> None:
        lbl = self._tile_labels[key]
        if value is None:
            lbl.setText("N/A")
            lbl.setStyleSheet(f"color:{c('t3')}; background:transparent;")
        else:
            sign = "+" if value >= 0 else "-"
            lbl.setText(f"{sign}{fmt_amount(abs(value))}")
            lbl.setStyleSheet(f"color:{c('income_c') if value >= 0 else c('expense_c')}; background:transparent;")

    def _build_running_balance(self, schema, txs: list[dict]) -> list[tuple[int, float]] | None:
        if not schema.HAS_DAILY_DATES:
            return None
        daily_delta: dict[int, float] = {}
        for tx in txs:
            d = tx.get("date")
            if d is None:
                continue
            amt = tx.get("amount") or 0
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
            amount_lbl = QLabel(f"{sign}{fmt_amount(tx.get('amount') or 0)}")
            amount_lbl.setStyleSheet(f"color:{amount_color}; background:transparent; font-weight:bold;")
            row_lay.addWidget(amount_lbl)

            self._preview_list_lay.addWidget(row)
            self._preview_rows.append(row)
