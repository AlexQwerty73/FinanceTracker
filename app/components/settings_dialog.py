"""
app/components/settings_dialog.py — SettingsDialog: one consolidated
window for the two things that used to be separate sidebar buttons/dialogs
— the file manager (FilesManagerWidget) and creating a new file
(CreateFileWidget) — as tabs, plus room for "and similar things" later.
"""
from __future__ import annotations

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QDialog, QTabWidget, QVBoxLayout

from core.themes import c

from .create_file_dialog import CreateFileWidget
from .manage_files_dialog import FilesManagerWidget
from .widgets import primary_button


class SettingsDialog(QDialog):
    file_created = pyqtSignal(int)
    manage_templates_requested = pyqtSignal()
    files_changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setFixedWidth(560)
        self.setStyleSheet(f"""
            QDialog {{ background:{c('bg')}; }}
            QTabWidget::pane {{ border:1px solid {c('panel_bd')}; border-radius:8px; top:-1px; }}
            QTabBar::tab {{ background:transparent; color:{c('t2')}; padding:8px 16px; }}
            QTabBar::tab:selected {{ color:{c('ac')}; font-weight:bold; }}
            QTabBar::tab:hover {{ color:{c('t1')}; }}
        """)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        tabs = QTabWidget()
        self._files_widget = FilesManagerWidget()
        self._files_widget.files_changed.connect(self.files_changed.emit)
        tabs.addTab(self._files_widget, "Files")

        self._create_widget = CreateFileWidget()
        self._create_widget.file_created.connect(self._on_file_created)
        self._create_widget.manage_templates_requested.connect(self._on_manage_templates_requested)
        tabs.addTab(self._create_widget, "Create New File")

        lay.addWidget(tabs)

        close_btn = primary_button("Close")
        close_btn.clicked.connect(self.accept)
        wrapper_lay = QVBoxLayout()
        wrapper_lay.setContentsMargins(16, 12, 16, 16)
        wrapper_lay.addWidget(close_btn)
        lay.addLayout(wrapper_lay)

    def _on_file_created(self, year: int) -> None:
        self.file_created.emit(year)
        self._files_widget.refresh_rows()  # keep the Files tab in sync in case the user switches to it

    def _on_manage_templates_requested(self) -> None:
        self.manage_templates_requested.emit()
        self.accept()  # close Settings — window.py switches to the Templates page in response
