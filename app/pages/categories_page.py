"""
app/pages/categories_page.py — CategoriesPage: manage each year's category
list in one place. Renaming propagates to every transaction that uses the
old name (every month sheet, plus AllData for 2026) — fix a typo once here
instead of chasing it through every row it was ever entered on.
"""
from __future__ import annotations

from datetime import date as Date

from PyQt6.QtWidgets import (
    QHBoxLayout, QLabel, QLineEdit, QListWidget, QVBoxLayout, QWidget,
)

from core.excel import registry
from core.excel.base import CategoryExistsError
from core.excel.workbook_io import WorkbookLockedError
from core.themes import FIELD_HEIGHT, c, radius

from ..components.transaction_fields import input_style
from ..components.widgets import NoWheelComboBox, bordered_box, primary_button, scrollable_area, section_label


class CategoriesPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._year = registry.supported_years()[0]

        outer_lay = QVBoxLayout(self)
        outer_lay.setContentsMargins(0, 0, 0, 0)

        content = QWidget()
        content.setStyleSheet("background:transparent;")
        outer_lay.addWidget(scrollable_area(content))

        lay = QVBoxLayout(content)
        lay.setContentsMargins(4, 4, 4, 20)
        lay.setSpacing(14)

        year_row = QHBoxLayout()
        year_row.addWidget(section_label("Year"))
        self._year_combo = NoWheelComboBox()
        self._year_combo.addItems([str(y) for y in registry.supported_years()])
        self._year_combo.setFixedHeight(FIELD_HEIGHT)
        self._year_combo.setStyleSheet(input_style())
        self._year_combo.currentTextChanged.connect(self._on_year_changed)
        year_row.addWidget(self._year_combo)
        year_row.addStretch()
        lay.addLayout(year_row)

        self._status = QLabel("")
        self._status.setWordWrap(True)
        lay.addWidget(self._status)

        body = QHBoxLayout()
        body.setSpacing(16)

        list_box = bordered_box(c("panel_bg"), c("panel_bd"), radius=radius("xl"))
        list_lay = QVBoxLayout(list_box)
        list_lay.setContentsMargins(16, 14, 16, 14)
        list_lay.setSpacing(8)
        list_lay.addWidget(section_label("Categories"))
        self._list = QListWidget()
        self._list.setMinimumHeight(320)
        self._list.setStyleSheet(f"""
            QListWidget {{ background:{c('in_bg')}; color:{c('t1')}; border:none; border-radius:8px; }}
            QListWidget::item {{ padding:6px 8px; }}
            QListWidget::item:selected {{ background:{c('btn_bg')}; color:{c('ac')}; }}
        """)
        list_lay.addWidget(self._list, 1)
        body.addWidget(list_box, 1)

        actions_box = bordered_box(c("panel_bg"), c("panel_bd"), radius=radius("xl"))
        actions_lay = QVBoxLayout(actions_box)
        actions_lay.setContentsMargins(20, 16, 20, 16)
        actions_lay.setSpacing(10)

        actions_lay.addWidget(section_label("Add a category"))
        self._add_field = QLineEdit()
        self._add_field.setPlaceholderText("New category name...")
        self._add_field.setFixedHeight(FIELD_HEIGHT)
        self._add_field.setStyleSheet(input_style())
        actions_lay.addWidget(self._add_field)
        add_btn = primary_button("Add")
        add_btn.clicked.connect(self._on_add)
        actions_lay.addWidget(add_btn)

        actions_lay.addSpacing(12)
        actions_lay.addWidget(section_label("Rename selected category"))
        self._rename_hint = QLabel("Select a category on the left first.")
        self._rename_hint.setWordWrap(True)
        self._rename_hint.setStyleSheet(f"color:{c('t3')}; background:transparent;")
        actions_lay.addWidget(self._rename_hint)
        self._rename_field = QLineEdit()
        self._rename_field.setPlaceholderText("New name...")
        self._rename_field.setFixedHeight(FIELD_HEIGHT)
        self._rename_field.setStyleSheet(input_style())
        actions_lay.addWidget(self._rename_field)
        rename_btn = primary_button("Rename everywhere")
        rename_btn.clicked.connect(self._on_rename)
        actions_lay.addWidget(rename_btn)
        actions_lay.addStretch()

        body.addWidget(actions_box, 1)
        lay.addLayout(body, 1)

        self._list.currentTextChanged.connect(self._on_selection_changed)

    def _set_status(self, text: str, error: bool) -> None:
        self._status.setStyleSheet(f"color:{c('err_c') if error else c('income_c')}; background:transparent;")
        self._status.setText(text)

    def refresh_years(self) -> None:
        """Repopulate the Year dropdown — call after a new year's file is
        created via CreateFileDialog, since registry.supported_years() can
        grow at runtime and this combo was only populated once at init."""
        current = self._year_combo.currentText()
        self._year_combo.blockSignals(True)
        self._year_combo.clear()
        self._year_combo.addItems([str(y) for y in registry.supported_years()])
        if self._year_combo.findText(current) >= 0:
            self._year_combo.setCurrentText(current)
        self._year_combo.blockSignals(False)

    def _on_year_changed(self, text: str) -> None:
        if text:
            self._year = int(text)
            self.refresh(self._year)

    def _on_selection_changed(self, text: str) -> None:
        if text:
            self._rename_hint.setText(f'Renaming "{text}" — this updates every transaction that uses it.')
            self._rename_field.setText(text)
        else:
            self._rename_hint.setText("Select a category on the left first.")
            self._rename_field.clear()

    def refresh(self, year: int | None = None) -> None:
        if year is not None:
            self._year = year
            if self._year_combo.currentText() != str(year):
                self._year_combo.setCurrentText(str(year))
        try:
            schema = registry.get_schema_for_date(Date(self._year, 1, 1))
            categories = schema.get_categories()
        except (ValueError, WorkbookLockedError) as exc:
            self._set_status(str(exc), error=True)
            return

        self._set_status("", error=False)
        self._list.clear()
        self._list.addItems(categories)

    def _on_add(self) -> None:
        name = self._add_field.text().strip()
        if not name:
            self._set_status("Enter a category name.", error=True)
            return
        try:
            schema = registry.get_schema_for_date(Date(self._year, 1, 1))
            schema.add_category(name)
        except (CategoryExistsError, WorkbookLockedError, ValueError) as exc:
            self._set_status(str(exc), error=True)
            return
        self._add_field.clear()
        self._set_status(f'Added "{name}".', error=False)
        self.refresh(self._year)

    def _on_rename(self) -> None:
        item = self._list.currentItem()
        if item is None:
            self._set_status("Select a category to rename first.", error=True)
            return
        old_name = item.text()
        new_name = self._rename_field.text().strip()
        if not new_name:
            self._set_status("Enter a new name.", error=True)
            return
        if new_name == old_name:
            self._set_status("That's already the current name.", error=True)
            return
        try:
            schema = registry.get_schema_for_date(Date(self._year, 1, 1))
            count = schema.rename_category(old_name, new_name)
        except (CategoryExistsError, WorkbookLockedError, ValueError) as exc:
            self._set_status(str(exc), error=True)
            return
        self._set_status(f'Renamed "{old_name}" → "{new_name}" ({count} transaction(s) updated).', error=False)
        self.refresh(self._year)
