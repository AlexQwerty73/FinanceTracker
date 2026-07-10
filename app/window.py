"""
app/window.py — App: two-panel layout (transaction form + dashboard).
Watches the Finances directory and refreshes the dashboard ~2s after any
external change settles (debounced), plus immediately after a local save.
"""
from __future__ import annotations

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QHBoxLayout, QWidget

from app.components.dashboard import DashboardPanel
from app.components.transaction_form import TransactionForm
from core.themes import c
from core.watcher import FileWatcher

_DEBOUNCE_MS = 2000


class App(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("FinanceTracker")
        self.resize(920, 620)
        self.setMinimumSize(760, 480)
        self.setStyleSheet(f"background:{c('bg')};")

        self._form = TransactionForm()
        self._dashboard = DashboardPanel()

        lay = QHBoxLayout(self)
        lay.setContentsMargins(20, 20, 20, 20)
        lay.setSpacing(20)
        lay.addWidget(self._form, 0)
        lay.addWidget(self._dashboard, 1)

        self._form.saved.connect(self._dashboard.refresh)

        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(_DEBOUNCE_MS)
        self._debounce.timeout.connect(self._dashboard.refresh)

        self._watcher = FileWatcher(self)
        self._watcher.changed.connect(lambda _path: self._debounce.start())
        self._watcher.start()

        self._dashboard.refresh()

    def closeEvent(self, e):
        self._watcher.stop()
        super().closeEvent(e)
