"""
app/components/manage_files_dialog.py — ManageFilesDialog: see where every
registered year's file currently lives, and move one to a different folder
without touching Explorer — core.file_ops.move_year_file() handles the
physical move and keeps settings.json/config.FILE_PATHS in sync. Also lets
you change the default folder new files get suggested into
(create_file_dialog.py).
"""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QCursor, QFont
from PyQt6.QtWidgets import QDialog, QFileDialog, QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout, QWidget

from core import config, file_ops, settings
from core.excel import registry
from core.themes import c

from .transaction_fields import field_label, input_style


def _ghost_btn(text: str) -> QPushButton:
    btn = QPushButton(text)
    btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
    btn.setStyleSheet(f"""
        QPushButton {{ background:transparent; color:{c('t2')};
            border:1px solid {c('in_bd')}; border-radius:8px; padding:0 12px; }}
        QPushButton:hover {{ color:{c('t1')}; border-color:{c('t2')}; }}
        QPushButton:disabled {{ color:{c('t3')}; border-color:{c('in_bd')}; }}
    """)
    return btn


class ManageFilesDialog(QDialog):
    files_changed = pyqtSignal()  # emitted after any successful move / default-folder change

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Manage Files")
        self.setFixedWidth(540)
        self.setStyleSheet(f"QDialog {{ background:{c('bg')}; }}")

        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 20, 20, 20)
        lay.setSpacing(10)

        hdr = QLabel("Manage Files")
        hdr.setFont(QFont("Segoe UI", 13, QFont.Weight.Bold))
        hdr.setStyleSheet(f"color:{c('t1')}; background:transparent;")
        lay.addWidget(hdr)

        desc = QLabel("See where each year's file lives, and move one to a different folder without doing it in Explorer.")
        desc.setWordWrap(True)
        desc.setStyleSheet(f"color:{c('t2')}; background:transparent;")
        lay.addWidget(desc)

        lay.addWidget(field_label("Default folder for new files"))
        folder_row = QHBoxLayout()
        self._default_folder_field = QLineEdit(str(config.FINANCES_DIR))
        self._default_folder_field.setReadOnly(True)
        self._default_folder_field.setFixedHeight(34)
        self._default_folder_field.setStyleSheet(input_style())
        change_folder_btn = _ghost_btn("Change…")
        change_folder_btn.setFixedHeight(34)
        change_folder_btn.clicked.connect(self._on_change_default_folder)
        folder_row.addWidget(self._default_folder_field, 1)
        folder_row.addWidget(change_folder_btn)
        lay.addLayout(folder_row)

        lay.addWidget(field_label("Files"))
        self._rows_lay = QVBoxLayout()
        self._rows_lay.setSpacing(8)
        lay.addLayout(self._rows_lay)
        self._row_widgets: list[QWidget] = []

        self._status = QLabel("")
        self._status.setWordWrap(True)
        self._status.setFont(QFont("Segoe UI", 9))
        lay.addWidget(self._status)

        close_btn = QPushButton("Close")
        close_btn.setFixedHeight(32)
        close_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        close_btn.setStyleSheet(f"""
            QPushButton {{ background:{c('btn_bg')}; color:{c('ac')};
                border:1px solid {c('btn_bd')}; border-radius:8px; font-weight:bold; }}
            QPushButton:hover {{ background:{c('btn_hbg')}; }}
        """)
        close_btn.clicked.connect(self.accept)
        lay.addWidget(close_btn)

        self._refresh_rows()

    def _set_status(self, text: str, error: bool = True) -> None:
        self._status.setStyleSheet(f"color:{c('err_c') if error else c('income_c')}; background:transparent;")
        self._status.setText(text)

    def _refresh_rows(self) -> None:
        for w in self._row_widgets:
            self._rows_lay.removeWidget(w)
            w.deleteLater()
        self._row_widgets.clear()

        for year in registry.supported_years():
            path = config.FILE_PATHS.get(year)
            row = QWidget()
            row.setStyleSheet("background:transparent;")
            row_lay = QHBoxLayout(row)
            row_lay.setContentsMargins(0, 0, 0, 0)

            year_lbl = QLabel(str(year))
            year_lbl.setFixedWidth(44)
            year_lbl.setStyleSheet(f"color:{c('t1')}; background:transparent; font-weight:bold;")
            row_lay.addWidget(year_lbl)

            path_lbl = QLabel(str(path) if path else "(no file yet)")
            path_lbl.setStyleSheet(f"color:{c('t2') if path else c('t3')}; background:transparent;")
            row_lay.addWidget(path_lbl, 1)

            move_btn = _ghost_btn("Move…")
            move_btn.setFixedHeight(28)
            move_btn.setEnabled(path is not None and path.exists())
            move_btn.clicked.connect(lambda _checked, y=year: self._on_move(y))
            row_lay.addWidget(move_btn)

            self._rows_lay.addWidget(row)
            self._row_widgets.append(row)

    def _on_change_default_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Default folder for new files", str(config.FINANCES_DIR))
        if not folder:
            return
        settings.set_default_folder(Path(folder))
        config.FINANCES_DIR = Path(folder)
        self._default_folder_field.setText(folder)
        self._set_status("Default folder updated.", error=False)
        self.files_changed.emit()

    def _on_move(self, year: int) -> None:
        current = config.FILE_PATHS.get(year)
        if current is None:
            return
        folder = QFileDialog.getExistingDirectory(self, f"Move {current.name} to…", str(current.parent))
        if not folder:
            return
        new_path = Path(folder) / current.name
        try:
            file_ops.move_year_file(year, new_path)
        except FileExistsError:
            self._set_status(f"{new_path} already exists — pick a different folder.")
            return
        except (FileNotFoundError, PermissionError, OSError) as exc:
            self._set_status(f"Could not move the file: {exc}")
            return

        self._set_status(f"Moved {current.name} to {folder}.", error=False)
        self._refresh_rows()
        self.files_changed.emit()
