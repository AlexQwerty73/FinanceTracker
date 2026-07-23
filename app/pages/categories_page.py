"""
app/pages/categories_page.py — CategoriesPage: manage each year's category
list in one place. Renaming propagates to every transaction that uses the
old name (every month sheet, plus AllData for 2026) — fix a typo once here
instead of chasing it through every row it was ever entered on. Merge
reassigns one category's transactions into another, then removes the
source category. Delete only succeeds on a category with zero
transactions — merge first if it's in use.
"""
from __future__ import annotations

from datetime import date as Date

from PyQt6.QtWidgets import (
    QAbstractItemView, QHBoxLayout, QLabel, QLineEdit, QListWidget, QMessageBox, QVBoxLayout, QWidget,
)

from core.excel import registry
from core.excel.base import CategoryExistsError, CategoryInUseError
from core.excel.workbook_io import WorkbookLockedError
from core.themes import FIELD_HEIGHT, c, radius

from ..components.transaction_fields import input_style
from ..components.widgets import (
    NoWheelComboBox, bordered_box, primary_button, scrollable_area, secondary_button, section_label,
)


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
        self._list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self._list.setToolTip("Drag to reorder — this is the order categories show up in dropdowns.")
        self._list.setStyleSheet(f"""
            QListWidget {{ background:{c('in_bg')}; color:{c('t1')}; border:none; border-radius:8px; }}
            QListWidget::item {{ padding:6px 8px; }}
            QListWidget::item:selected {{ background:{c('btn_bg')}; color:{c('ac')}; }}
        """)
        self._list.model().rowsMoved.connect(self._on_reordered)
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

        actions_lay.addSpacing(12)
        actions_lay.addWidget(section_label("Merge selected into…"))
        self._merge_hint = QLabel("Select a category on the left first.")
        self._merge_hint.setWordWrap(True)
        self._merge_hint.setStyleSheet(f"color:{c('t3')}; background:transparent;")
        actions_lay.addWidget(self._merge_hint)
        self._merge_combo = NoWheelComboBox()
        self._merge_combo.setFixedHeight(FIELD_HEIGHT)
        self._merge_combo.setStyleSheet(input_style())
        actions_lay.addWidget(self._merge_combo)
        merge_btn = primary_button("Merge")
        merge_btn.clicked.connect(self._on_merge)
        actions_lay.addWidget(merge_btn)

        actions_lay.addSpacing(12)
        actions_lay.addWidget(section_label("Delete selected category"))
        delete_hint = QLabel("Only works if nothing uses it — merge it into another category first otherwise.")
        delete_hint.setWordWrap(True)
        delete_hint.setStyleSheet(f"color:{c('t3')}; background:transparent;")
        actions_lay.addWidget(delete_hint)
        delete_btn = secondary_button("Delete")
        delete_btn.clicked.connect(self._on_delete)
        actions_lay.addWidget(delete_btn)

        actions_lay.addStretch()

        body.addWidget(actions_box, 1)
        lay.addLayout(body, 1)

        self._list.currentTextChanged.connect(self._on_selection_changed)

    def _set_status(self, text: str, error: bool) -> None:
        self._status.setStyleSheet(f"color:{c('err_c') if error else c('income_c')}; background:transparent;")
        self._status.setText(text)

    def refresh_years(self) -> None:
        """Repopulate the Year dropdown — call after a new year's file is
        created via the Settings dialog's "Create New File" tab, since
        registry.supported_years() can grow at runtime and this combo was
        only populated once at init."""
        current = self._year_combo.currentText()
        years = registry.supported_years()
        self._year_combo.blockSignals(True)
        self._year_combo.clear()
        self._year_combo.addItems([str(y) for y in years])
        found = self._year_combo.findText(current) >= 0
        if found:
            self._year_combo.setCurrentText(current)
        self._year_combo.blockSignals(False)
        if not found and years:
            # The previously-selected year was just unregistered (e.g. its
            # only candidate file got unchecked) -- the combo silently fell
            # back to its first item while self._year still held the dead
            # year, so the next refresh() would show a stale "no template
            # registered" error until the user manually re-picked a year.
            self.refresh(years[0])

    def _on_year_changed(self, text: str) -> None:
        if text:
            self._year = int(text)
            self.refresh(self._year)

    def _on_selection_changed(self, text: str) -> None:
        if text:
            self._rename_hint.setText(f'Renaming "{text}" — this updates every transaction that uses it.')
            self._rename_field.setText(text)
            self._merge_hint.setText(f'Merging "{text}" into whatever you pick below — this reassigns its transactions.')
        else:
            self._rename_hint.setText("Select a category on the left first.")
            self._rename_field.clear()
            self._merge_hint.setText("Select a category on the left first.")
        self._refresh_merge_targets(exclude=text)

    def _refresh_merge_targets(self, exclude: str) -> None:
        current = self._merge_combo.currentText()
        others = [self._list.item(i).text() for i in range(self._list.count()) if self._list.item(i).text() != exclude]
        self._merge_combo.blockSignals(True)
        self._merge_combo.clear()
        self._merge_combo.addItems(others)
        if current in others:
            self._merge_combo.setCurrentText(current)
        self._merge_combo.blockSignals(False)

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
        self._refresh_merge_targets(exclude=self._list.currentItem().text() if self._list.currentItem() else "")

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

    def _on_merge(self) -> None:
        item = self._list.currentItem()
        if item is None:
            self._set_status("Select a category to merge first.", error=True)
            return
        source = item.text()
        target = self._merge_combo.currentText()
        if not target:
            self._set_status("Pick a category to merge into.", error=True)
            return
        reply = QMessageBox.question(
            self, "Merge category",
            f'Merge "{source}" into "{target}"?\n\n'
            f'Every transaction currently using "{source}" will be reassigned to "{target}", '
            f'then "{source}" is removed from the list. This can\'t be undone automatically.',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        try:
            schema = registry.get_schema_for_date(Date(self._year, 1, 1))
            count = schema.merge_category(source, target)
        except (WorkbookLockedError, ValueError) as exc:
            self._set_status(str(exc), error=True)
            return
        self._set_status(f'Merged "{source}" into "{target}" ({count} transaction(s) reassigned).', error=False)
        self.refresh(self._year)

    def _on_delete(self) -> None:
        item = self._list.currentItem()
        if item is None:
            self._set_status("Select a category to delete first.", error=True)
            return
        name = item.text()
        try:
            schema = registry.get_schema_for_date(Date(self._year, 1, 1))
            schema.delete_category(name)
        except (CategoryInUseError, WorkbookLockedError, ValueError) as exc:
            self._set_status(str(exc), error=True)
            return
        self._set_status(f'Deleted "{name}".', error=False)
        self.refresh(self._year)

    def _on_reordered(self, *_args) -> None:
        new_order = [self._list.item(i).text() for i in range(self._list.count())]
        try:
            schema = registry.get_schema_for_date(Date(self._year, 1, 1))
            schema.reorder_categories(new_order)
        except (WorkbookLockedError, ValueError) as exc:
            self._set_status(str(exc), error=True)
            self.refresh(self._year)  # revert the list to whatever's actually on disk
            return
        self._set_status("Order saved.", error=False)
