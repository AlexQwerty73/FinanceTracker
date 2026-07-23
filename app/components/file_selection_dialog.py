"""
app/components/file_selection_dialog.py — FileSelectionDialog: a checkbox
list of every *.xlsx found in the default Finances folder, so the user can
tell the app which ones are actually finance files (the folder can hold
unrelated files too, e.g. a stickers spreadsheet) instead of the app
guessing. A year can have more than one checked/tracked candidate (e.g.
while trying out a new layout side by side with the original) — exactly
one is "active" at a time, switched with the ● button on its row.
"""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QCursor, QFont
from PyQt6.QtWidgets import (
    QCheckBox, QDialog, QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout, QWidget,
)

from core import config, file_ops, settings
from core.themes import FIELD_HEIGHT, c, font_size

from .transaction_fields import input_style
from .widgets import NoWheelComboBox, nav_chip_style, primary_button

_TEMPLATE_LABELS = [
    ("Simple — quick monthly entry, no per-transaction date", settings.TEMPLATE_2025),
    ("Detailed — dated transactions, running balance, full log", settings.TEMPLATE_2026),
]


class FileSelectionDialog(QDialog):
    files_changed = pyqtSignal()  # emitted after any check/uncheck/activate that changes tracking

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Select Finance Files")
        self.setFixedWidth(620)
        self.setStyleSheet(f"QDialog {{ background:{c('bg')}; }}")

        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 20, 20, 20)
        lay.setSpacing(10)

        hdr = QLabel("Select Finance Files")
        hdr.setFont(QFont("Segoe UI", font_size("dialog"), QFont.Weight.Bold))
        hdr.setStyleSheet(f"color:{c('t1')}; background:transparent;")
        lay.addWidget(hdr)

        desc = QLabel(
            f"Every .xlsx found in {config.FINANCES_DIR} — check the ones that are actually "
            "finance files. A year with more than one checked file needs one marked active (●) "
            "— that's the one the app reads and writes."
        )
        desc.setWordWrap(True)
        desc.setStyleSheet(f"color:{c('t2')}; background:transparent;")
        lay.addWidget(desc)

        self._rows_lay = QVBoxLayout()
        self._rows_lay.setSpacing(6)
        lay.addLayout(self._rows_lay)
        self._row_widgets: list[QWidget] = []

        self._status = QLabel("")
        self._status.setWordWrap(True)
        self._status.setFont(QFont("Segoe UI", font_size("label")))
        lay.addWidget(self._status)

        close_btn = primary_button("Close")
        close_btn.clicked.connect(self.accept)
        lay.addWidget(close_btn)

        self._refresh_rows()

    def _set_status(self, text: str, error: bool = True) -> None:
        self._status.setStyleSheet(f"color:{c('err_c') if error else c('income_c')}; background:transparent;")
        self._status.setText(text)

    # ── row building ─────────────────────────────────────────────────────

    def _refresh_rows(self) -> None:
        for w in self._row_widgets:
            self._rows_lay.removeWidget(w)
            w.deleteLater()
        self._row_widgets.clear()

        by_path = file_ops.known_candidate_years()
        active_paths = set(settings.get_file_paths().values())
        known_stems = {p.stem for p in by_path}
        for path in file_ops.discover_candidate_files(config.FINANCES_DIR):
            year = by_path.get(path)
            if year is None and file_ops.detect_conflict_copy(path, known_stems):
                row = self._build_conflict_row(path)
            else:
                row = self._build_row(path, year, active=path in active_paths)
            self._rows_lay.addWidget(row)
            self._row_widgets.append(row)

    def _build_conflict_row(self, path: Path) -> QWidget:
        """A likely OneDrive sync-conflict copy of an already-tracked file
        -- shown as a plain warning, not a checkbox, so it can't be
        accidentally checked in as if it were a normal candidate (see
        core/file_ops.py::detect_conflict_copy())."""
        row = QWidget()
        row.setStyleSheet("background:transparent;")
        lay = QHBoxLayout(row)
        lay.setContentsMargins(0, 0, 0, 0)
        warn = QLabel(f"⚠ {path.name} — looks like a OneDrive sync-conflict copy, not tracked")
        warn.setStyleSheet(f"color:{c('err_c')}; background:transparent;")
        lay.addWidget(warn, 1)
        return row

    def _build_row(self, path: Path, year: int | None, active: bool) -> QWidget:
        row = QWidget()
        row.setStyleSheet("background:transparent;")
        outer = QVBoxLayout(row)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(4)

        top = QHBoxLayout()
        checkbox = QCheckBox(path.name)
        checkbox.setChecked(year is not None)
        checkbox.setStyleSheet(f"QCheckBox {{ color:{c('t1')}; background:transparent; }}")
        top.addWidget(checkbox, 1)

        if year is not None:
            year_lbl = QLabel(f"year {year}")
            year_lbl.setStyleSheet(f"color:{c('t3')}; background:transparent;")
            top.addWidget(year_lbl)

            candidates = settings.get_candidates(year)
            if len(candidates) > 1:
                active_btn = QPushButton("● active" if active else "set active")
                active_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
                active_btn.setFixedHeight(26)
                active_btn.setStyleSheet(nav_chip_style(active, radius_key="sm"))
                if not active:
                    active_btn.clicked.connect(lambda _c=False, y=year, p=path: self._on_set_active(y, p))
                else:
                    active_btn.setEnabled(False)
                top.addWidget(active_btn)
        outer.addLayout(top)

        # inline year/template picker, shown only while confirming a
        # newly-checked, previously-unknown file
        confirm_row = QWidget()
        confirm_row.setVisible(False)
        confirm_lay = QHBoxLayout(confirm_row)
        confirm_lay.setContentsMargins(24, 0, 0, 0)
        confirm_lay.setSpacing(6)
        year_field = QLineEdit()
        year_field.setPlaceholderText("Year, e.g. 2026")
        year_field.setFixedHeight(FIELD_HEIGHT)
        year_field.setFixedWidth(110)
        year_field.setStyleSheet(input_style())
        template_combo = NoWheelComboBox()
        for label, tid in _TEMPLATE_LABELS:
            template_combo.addItem(label, tid)
        template_combo.setFixedHeight(FIELD_HEIGHT)
        template_combo.setStyleSheet(input_style())
        add_btn = primary_button("Add")
        confirm_lay.addWidget(year_field)
        confirm_lay.addWidget(template_combo, 1)
        confirm_lay.addWidget(add_btn)
        outer.addWidget(confirm_row)

        add_btn.clicked.connect(lambda _c=False, p=path: self._on_confirm_new(p, year_field, template_combo, checkbox, confirm_row))
        checkbox.toggled.connect(lambda checked, p=path, y=year, cr=confirm_row: self._on_toggled(checked, p, y, cr))

        return row

    # ── actions ──────────────────────────────────────────────────────────

    def _on_toggled(self, checked: bool, path: Path, year: int | None, confirm_row: QWidget) -> None:
        if checked and year is None:
            confirm_row.setVisible(True)
            return
        confirm_row.setVisible(False)
        if not checked and year is not None:
            try:
                settings.unregister_candidate(year, path)
            except ValueError as exc:
                self._set_status(str(exc))
                self._refresh_rows()  # snaps the checkbox back to checked
                return
            self._set_status(f"Stopped tracking {path.name}.", error=False)
            self.files_changed.emit()
            self._refresh_rows()

    def _on_confirm_new(self, path: Path, year_field: QLineEdit, template_combo: NoWheelComboBox,
                         checkbox: QCheckBox, confirm_row: QWidget) -> None:
        year_text = year_field.text().strip()
        try:
            year = int(year_text)
            if not (1900 <= year <= 9999):
                raise ValueError
        except ValueError:
            self._set_status("Enter a valid year (e.g. 2026).")
            return
        template_id = template_combo.currentData()
        settings.register_candidate(year, path, template_id, activate=True)
        config.FILE_PATHS[year] = path
        self._set_status(f"Added {path.name} as year {year}.", error=False)
        self.files_changed.emit()
        self._refresh_rows()

    def _on_set_active(self, year: int, path: Path) -> None:
        file_ops.set_active_file(year, path)
        self._set_status(f"{path.name} is now active for {year}.", error=False)
        self.files_changed.emit()
        self._refresh_rows()
