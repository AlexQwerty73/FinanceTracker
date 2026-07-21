"""
app/pages/home_page.py — HomePage: the combined Dashboard + Transactions
view, one sidebar entry instead of two. Owns the TopBar (month/year nav +
Add Transaction) — that's the one thing genuinely shared between the two
inner pages, since they always show the same viewed month — plus a small
chip toggle switching which of the two is visible below it.

Dashboard and Transactions themselves are unchanged (still separate
QWidget classes) — this page just hosts both in an internal QStackedWidget
instead of App hosting them as two top-level sidebar pages.
"""
from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QCursor
from PyQt6.QtWidgets import QHBoxLayout, QPushButton, QStackedWidget, QVBoxLayout, QWidget

from ..components.topbar import TopBar
from ..components.widgets import nav_chip_style
from .dashboard_page import DashboardPage
from .transactions_page import TransactionsPage

_TAB_DASHBOARD = 0
_TAB_TRANSACTIONS = 1


class HomePage(QWidget):
    analytics_clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(14)

        self._topbar = TopBar()
        self._topbar.period_changed.connect(lambda *_args: self.refresh_current())
        self._topbar.transaction_saved.connect(self.refresh_current)
        lay.addWidget(self._topbar)

        tabs_row = QHBoxLayout()
        tabs_row.setSpacing(8)
        self._dashboard_tab_btn = QPushButton("Dashboard")
        self._transactions_tab_btn = QPushButton("Transactions")
        for btn in (self._dashboard_tab_btn, self._transactions_tab_btn):
            btn.setFixedHeight(32)
            btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._dashboard_tab_btn.clicked.connect(lambda: self._show_tab(_TAB_DASHBOARD))
        self._transactions_tab_btn.clicked.connect(lambda: self._show_tab(_TAB_TRANSACTIONS))
        tabs_row.addWidget(self._dashboard_tab_btn)
        tabs_row.addWidget(self._transactions_tab_btn)
        tabs_row.addStretch()
        lay.addLayout(tabs_row)

        self._stack = QStackedWidget()
        self._dashboard_page = DashboardPage()
        self._transactions_page = TransactionsPage()
        self._stack.addWidget(self._dashboard_page)     # _TAB_DASHBOARD
        self._stack.addWidget(self._transactions_page)  # _TAB_TRANSACTIONS
        lay.addWidget(self._stack, 1)

        self._dashboard_page.view_all_clicked.connect(lambda: self._show_tab(_TAB_TRANSACTIONS))
        self._transactions_page.analytics_clicked.connect(self.analytics_clicked.emit)

        self._style_tab_buttons()

    def _show_tab(self, index: int) -> None:
        self._stack.setCurrentIndex(index)
        self._style_tab_buttons()

    def _style_tab_buttons(self) -> None:
        current = self._stack.currentIndex()
        self._dashboard_tab_btn.setStyleSheet(nav_chip_style(current == _TAB_DASHBOARD, radius_key="lg"))
        self._transactions_tab_btn.setStyleSheet(nav_chip_style(current == _TAB_TRANSACTIONS, radius_key="lg"))

    def refresh_current(self) -> None:
        """Refresh both inner pages for the currently viewed month — cheap
        (one month each), so no reason to only refresh whichever tab is
        visible."""
        year, month = self._topbar.year, self._topbar.month
        self._dashboard_page.refresh(year, month)
        self._transactions_page.refresh(year, month)
        self._topbar.mark_updated()

    def refresh_active_file_label(self) -> None:
        self._topbar.refresh_active_file_label()
