"""
app/window.py — App: sidebar + top bar + page stack (Dashboard,
Transactions, Analytics, Categories, Templates, Currencies). Watches the
Finances directory and refreshes the current page ~2s after any external
change settles (debounced), plus immediately after a local add/edit/delete.

Dashboard and Transactions are cheap (one month) and always refresh
together on any period change. Analytics reads every month in its
selected range and Categories doesn't depend on the viewed month at all,
so both refresh lazily — only when they become the active page, or when
the period changes while already active. Currencies is all-time/all-years
by design (independent of the viewed month entirely), same lazy pattern
as Categories.
"""
from __future__ import annotations

from PyQt6.QtCore import QSize, QTimer, Qt
from PyQt6.QtGui import QCursor
from PyQt6.QtWidgets import QHBoxLayout, QPushButton, QStackedWidget, QVBoxLayout, QWidget

from core.icons import icon
from core.themes import c
from core.watcher import FileWatcher

from .components.create_file_dialog import CreateFileDialog
from .components.manage_files_dialog import ManageFilesDialog
from .components.topbar import TopBar
from .components.widgets import nav_chip_style
from .pages.analytics_page import AnalyticsPage
from .pages.categories_page import CategoriesPage
from .pages.currencies_page import CurrenciesPage
from .pages.dashboard_page import DashboardPage
from .pages.templates_page import TemplatesPage
from .pages.transactions_page import TransactionsPage

_ICON_SIZE = QSize(22, 22)

_DEBOUNCE_MS = 2000

PG_DASHBOARD = 0
PG_TRANSACTIONS = 1
PG_ANALYTICS = 2
PG_CATEGORIES = 3
PG_TEMPLATES = 4
PG_CURRENCIES = 5


