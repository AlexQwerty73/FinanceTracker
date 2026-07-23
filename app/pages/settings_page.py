"""
app/pages/settings_page.py — SettingsPage: a full sidebar page (not a
popup dialog) hosting three tabs — Files (FilesManagerWidget), Create New
File (CreateFileWidget), and Templates (TemplatesPage, un-parked here —
this is its only home now, no separate sidebar destination). Lives for
the app's whole lifetime like every other page (created once in
window.py), so — unlike the old SettingsDialog, which got a free reset
every time it was reopened — a template saved on the Templates tab is
wired to live-refresh the Create tab's Layout picker instead of only
showing up after a restart.
"""
from __future__ import annotations

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QTabWidget, QVBoxLayout, QWidget

from core.themes import c

from ..components.create_file_dialog import CreateFileWidget
from ..components.manage_files_dialog import FilesManagerWidget
from .templates_page import TemplatesPage


class SettingsPage(QWidget):
    file_created = pyqtSignal(int)
    files_changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(f"""
            QTabWidget::pane {{ border:1px solid {c('panel_bd')}; border-radius:8px; top:-1px; }}
            QTabBar::tab {{ background:transparent; color:{c('t2')}; padding:8px 16px; }}
            QTabBar::tab:selected {{ color:{c('ac')}; font-weight:bold; }}
            QTabBar::tab:hover {{ color:{c('t1')}; }}
        """)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)

        self._tabs = QTabWidget()

        self._files_widget = FilesManagerWidget()
        self._files_widget.files_changed.connect(self.files_changed.emit)
        self._tabs.addTab(self._files_widget, "Files")

        self._create_widget = CreateFileWidget()
        self._create_widget.file_created.connect(self._on_file_created)
        self._create_widget.manage_templates_requested.connect(
            lambda: self._tabs.setCurrentWidget(self._templates_widget)
        )
        self._tabs.addTab(self._create_widget, "Create New File")

        self._templates_widget = TemplatesPage()
        self._templates_widget.template_saved.connect(self._create_widget.refresh_template_combo)
        self._tabs.addTab(self._templates_widget, "Templates")

        lay.addWidget(self._tabs)

    def refresh(self) -> None:
        self._files_widget.refresh_rows()

    def _on_file_created(self, year: int) -> None:
        self.file_created.emit(year)
        self._files_widget.refresh_rows()  # keep the Files tab in sync in case the user switches to it
