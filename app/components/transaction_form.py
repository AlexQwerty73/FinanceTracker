"""
app/components/transaction_form.py — TransactionForm: left-panel ADD form.
Wraps TransactionFields with a Save button; emits `saved` so the dashboard
can refresh.
"""
from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QCursor, QFont
from PyQt6.QtWidgets import QLabel, QPushButton, QVBoxLayout, QWidget

from core.excel import registry
from core.excel.base import SheetFullError
from core.excel.workbook_io import WorkbookLockedError
from core.themes import c

from .transaction_fields import TransactionFields


class TransactionForm(QWidget):
    saved = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(300)
        self.setStyleSheet(f"background:{c('panel_bg')}; border:1px solid {c('panel_bd')}; border-radius:14px;")

        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 20, 20, 20)
        lay.setSpacing(8)

        hdr = QLabel("Add Transaction")
        hdr.setFont(QFont("Segoe UI", 14, QFont.Weight.Bold))
        hdr.setStyleSheet(f"color:{c('t1')}; background:transparent;")
        lay.addWidget(hdr)
        lay.addSpacing(6)

        self._fields = TransactionFields()
        lay.addWidget(self._fields)

        lay.addSpacing(4)
        self._status = QLabel("")
        self._status.setWordWrap(True)
        self._status.setFont(QFont("Segoe UI", 9))
        lay.addWidget(self._status)

        self._save_btn = QPushButton("Save")
        self._save_btn.setFixedHeight(36)
        self._save_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._save_btn.setStyleSheet(f"""
            QPushButton {{ background:{c('btn_bg')}; color:{c('ac')};
                border:1px solid {c('btn_bd')}; border-radius:8px; font-weight:bold; }}
            QPushButton:hover {{ background:{c('btn_hbg')}; }}
        """)
        self._save_btn.clicked.connect(self._on_save)
        lay.addWidget(self._save_btn)
        lay.addStretch()

    def _set_status(self, text: str, error: bool) -> None:
        self._status.setText(text)
        self._status.setStyleSheet(
            f"color:{c('err_c') if error else c('income_c')}; background:transparent;"
        )

    def _on_save(self) -> None:
        d = self._fields.get_date()
        try:
            schema = registry.get_schema_for_date(d)
        except ValueError as exc:
            self._set_status(str(exc), error=True)
            return

        amount_text = self._fields.get_amount_text().strip().replace(",", ".")
        try:
            amount = float(amount_text)
            if amount <= 0:
                raise ValueError
        except ValueError:
            self._set_status("Enter a valid positive amount.", error=True)
            return

        try:
            schema.add_transaction(
                d, self._fields.get_type(), self._fields.get_category(),
                amount, self._fields.get_payment_type(), self._fields.get_note(),
            )
        except (SheetFullError, WorkbookLockedError) as exc:
            self._set_status(str(exc), error=True)
            return
        except Exception as exc:
            self._set_status(f"Unexpected error: {exc}", error=True)
            return

        self._set_status("Saved.", error=False)
        self._fields.clear_amount_and_note()
        self.saved.emit()
