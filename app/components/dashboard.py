"""
app/components/dashboard.py — DashboardPanel: totals, charts, and the
transaction list for a browsable month (defaults to today's month/year).
refresh() re-reads the workbook from disk; called after a local save/edit/
delete and whenever the file watcher detects an external change.
"""
from __future__ import annotations

from datetime import date as Date

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QCursor, QFont
from PyQt6.QtWidgets import (
    QFrame, QGridLayout, QHBoxLayout, QLabel, QMessageBox, QPushButton,
    QScrollArea, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from core.excel import registry
from core.excel.base import MONTH_NAMES, TransactionNotFoundError
from core.excel.workbook_io import WorkbookLockedError
from core.themes import c

from .charts import CategoryBreakdownChart, TrendChart
from .transaction_dialog import TransactionDialog

_TILES = [
    ("income", "Income", "income_c"),
    ("expense", "Expense", "expense_c"),
    ("invest", "Invest", "invest_c"),
    ("balance", "Balance", "t1"),
]

_TREND_MONTHS = 6


def _fmt_amount(v: float) -> str:
    return f"{v:,.2f}"


def _nav_btn(text: str) -> QPushButton:
    btn = QPushButton(text)
    btn.setFixedSize(30, 28)
    btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
    btn.setStyleSheet(f"""
        QPushButton {{ background:{c('in_bg')}; color:{c('t1')};
            border:1px solid {c('in_bd')}; border-radius:6px; }}
        QPushButton:hover {{ border-color:{c('ac')}; color:{c('ac')}; }}
        QPushButton:disabled {{ color:{c('t3')}; }}
    """)
    return btn


def _section_label(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
    lbl.setStyleSheet(f"color:{c('t2')}; background:transparent;")
    return lbl


def _trailing_periods(year: int, month: int, count: int) -> list[tuple[int, int]]:
    """Up to `count` (year, month) pairs ending at (year, month), oldest
    first, clamped to the earliest period any registered schema covers."""
    floor_year, floor_month = registry.min_supported_period()
    periods: list[tuple[int, int]] = []
    y, m = year, month
    while len(periods) < count:
        periods.append((y, m))
        if (y, m) <= (floor_year, floor_month):
            break
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    periods.reverse()
    return periods


class DashboardPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(f"background:{c('panel_bg')}; border:1px solid {c('panel_bd')}; border-radius:14px;")

        today = Date.today()
        self._viewed_year = today.year
        self._viewed_month = today.month
        self._current_txs: list[dict] = []
        self._current_schema = None

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
        lay.setContentsMargins(20, 20, 20, 20)
        lay.setSpacing(12)

        top_row = QHBoxLayout()
        self._prev_btn = _nav_btn("<")
        self._prev_btn.clicked.connect(self._go_prev)
        top_row.addWidget(self._prev_btn)

        self._title = QLabel("")
        self._title.setFont(QFont("Segoe UI", 14, QFont.Weight.Bold))
        self._title.setStyleSheet(f"color:{c('t1')}; background:transparent;")
        self._title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        top_row.addWidget(self._title, 1)

        self._next_btn = _nav_btn(">")
        self._next_btn.clicked.connect(self._go_next)
        top_row.addWidget(self._next_btn)

        today_btn = QPushButton("Today")
        today_btn.setFixedHeight(28)
        today_btn.setStyleSheet(f"""
            QPushButton {{ background:transparent; color:{c('t2')};
                border:1px solid {c('in_bd')}; border-radius:6px; padding:0 10px; }}
            QPushButton:hover {{ color:{c('ac')}; border-color:{c('ac')}; }}
        """)
        today_btn.clicked.connect(self._go_today)
        top_row.addWidget(today_btn)

        refresh_btn = QPushButton("Refresh")
        refresh_btn.setFixedHeight(28)
        refresh_btn.setStyleSheet(f"""
            QPushButton {{ background:transparent; color:{c('t2')};
                border:1px solid {c('in_bd')}; border-radius:6px; padding:0 10px; }}
            QPushButton:hover {{ color:{c('ac')}; border-color:{c('ac')}; }}
        """)
        refresh_btn.clicked.connect(self.refresh)
        top_row.addWidget(refresh_btn)
        lay.addLayout(top_row)

        self._status = QLabel("")
        self._status.setWordWrap(True)
        self._status.setStyleSheet(f"color:{c('err_c')}; background:transparent;")
        lay.addWidget(self._status)

        tiles_grid = QGridLayout()
        tiles_grid.setSpacing(10)
        self._tile_labels: dict[str, QLabel] = {}
        for i, (key, title, color_key) in enumerate(_TILES):
            box = QWidget()
            box.setStyleSheet(f"background:{c('in_bg')}; border:1px solid {c('in_bd')}; border-radius:10px;")
            box_lay = QVBoxLayout(box)
            box_lay.setContentsMargins(14, 10, 14, 10)
            box_lay.setSpacing(2)
            title_lbl = QLabel(title)
            title_lbl.setFont(QFont("Segoe UI", 9))
            title_lbl.setStyleSheet(f"color:{c('t2')}; background:transparent;")
            value_lbl = QLabel("0.00")
            value_lbl.setFont(QFont("Segoe UI", 15, QFont.Weight.Bold))
            value_lbl.setStyleSheet(f"color:{c(color_key)}; background:transparent;")
            box_lay.addWidget(title_lbl)
            box_lay.addWidget(value_lbl)
            tiles_grid.addWidget(box, i // 2, i % 2)
            self._tile_labels[key] = value_lbl
        lay.addLayout(tiles_grid)

        lay.addWidget(_section_label("Expenses by category"))
        self._category_chart = CategoryBreakdownChart()
        lay.addWidget(self._category_chart)

        lay.addWidget(_section_label(f"Income vs expense (last {_TREND_MONTHS} months)"))
        self._trend_chart = TrendChart()
        lay.addWidget(self._trend_chart)

        lay.addWidget(_section_label("Transactions"))
        self._table = QTableWidget(0, 4)
        self._table.setHorizontalHeaderLabels(["Date", "Type", "Category", "Amount"])
        self._table.verticalHeader().setVisible(False)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.setMinimumHeight(220)
        self._table.setStyleSheet(f"""
            QTableWidget {{ background:transparent; color:{c('t1')}; border:none; gridline-color:{c('sep')}; }}
            QHeaderView::section {{ background:transparent; color:{c('t2')}; border:none; border-bottom:1px solid {c('sep')}; padding:4px; }}
            QTableWidget::item:selected {{ background:{c('btn_bg')}; }}
        """)
        lay.addWidget(self._table)

        row_actions = QHBoxLayout()
        row_actions.addStretch()
        self._edit_btn = QPushButton("Edit")
        self._edit_btn.setFixedHeight(30)
        self._edit_btn.setStyleSheet(f"""
            QPushButton {{ background:transparent; color:{c('t2')};
                border:1px solid {c('in_bd')}; border-radius:6px; padding:0 14px; }}
            QPushButton:hover {{ color:{c('ac')}; border-color:{c('ac')}; }}
        """)
        self._edit_btn.clicked.connect(self._on_edit)
        self._delete_btn = QPushButton("Delete")
        self._delete_btn.setFixedHeight(30)
        self._delete_btn.setStyleSheet(f"""
            QPushButton {{ background:transparent; color:{c('t2')};
                border:1px solid {c('in_bd')}; border-radius:6px; padding:0 14px; }}
            QPushButton:hover {{ color:{c('err_c')}; border-color:{c('err_c')}; }}
        """)
        self._delete_btn.clicked.connect(self._on_delete)
        row_actions.addWidget(self._edit_btn)
        row_actions.addWidget(self._delete_btn)
        lay.addLayout(row_actions)

    # ── month navigation ────────────────────────────────────────────────

    def _go_prev(self) -> None:
        y, m = self._viewed_year, self._viewed_month - 1
        if m == 0:
            y, m = y - 1, 12
        if (y, m) < registry.min_supported_period():
            return
        self._viewed_year, self._viewed_month = y, m
        self.refresh()

    def _go_next(self) -> None:
        y, m = self._viewed_year, self._viewed_month + 1
        if m == 13:
            y, m = y + 1, 1
        if (y, m) > registry.max_supported_period():
            return
        self._viewed_year, self._viewed_month = y, m
        self.refresh()

    def _go_today(self) -> None:
        today = Date.today()
        self._viewed_year, self._viewed_month = today.year, today.month
        self.refresh()

    # ── edit / delete ───────────────────────────────────────────────────

    def _selected_tx(self) -> dict | None:
        row = self._table.currentRow()
        if row < 0 or row >= len(self._current_txs):
            return None
        return self._current_txs[row]

    def _on_edit(self) -> None:
        tx = self._selected_tx()
        if tx is None or self._current_schema is None:
            return
        dlg = TransactionDialog(self._current_schema, tx, self)
        if dlg.exec():
            self.refresh()

    def _on_delete(self) -> None:
        tx = self._selected_tx()
        if tx is None or self._current_schema is None:
            return
        label = tx.get("date").strftime("%Y-%m-%d") if tx.get("date") else tx.get("month", "")
        reply = QMessageBox.question(
            self, "Delete transaction",
            f"Delete this transaction?\n\n{label} — {tx.get('type')} / {tx.get('category')} — {_fmt_amount(tx.get('amount') or 0)}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        try:
            self._current_schema.delete_transaction(tx)
        except (TransactionNotFoundError, WorkbookLockedError) as exc:
            self._status.setText(str(exc))
            return
        self.refresh()

    # ── refresh ─────────────────────────────────────────────────────────

    def refresh(self) -> None:
        try:
            schema = registry.get_schema_for_date(Date(self._viewed_year, self._viewed_month, 1))
        except ValueError as exc:
            self._status.setText(str(exc))
            return

        self._current_schema = schema
        self._title.setText(f"{MONTH_NAMES[self._viewed_month - 1]} {self._viewed_year}")
        self._prev_btn.setEnabled((self._viewed_year, self._viewed_month) > registry.min_supported_period())
        self._next_btn.setEnabled((self._viewed_year, self._viewed_month) < registry.max_supported_period())

        try:
            summary = schema.month_summary(self._viewed_month)
            txs = schema.transactions_for_month(self._viewed_month)
        except WorkbookLockedError as exc:
            self._status.setText(str(exc))
            return

        self._status.setText("")
        self._current_txs = txs
        for key, _title, _color in _TILES:
            self._tile_labels[key].setText(_fmt_amount(summary[key]))

        breakdown: dict[str, float] = {}
        for tx in txs:
            if schema.is_expense_type(tx.get("type")):
                cat = tx.get("category") or "Other"
                breakdown[cat] = breakdown.get(cat, 0.0) + (tx.get("amount") or 0)
        self._category_chart.update_data(breakdown)

        try:
            trend_points = self._build_trend_points()
        except WorkbookLockedError as exc:
            self._status.setText(str(exc))
            trend_points = []
        self._trend_chart.update_data(trend_points)

        self._table.setRowCount(len(txs))
        for row, tx in enumerate(txs):
            date_val = tx.get("date")
            date_str = date_val.strftime("%Y-%m-%d") if date_val else tx.get("month", "")
            values = [date_str, tx.get("type") or "", tx.get("category") or "", _fmt_amount(tx.get("amount") or 0)]
            for col, value in enumerate(values):
                item = QTableWidgetItem(value)
                if col == 3:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self._table.setItem(row, col, item)

    def _build_trend_points(self) -> list[tuple[str, float, float]]:
        points = []
        for y, m in _trailing_periods(self._viewed_year, self._viewed_month, _TREND_MONTHS):
            schema = registry.get_schema_for_date(Date(y, m, 1))
            summary = schema.month_summary(m)
            label = f"{MONTH_NAMES[m - 1][:3]} '{y % 100:02d}"
            points.append((label, summary["income"], summary["expense"]))
        return points
