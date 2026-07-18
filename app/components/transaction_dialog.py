"""
app/components/transaction_dialog.py — TransactionDialog: add a new
transaction, or edit an existing one. Pass tx=None for add mode (defaults to
today); pass tx + source_schema (the schema it came from) to edit.

If the edited/entered date falls in a different year (a different physical
workbook) than the transaction's original year, this does a cross-file move:
write the new row into the target year's file *before* deleting the old row
from the source year's file, so a failure on the second step leaves a
duplicate rather than losing the transaction.
"""
from __future__ import annotations

from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import QDialog, QHBoxLayout, QLabel, QVBoxLayout

from core import prefs
from core.excel import registry
from core.excel.base import MONTH_NAMES, SheetFullError, TransactionNotFoundError
from core.excel.workbook_io import WorkbookLockedError
from core.themes import c, font_size

from .transaction_fields import TransactionFields
from .widgets import primary_button, secondary_button


class TransactionDialog(QDialog):
    def __init__(self, tx: dict | None = None, source_schema=None, parent=None):
        super().__init__(parent)
        self._is_edit = tx is not None
        self._tx = tx
        self._source_schema = source_schema

        self.setWindowTitle("Edit Transaction" if self._is_edit else "Add Transaction")
        self.setFixedWidth(340)
        self.setStyleSheet(f"QDialog {{ background:{c('bg')}; }}")

        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 20, 20, 20)
        lay.setSpacing(8)

        hdr = QLabel("Edit Transaction" if self._is_edit else "Add Transaction")
        hdr.setFont(QFont("Segoe UI", font_size("dialog"), QFont.Weight.Bold))
        hdr.setStyleSheet(f"color:{c('t1')}; background:transparent;")
        lay.addWidget(hdr)

        self._fields = TransactionFields(remember_payment=not self._is_edit)
        if self._is_edit:
            if tx.get("date") is None:
                month_num = MONTH_NAMES.index(tx["month"]) + 1
                self._fields.set_date(source_schema.year, month_num, 1)
            self._fields.set_values(tx)
        lay.addWidget(self._fields)

        self._status = QLabel("")
        self._status.setWordWrap(True)
        self._status.setFont(QFont("Segoe UI", font_size("label")))
        lay.addWidget(self._status)

        btn_row = QHBoxLayout()
        cancel_btn = secondary_button("Cancel")
        cancel_btn.clicked.connect(self.reject)
        save_btn = primary_button("Save changes" if self._is_edit else "Add")
        save_btn.clicked.connect(self._on_save)
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(save_btn)
        lay.addLayout(btn_row)

    def _set_status(self, text: str) -> None:
        self._status.setStyleSheet(f"color:{c('err_c')}; background:transparent;")
        self._status.setText(text)

    def _on_save(self) -> None:
        new_date = self._fields.get_date()
        try:
            target_schema = registry.get_schema_for_date(new_date)
        except ValueError as exc:
            self._set_status(str(exc))
            return

        amount_text = self._fields.get_amount_text().strip().replace(",", ".")
        try:
            amount = float(amount_text)
            if amount <= 0:
                raise ValueError
        except ValueError:
            self._set_status("Enter a valid positive amount.")
            return

        type_ = self._fields.get_type()
        category = self._fields.get_category()
        payment_type = self._fields.get_payment_type()
        currency = self._fields.get_currency()
        note = self._fields.get_note()

        try:
            if not self._is_edit:
                target_schema.add_transaction(new_date, type_, category, amount, payment_type, note, currency)
            elif target_schema is self._source_schema:
                self._source_schema.update_transaction(
                    self._tx, new_date, type_, category, amount, payment_type, note, currency
                )
            else:
                # Different year's file: add to the new one first, then remove
                # from the old one, so a failure here leaves a duplicate
                # rather than losing the transaction.
                target_schema.add_transaction(new_date, type_, category, amount, payment_type, note, currency)
                self._source_schema.delete_transaction(self._tx)
        except (SheetFullError, TransactionNotFoundError, WorkbookLockedError) as exc:
            self._set_status(str(exc))
            return
        except Exception as exc:
            self._set_status(f"Unexpected error: {exc}")
            return

        if payment_type:
            prefs.set_last_payment_type(target_schema.year, payment_type)
        if currency:
            prefs.set_last_currency(target_schema.year, currency)

        self.accept()
