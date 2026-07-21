"""
app/window.py — App: sidebar + page stack (Home, Analytics, Categories,
Templates, Currencies, Review). Watches the Finances directory and
refreshes the active page ~2s after any external change settles
(debounced).

Home (app/pages/home_page.py) combines what used to be two separate
top-level pages (Dashboard + Transactions) plus the month/year TopBar —
that trio always shares the same viewed month, so they're one page now,
not three things window.py has to keep in sync. Analytics, Categories,
Currencies, and Review are all independent of "the viewed month" entirely
(Categories/Currencies have their own year-scoping, Analytics always
anchors at today) — each refreshes lazily, only when it becomes the
active page. Templates is parked behind a WipPlaceholder pending a
redesign (see CLAUDE.md's Recent changes) — the real `TemplatesPage`
implementation is untouched, just not wired up right now.
"""
from __future__ import annotations

from datetime import date as Date

from PyQt6.QtCore import QSize, QTimer, Qt
from PyQt6.QtGui import QCursor
from PyQt6.QtWidgets import QHBoxLayout, QPushButton, QStackedWidget, QVBoxLayout, QWidget

from core.excel import registry
from core.icons import icon
from core.themes import c
from core.watcher import FileWatcher

from .components.rate_sync_worker import RateSyncWorker
from .components.settings_dialog import SettingsDialog
from .components.widgets import nav_chip_style
from .components.wip_placeholder import WipPlaceholder
from .pages.analytics_page import AnalyticsPage
from .pages.categories_page import CategoriesPage
from .pages.currencies_page import CurrenciesPage
from .pages.home_page import HomePage
from .pages.review_page import ReviewPage

_ICON_SIZE = QSize(22, 22)

_DEBOUNCE_MS = 2000

PG_HOME = 0
PG_ANALYTICS = 1
PG_CATEGORIES = 2
PG_TEMPLATES = 3
PG_CURRENCIES = 4
PG_REVIEW = 5


class App(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("FinanceTracker")
        self.resize(1200, 780)
        self.setMinimumSize(1000, 640)
        self.setStyleSheet(f"background:{c('bg')};")

        self._home_page = HomePage()
        self._analytics_page = AnalyticsPage()
        self._categories_page = CategoriesPage()
        self._templates_page = WipPlaceholder("Templates")  # real TemplatesPage parked pending a redesign
        self._currencies_page = CurrenciesPage()
        self._review_page = ReviewPage()
        self._home_page.analytics_clicked.connect(lambda: self._show_page(PG_ANALYTICS))

        self._stack = QStackedWidget()
        self._stack.addWidget(self._home_page)        # PG_HOME
        self._stack.addWidget(self._analytics_page)    # PG_ANALYTICS
        self._stack.addWidget(self._categories_page)   # PG_CATEGORIES
        self._stack.addWidget(self._templates_page)    # PG_TEMPLATES
        self._stack.addWidget(self._currencies_page)   # PG_CURRENCIES
        self._stack.addWidget(self._review_page)        # PG_REVIEW

        root_lay = QHBoxLayout(self)
        root_lay.setContentsMargins(0, 0, 0, 0)
        root_lay.setSpacing(0)
        root_lay.addWidget(self._build_sidebar())

        right = QWidget()
        right.setStyleSheet("background:transparent;")
        right_lay = QVBoxLayout(right)
        right_lay.setContentsMargins(20, 16, 20, 16)
        right_lay.addWidget(self._stack, 1)
        root_lay.addWidget(right, 1)

        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(_DEBOUNCE_MS)
        self._debounce.timeout.connect(self._refresh_active_page)

        self._watcher = FileWatcher(self)
        self._watcher.changed.connect(lambda _path: self._debounce.start())
        self._watcher.start()

        self._refresh_active_page()
        self._catch_up_all_transactions()

        self._rate_sync = RateSyncWorker(self)
        self._rate_sync.sync_finished.connect(self._refresh_active_page)
        self._rate_sync.start()

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
            ("dashboard", "Dashboard", PG_HOME),
            ("analytics", "Analytics", PG_ANALYTICS),
            ("categories", "Categories", PG_CATEGORIES),
            ("templates", "Templates (in development)", PG_TEMPLATES),
            ("currencies", "Currencies", PG_CURRENCIES),
            ("review", "Review — duplicates & outliers", PG_REVIEW),
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

        settings_btn = QPushButton()
        settings_btn.setFixedSize(48, 44)
        settings_btn.setIcon(icon("settings", c("t2")))
        settings_btn.setIconSize(_ICON_SIZE)
        settings_btn.setToolTip("Settings — files, create a new finances file")
        settings_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        settings_btn.setStyleSheet(nav_chip_style(False, ghost=True, radius_key="lg"))
        settings_btn.clicked.connect(self._on_settings)
        lay.addWidget(settings_btn, alignment=Qt.AlignmentFlag.AlignCenter)

        self._style_nav_buttons()
        return sb

    def _style_nav_buttons(self) -> None:
        current = self._stack.currentIndex() if hasattr(self, "_stack") else PG_HOME
        for btn, idx, icon_name in self._nav_btns:
            selected = idx == current
            btn.setStyleSheet(nav_chip_style(selected, ghost=True, radius_key="lg"))
            btn.setIcon(icon(icon_name, c("ac") if selected else c("t2")))

    def _show_page(self, index: int) -> None:
        self._stack.setCurrentIndex(index)
        self._style_nav_buttons()
        self._refresh_active_page()

    def _catch_up_all_transactions(self) -> None:
        """Rebuild the All Transactions sheet once per launch for every
        DynamicSchema year — Monthly/Annual Summary and By Category are
        live Excel formulas now (self-updating regardless of edit source),
        but All Transactions is still a Python-maintained mirror (see
        core/excel/derived_sheets.py), so it can otherwise lag behind
        transactions entered directly in Excel (e.g. from a phone) until
        the app happens to write something of its own. One year's schema
        failing (a legacy/broken file) must not block the rest."""
        for year in registry.supported_years():
            try:
                schema = registry.get_schema_for_date(Date(year, 1, 1))
                schema._refresh_derived_sheets()
            except (ValueError, AttributeError):
                continue

    def _refresh_active_page(self) -> None:
        idx = self._stack.currentIndex()
        if idx == PG_HOME:
            self._home_page.refresh_current()
        elif idx == PG_ANALYTICS:
            self._analytics_page.refresh()
        elif idx == PG_CATEGORIES:
            self._categories_page.refresh()
        elif idx == PG_CURRENCIES:
            self._currencies_page.refresh()
        elif idx == PG_REVIEW:
            self._review_page.refresh()
        # PG_TEMPLATES is a WIP placeholder — nothing to refresh.

    def _on_settings(self) -> None:
        dlg = SettingsDialog(parent=self)
        dlg.file_created.connect(self._on_file_created)
        dlg.manage_templates_requested.connect(lambda: self._show_page(PG_TEMPLATES))
        dlg.files_changed.connect(self._on_files_changed)
        dlg.exec()

    def _on_file_created(self, year: int) -> None:
        self._watcher.rewatch()  # start watching the new file's folder too
        self._categories_page.refresh_years()
        self._refresh_active_page()

    def _on_files_changed(self) -> None:
        self._watcher.rewatch()  # a move can put a file in a not-yet-watched folder
        self._home_page.refresh_active_file_label()
        self._refresh_active_page()

    def closeEvent(self, e):
        self._watcher.stop()
        if self._rate_sync.isRunning():
            self._rate_sync.wait(3000)
        super().closeEvent(e)