class App(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("FinanceTracker")
        self.resize(1200, 780)
        self.setMinimumSize(1000, 640)
        self.setStyleSheet(f"background:{c('bg')};")

        self._dashboard_page = DashboardPage()
        self._transactions_page = TransactionsPage()
        self._analytics_page = AnalyticsPage()
        self._categories_page = CategoriesPage()
        self._templates_page = TemplatesPage()
        self._currencies_page = CurrenciesPage()
        self._dashboard_page.view_all_clicked.connect(lambda: self._show_page(PG_TRANSACTIONS))
        self._transactions_page.analytics_clicked.connect(lambda: self._show_page(PG_ANALYTICS))

        self._stack = QStackedWidget()
        self._stack.addWidget(self._dashboard_page)     # PG_DASHBOARD
        self._stack.addWidget(self._transactions_page)  # PG_TRANSACTIONS
        self._stack.addWidget(self._analytics_page)     # PG_ANALYTICS
        self._stack.addWidget(self._categories_page)    # PG_CATEGORIES
        self._stack.addWidget(self._templates_page)     # PG_TEMPLATES
        self._stack.addWidget(self._currencies_page)    # PG_CURRENCIES

        self._topbar = TopBar()
        self._topbar.period_changed.connect(self._on_period_changed)
        self._topbar.transaction_saved.connect(self._refresh_current)

        root_lay = QHBoxLayout(self)
        root_lay.setContentsMargins(0, 0, 0, 0)
        root_lay.setSpacing(0)
        root_lay.addWidget(self._build_sidebar())

        right = QWidget()
        right.setStyleSheet("background:transparent;")
        right_lay = QVBoxLayout(right)
        right_lay.setContentsMargins(20, 16, 20, 16)
        right_lay.setSpacing(14)
        right_lay.addWidget(self._topbar)
        right_lay.addWidget(self._stack, 1)
        root_lay.addWidget(right, 1)

        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(_DEBOUNCE_MS)
        self._debounce.timeout.connect(self._refresh_current)

        self._watcher = FileWatcher(self)
        self._watcher.changed.connect(lambda _path: self._debounce.start())
        self._watcher.start()

        self._refresh_current()

    def _build_sidebar(self) -> QWidget:
        sb = QWidget()
        sb.setObjectName("Sidebar")
        sb.setFixedWidth(64)
        sb.setStyleSheet(f"QWidget#Sidebar {{ background:{c('panel_bg')}; border-right:1px solid {c('panel_bd')}; }}")
        lay = QVBoxLayout(sb)
        lay.setContentsMargins(8, 16, 8, 16)
        lay.setSpacing(6)

        self._nav_btns: list[tuple[QPushButton, int, str]] = []
        for icon_name, tooltip, page_idx in [
            ("dashboard", "Dashboard", PG_DASHBOARD),
            ("transactions", "Transactions", PG_TRANSACTIONS),
            ("analytics", "Analytics", PG_ANALYTICS),
            ("categories", "Categories", PG_CATEGORIES),
            ("templates", "Templates", PG_TEMPLATES),
            ("currencies", "Currencies", PG_CURRENCIES),
        ]:
            btn = QPushButton()
            btn.setFixedSize(48, 44)
            btn.setIconSize(_ICON_SIZE)
            btn.setToolTip(tooltip)
            btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            btn.clicked.connect(lambda _checked, idx=page_idx: self._show_page(idx))
            self._nav_btns.append((btn, page_idx, icon_name))
            lay.addWidget(btn, alignment=Qt.AlignmentFlag.AlignCenter)

        lay.addStretch()

        create_file_btn = QPushButton()
        create_file_btn.setFixedSize(48, 44)
        create_file_btn.setIcon(icon("create-file", c("t2")))
        create_file_btn.setIconSize(_ICON_SIZE)
        create_file_btn.setToolTip("Create a new finances file")
        create_file_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        create_file_btn.setStyleSheet(nav_chip_style(False, ghost=True, radius_key="lg"))
        create_file_btn.clicked.connect(self._on_create_file)
        lay.addWidget(create_file_btn, alignment=Qt.AlignmentFlag.AlignCenter)

        manage_files_btn = QPushButton()
        manage_files_btn.setFixedSize(48, 44)
        manage_files_btn.setIcon(icon("settings", c("t2")))
        manage_files_btn.setIconSize(_ICON_SIZE)
        manage_files_btn.setToolTip("Manage files — see and move where each year's file lives")
        manage_files_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        manage_files_btn.setStyleSheet(nav_chip_style(False, ghost=True, radius_key="lg"))
        manage_files_btn.clicked.connect(self._on_manage_files)
        lay.addWidget(manage_files_btn, alignment=Qt.AlignmentFlag.AlignCenter)

        self._style_nav_buttons()
        return sb

    def _style_nav_buttons(self) -> None:
        current = self._stack.currentIndex() if hasattr(self, "_stack") else PG_DASHBOARD
        for btn, idx, icon_name in self._nav_btns:
            selected = idx == current
            btn.setStyleSheet(nav_chip_style(selected, ghost=True, radius_key="lg"))
            btn.setIcon(icon(icon_name, c("ac") if selected else c("t2")))

    def _show_page(self, index: int) -> None:
        self._stack.setCurrentIndex(index)
        self._style_nav_buttons()
        if index == PG_ANALYTICS:
            self._analytics_page.refresh(self._topbar.year, self._topbar.month)
        elif index == PG_CATEGORIES:
            self._categories_page.refresh(self._topbar.year)
        elif index == PG_CURRENCIES:
            self._currencies_page.refresh()

    def _on_period_changed(self, year: int, month: int) -> None:
        self._dashboard_page.refresh(year, month)
        self._transactions_page.refresh(year, month)
        if self._stack.currentIndex() == PG_ANALYTICS:
            self._analytics_page.refresh(year, month)
        self._topbar.mark_updated()

    def _refresh_current(self) -> None:
        self._on_period_changed(self._topbar.year, self._topbar.month)

    def _on_create_file(self) -> None:
        dlg = CreateFileDialog(parent=self)
        dlg.file_created.connect(self._on_file_created)
        dlg.manage_templates_requested.connect(lambda: self._show_page(PG_TEMPLATES))
        dlg.exec()

    def _on_file_created(self, year: int) -> None:
        self._watcher.rewatch()  # start watching the new file's folder too
        self._analytics_page.refresh_years()
        self._categories_page.refresh_years()
        self._refresh_current()

    def _on_manage_files(self) -> None:
        dlg = ManageFilesDialog(parent=self)
        dlg.files_changed.connect(self._on_files_changed)
        dlg.exec()

    def _on_files_changed(self) -> None:
        self._watcher.rewatch()  # a move can put a file in a not-yet-watched folder
        self._topbar.refresh_active_file_label()
        self._refresh_current()

    def closeEvent(self, e):
        self._watcher.stop()
        super().closeEvent(e)
