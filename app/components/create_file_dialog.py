"""
app/components/create_file_dialog.py — CreateFileDialog: generate a
brand-new, blank Finances_<year>.xlsx from one of the two built-in layouts
and register it, so someone without an existing file (e.g. this app
shared with someone else) can start using it from scratch.
"""
from __future__ import annotations

from datetime import date as Date
from pathlib import Path

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import QDialog, QFileDialog, QHBoxLayout, QLabel, QLineEdit, QVBoxLayout

from core import config, settings
from core.excel import template_model, templates
from core.themes import FIELD_HEIGHT, c, font_size

from .transaction_fields import field_label, input_style
from .widgets import NoWheelComboBox, primary_button, secondary_button

_NEW_TEMPLATE_SENTINEL = "__new_template__"


class CreateFileDialog(QDialog):
    file_created = pyqtSignal(int)  # emits the new year on success
    manage_templates_requested = pyqtSignal()  # user picked "design a new template"

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Create New Finances File")
        self.setFixedWidth(420)
        self.setStyleSheet(f"QDialog {{ background:{c('bg')}; }}")

        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 20, 20, 20)
        lay.setSpacing(10)

        hdr = QLabel("Create New Finances File")
        hdr.setFont(QFont("Segoe UI", font_size("dialog"), QFont.Weight.Bold))
        hdr.setStyleSheet(f"color:{c('t1')}; background:transparent;")
        lay.addWidget(hdr)

        desc = QLabel(
            "Generates a blank Excel workbook this app can read and write. Picking a year that "
            "already has a file adds this as an extra candidate for that year (and switches to "
            "it) — manage which file is active from ⚙ Manage files."
        )
        desc.setWordWrap(True)
        desc.setStyleSheet(f"color:{c('t2')}; background:transparent;")
        lay.addWidget(desc)

        lay.addWidget(field_label("Layout"))
        self._template_combo = NoWheelComboBox()
        self._template_combo.setFixedHeight(FIELD_HEIGHT)
        self._template_combo.setStyleSheet(input_style())
        self._template_combo.currentIndexChanged.connect(self._on_template_selection_changed)
        lay.addWidget(self._template_combo)
        self._refresh_template_combo()

        lay.addWidget(field_label("Year"))
        self._year_field = QLineEdit(str(self._suggest_year()))
        self._year_field.setFixedHeight(FIELD_HEIGHT)
        self._year_field.setStyleSheet(input_style())
        self._year_field.textChanged.connect(self._on_year_changed)
        lay.addWidget(self._year_field)

        lay.addWidget(field_label("Save to"))
        path_row = QHBoxLayout()
        self._path_field = QLineEdit()
        self._path_field.setReadOnly(True)
        self._path_field.setFixedHeight(FIELD_HEIGHT)
        self._path_field.setStyleSheet(input_style())
        browse_btn = secondary_button("Browse…")
        browse_btn.setFixedHeight(FIELD_HEIGHT)
        browse_btn.clicked.connect(self._on_browse)
        path_row.addWidget(self._path_field, 1)
        path_row.addWidget(browse_btn)
        lay.addLayout(path_row)
        self._set_default_path()

        self._status = QLabel("")
        self._status.setWordWrap(True)
        self._status.setFont(QFont("Segoe UI", font_size("label")))
        lay.addWidget(self._status)

        btn_row = QHBoxLayout()
        cancel_btn = secondary_button("Cancel")
        cancel_btn.clicked.connect(self.reject)
        create_btn = primary_button("Create")
        create_btn.clicked.connect(self._on_create)
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(create_btn)
        lay.addLayout(btn_row)

    def _refresh_template_combo(self, select_id: str | None = None) -> None:
        self._template_combo.blockSignals(True)
        self._template_combo.clear()
        self._template_combo.addItem("Simple — quick monthly entry, no per-transaction date", settings.TEMPLATE_2025)
        self._template_combo.addItem("Detailed — dated transactions, running balance, full log", settings.TEMPLATE_2026)
        for t in template_model.list_templates():
            self._template_combo.addItem(f"{t.name} (custom)", t.id)
        self._template_combo.addItem("＋ Design a new template…", _NEW_TEMPLATE_SENTINEL)
        if select_id is not None:
            idx = self._template_combo.findData(select_id)
            if idx >= 0:
                self._template_combo.setCurrentIndex(idx)
        self._template_combo.blockSignals(False)

    def _on_template_selection_changed(self, _index: int) -> None:
        if self._template_combo.currentData() != _NEW_TEMPLATE_SENTINEL:
            return
        # Template design now happens on its own page (live preview etc.) —
        # close this dialog and let the app switch there; the new template
        # will show up in this combo next time it's opened.
        self.manage_templates_requested.emit()
        self.reject()

    def _suggest_year(self) -> int:
        used = set(settings.get_year_templates())
        year = Date.today().year
        while year in used:
            year += 1
        return year

    def _set_default_path(self) -> None:
        year_text = self._year_field.text().strip() or str(self._suggest_year())
        self._path_field.setText(str(config.FINANCES_DIR / f"Finances_{year_text}.xlsx"))

    def _on_year_changed(self, _text: str) -> None:
        self._set_default_path()

    def _set_status(self, text: str) -> None:
        self._status.setStyleSheet(f"color:{c('err_c')}; background:transparent;")
        self._status.setText(text)

    def _on_browse(self) -> None:
        year_text = self._year_field.text().strip() or str(self._suggest_year())
        start_path = self._path_field.text() or str(config.FINANCES_DIR / f"Finances_{year_text}.xlsx")
        path, _ = QFileDialog.getSaveFileName(self, "Save new finances file", start_path, "Excel Workbook (*.xlsx)")
        if path:
            self._path_field.setText(path)

    def _on_create(self) -> None:
        year_text = self._year_field.text().strip()
        try:
            year = int(year_text)
            if not (1900 <= year <= 9999):
                raise ValueError
        except ValueError:
            self._set_status("Enter a valid year (e.g. 2027).")
            return

        path_text = self._path_field.text().strip()
        if not path_text:
            self._set_status("Choose where to save the file.")
            return
        path = Path(path_text)

        template_id = self._template_combo.currentData()
        if template_id == _NEW_TEMPLATE_SENTINEL:
            self._set_status("Pick a layout, or finish creating the new template first.")
            return

        try:
            if template_id == settings.TEMPLATE_2025:
                templates.create_2025_style_workbook(path, year)
            elif template_id == settings.TEMPLATE_2026:
                templates.create_2026_style_workbook(path, year)
            else:
                custom = template_model.get_template(template_id)
                if custom is None:
                    self._set_status("That template no longer exists — pick another.")
                    return
                templates.create_custom_workbook(path, year, custom)
        except OSError as exc:
            self._set_status(f"Could not create the file: {exc}")
            return

        settings.register_candidate(year, path, template_id, activate=True)
        config.FILE_PATHS[year] = path
        self.file_created.emit(year)
        self.accept()
