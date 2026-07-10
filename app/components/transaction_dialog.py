"""
app/components/transaction_dialog.py — TransactionDialog: edit an existing
transaction (pre-filled TransactionFields + Save/Cancel), opened from the
dashboard's transaction table.

If the edited date crosses into a different year (a different physical
workbook), this does a cross-file move: write the new row into the target
year's file *before* deleting the old row from the source year's file, so a
failure on the second step leaves a duplicate rather than losing the
transaction.
"""
from __future__ import annotations

from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from core.excel import registry
from core.excel.base import MONTH_NAMES, SheetFullError, TransactionNotFoundError
from core.excel.workbook_io import WorkbookLockedError
from core.themes import c

from .transaction_fields import TransactionFields


class TransactionDialog(QDialog):
    def __init__(self, schema, tx: dict, parent=None):
        super().__init__(parent)
        self._schema = schema
        self._tx = tx
        self.setWindowTitle("Edit Transaction")
        self.setFixedWidth(340)
        self.setStyleSheet(f"QDialog {{ background:{c('bg')}; }}")

        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 20, 20, 20)
        lay.setSpacing(8)

        hdr = QLabel("Edit Transaction")
        hdr.setFont(QFont("Segoe UI", 13, QFont.Weight.Bold))
        hdr.setStyleSheet(f"color:{c('t1')}; background:transparent;")
        lay.addWidget(hdr)

        self._fields = TransactionFields()
        if tx.get("date") is None:
            month_num = MONTH_NAMES.index(tx["month"]) + 1
            self._fields.set_date(schema.year, month_num, 1)
        self._fields.set_values(tx)
        lay.addWidget(self._fields)

        self._status = QLabel("")
        self._status.setWordWrap(True)
        self._status.setFont(QFont("Segoe UI", 9))
        lay.addWidget(self._status)

        btn_row = QHBoxLayout()
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setFixedHeight(32)
        cancel_btn.setStyleSheet(f"""
            QPushButton {{ background:transparent; color:{c('t2')};
                border:1px solid {c('in_bd')}; border-radius:8px; }}
            QPushButton:hover {{ color:{c('t1')}; border-color:{c('t2')}; }}
        """)
        cancel_btn.clicked.connect(self.reject)
        save_btn = QPushButton("Save changes")
        save_btn.setFixedHeight(32)
        save_btn.setStyleSheet(f"""
            QPushButton {{ background:{c('btn_bg')}; color:{c('ac')};
                border:1px solid {c('btn_bd')}; border-radius:8px; font-weight:bold; }}
            QPushButton:hover {{ background:{c('btn_hbg')}; }}
        """)
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
        note = self._fields.get_note()

        try:
            if target_schema is self._schema:
                self._schema.update_transaction(self._tx, new_date, type_, category, amount, payment_type, note)
            else:
                # Different year's file: add to the new one first, then remove
                # from the old one, so a failure here leaves a duplicate
                # rather than losing the transaction.
                target_schema.add_transaction(new_date, type_, category, amount, payment_type, note)
                self._schema.delete_transaction(self._tx)
        except (SheetFullError, TransactionNotFoundError, WorkbookLockedError) as exc:
            self._set_status(str(exc))
            return
        except Exception as exc:
            self._set_status(f"Unexpected error: {exc}")
            return

        self.accept()
