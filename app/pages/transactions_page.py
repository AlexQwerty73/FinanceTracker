"""
app/pages/transactions_page.py — TransactionsPage: the full, searchable,
editable transaction list for the viewed month.
"""
from __future__ import annotations

from datetime import date as Date

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QCursor
from PyQt6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton,
    QScrollArea, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from core.excel import registry
from core.excel.base import MONTH_NAMES, TransactionNotFoundError
from core.excel.workbook_io import WorkbookLockedError
from core.format import fmt_amount
from core.themes import c

from ..components.transaction_dialog import TransactionDialog
from ..components.transaction_fields import input_style
from ..components.widgets import NoWheelComboBox


class TransactionsPage(QWidget):
    analytics_clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._year = Date.today().year
        self._month = Date.today().month
        self._all_txs: list[dict] = []
        self._filtered_txs: list[dict] = []
        self._current_schema = None
        self._row_widgets: list[dict] = []  # per row: {"type","category","amount","payment","note"}
        self._dirty_rows: set[int] = set()

        outer_lay = QVBoxLayout(self)
        outer_lay.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet(f"""
            QScrollArea {{ background:transparent; border:none; }}
            QScrollBar:vertical {{ background:transparent; width:8px; }}
            QScrollBar::handle:vertical {{ background:{c('in_bd')}; border-radius:4px; min-height:24px; }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height:0; }}
        """)
        outer_lay.addWidget(scroll)

        content = QWidget()
        content.setStyleSheet("background:transparent;")
        scroll.setWidget(content)

        lay = QVBoxLayout(content)
        lay.setContentsMargins(4, 4, 4, 20)
        lay.setSpacing(10)

        header_row = QHBoxLayout()
        analytics_btn = QPushButton("← Analytics")
        analytics_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        analytics_btn.setStyleSheet(f"""
            QPushButton {{ background:transparent; color:{c('ac')}; border:none; }}
            QPushButton:hover {{ text-decoration:underline; }}
        """)
        analytics_btn.clicked.connect(self.analytics_clicked.emit)
        header_row.addWidget(analytics_btn)
        header_row.addStretch()
        lay.addLayout(header_row)

        self._status = QLabel("")
        self._status.setWordWrap(True)
        self._status.setStyleSheet(f"color:{c('err_c')}; background:transparent;")
        lay.addWidget(self._status)

        self._search = QLineEdit()
        self._search.setPlaceholderText("Search by category or note...")
        self._search.setFixedHeight(34)
        self._search.setStyleSheet(input_style())
        self._search.textChanged.connect(self._apply_filter)
        lay.addWidget(self._search)

        self._table = QTableWidget(0, 6)
        self._table.setHorizontalHeaderLabels(["Date", "Type", "Category", "Amount", "Payment", "Note"])
        self._table.verticalHeader().setVisible(False)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self._table.horizontalHeader().setStretchLastSection(True)
        for col, width in [(0, 90), (1, 130), (2, 170), (3, 100), (4, 90)]:
            self._table.setColumnWidth(col, width)
        self._table.setMinimumHeight(320)
        self._table.setStyleSheet(f"""
            QTableWidget {{ background:{c('panel_bg')}; color:{c('t1')}; border:1px solid {c('panel_bd')};
                border-radius:10px; gridline-color:{c('sep')}; }}
            QHeaderView::section {{ background:transparent; color:{c('t2')}; border:none;
                border-bottom:1px solid {c('sep')}; padding:6px; }}
            QTableWidget::item {{ padding:4px; }}
            QTableWidget::item:selected {{ background:{c('btn_bg')}; }}
        """)
        lay.addWidget(self._table, 1)

        row_actions = QHBoxLayout()
        self._save_btn = QPushButton("Save changes")
        self._save_btn.setFixedHeight(32)
        self._save_btn.setEnabled(False)
        self._save_btn.setStyleSheet(f"""
            QPushButton {{ background:{c('btn_bg')}; color:{c('ac')};
                border:1px solid {c('btn_bd')}; border-radius:6px; font-weight:bold; padding:0 16px; }}
            QPushButton:hover {{ background:{c('btn_hbg')}; }}
            QPushButton:disabled {{ background:transparent; color:{c('t3')}; border-color:{c('in_bd')}; }}
        """)
        self._save_btn.clicked.connect(self._on_save_changes)
        row_actions.addWidget(self._save_btn)
        row_actions.addStretch()
        self._edit_btn = QPushButton("Edit date/month…")
        self._edit_btn.setFixedHeight(32)
        self._edit_btn.setToolTip("Open the full dialog — needed to move a transaction to a different date or month.")
        self._edit_btn.setStyleSheet(f"""
            QPushButton {{ background:transparent; color:{c('t2')};
                border:1px solid {c('in_bd')}; border-radius:6px; padding:0 16px; }}
            QPushButton:hover {{ color:{c('ac')}; border-color:{c('ac')}; }}
        """)
        self._edit_btn.clicked.connect(self._on_edit)
        self._delete_btn = QPushButton("Delete")
        self._delete_btn.setFixedHeight(32)
        self._delete_btn.setStyleSheet(f"""
            QPushButton {{ background:transparent; color:{c('t2')};
                border:1px solid {c('in_bd')}; border-radius:6px; padding:0 16px; }}
            QPushButton:hover {{ color:{c('err_c')}; border-color:{c('err_c')}; }}
        """)
        self._delete_btn.clicked.connect(self._on_delete)
        row_actions.addWidget(self._edit_btn)
        row_actions.addWidget(self._delete_btn)
        lay.addLayout(row_actions)

    def _set_status(self, text: str, error: bool = True) -> None:
        self._status.setStyleSheet(f"color:{c('err_c') if error else c('income_c')}; background:transparent;")
        self._status.setText(text)

    def refresh(self, year: int, month: int) -> None:
        self._year, self._month = year, month
        try:
            schema = registry.get_schema_for_date(Date(year, month, 1))
        except ValueError as exc:
            self._set_status(str(exc))
            return

        self._current_schema = schema
        try:
            self._all_txs = schema.transactions_for_month(month)
        except WorkbookLockedError as exc:
            self._set_status(str(exc))
            return

        self._set_status("", error=False)
        self._apply_filter()

    def _apply_filter(self) -> None:
        query = self._search.text().strip().lower()
        if not query:
            self._filtered_txs = list(self._all_txs)
        else:
            self._filtered_txs = [
                tx for tx in self._all_txs
                if query in (tx.get("category") or "").lower() or query in (tx.get("note") or "").lower()
            ]
        self._render_table()

    def _render_table(self) -> None:
        schema = self._current_schema
        txs = self._filtered_txs
        self._row_widgets = []
        self._dirty_rows = set()
        self._table.setRowCount(len(txs))

        types = schema.get_types() if schema is not None else []
        categories = schema.get_categories() if schema is not None else []
        payment_types = schema.get_payment_types() if schema is not None else None

        for row, tx in enumerate(txs):
            date_val = tx.get("date")
            date_str = date_val.strftime("%Y-%m-%d") if date_val else tx.get("month", "")
            date_item = QTableWidgetItem(date_str)
            self._table.setItem(row, 0, date_item)

            type_combo = NoWheelComboBox()
            type_combo.addItems(types)
            idx = type_combo.findText(tx.get("type") or "")
            if idx >= 0:
                type_combo.setCurrentIndex(idx)
            type_combo.setStyleSheet(input_style())

            category_combo = NoWheelComboBox()
            category_combo.addItems(categories)
            idx = category_combo.findText(tx.get("category") or "")
            if idx >= 0:
                category_combo.setCurrentIndex(idx)
            category_combo.setStyleSheet(input_style())

            amount_field = QLineEdit(f"{tx.get('amount') or 0:g}")
            amount_field.setStyleSheet(input_style())
            amount_field.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

            payment_combo = None
            if payment_types is not None:
                payment_combo = NoWheelComboBox()
                payment_combo.addItems(payment_types)
                idx = payment_combo.findText(tx.get("payment_type") or "")
                if idx >= 0:
                    payment_combo.setCurrentIndex(idx)
                elif "Card" in payment_types:
                    # No payment recorded on this row (e.g. an older 2025
                    # entry from before the column existed) — default the
                    # display to Card, same preference as new transactions.
                    payment_combo.setCurrentText("Card")
                payment_combo.setStyleSheet(input_style())
                self._table.setCellWidget(row, 4, payment_combo)
            else:
                self._table.setItem(row, 4, QTableWidgetItem(""))

            note_field = QLineEdit(tx.get("note") or "")
            note_field.setStyleSheet(input_style())

            self._table.setCellWidget(row, 1, type_combo)
            self._table.setCellWidget(row, 2, category_combo)
            self._table.setCellWidget(row, 3, amount_field)
            self._table.setCellWidget(row, 5, note_field)

            self._row_widgets.append({
                "type": type_combo, "category": category_combo, "amount": amount_field,
                "payment": payment_combo, "note": note_field,
            })
            self._update_amount_color(row)

            # Connect change signals only after every field's initial value
            # is set, so pre-filling from the existing transaction doesn't
            # itself get flagged as an edit.
            type_combo.currentTextChanged.connect(lambda _t, r=row: self._on_type_changed(r))
            category_combo.currentTextChanged.connect(lambda _t, r=row: self._on_field_changed(r))
            amount_field.textChanged.connect(lambda _t, r=row: self._on_field_changed(r))
            note_field.textChanged.connect(lambda _t, r=row: self._on_field_changed(r))
            if payment_combo is not None:
                payment_combo.currentTextChanged.connect(lambda _t, r=row: self._on_field_changed(r))

        self._update_save_button()

    def _update_amount_color(self, row: int) -> None:
        schema = self._current_schema
        amount_field = self._row_widgets[row]["amount"]
        type_text = self._row_widgets[row]["type"].currentText()
        is_expense = schema is not None and schema.is_expense_type(type_text)
        color = c("expense_c") if is_expense else c("income_c")
        amount_field.setStyleSheet(input_style() + f"QLineEdit {{ color:{color}; font-weight:bold; }}")

    def _on_type_changed(self, row: int) -> None:
        self._update_amount_color(row)
        self._on_field_changed(row)

    def _on_field_changed(self, row: int) -> None:
        self._dirty_rows.add(row)
        self._update_save_button()

    def _update_save_button(self) -> None:
        n = len(self._dirty_rows)
        self._save_btn.setEnabled(n > 0)
        self._save_btn.setText(f"Save changes ({n})" if n else "Save changes")

    def _on_save_changes(self) -> None:
        schema = self._current_schema
        if schema is None or not self._dirty_rows:
            return

        # Validate every dirty row before writing anything, so a bad amount
        # in one row doesn't leave the workbook half-updated.
        to_write: list[tuple[dict, Date, str, str, float, str | None, str]] = []
        for row in sorted(self._dirty_rows):
            tx = self._filtered_txs[row]
            widgets = self._row_widgets[row]
            new_type = widgets["type"].currentText()
            new_category = widgets["category"].currentText()
            amount_text = widgets["amount"].text().strip().replace(",", ".")
            try:
                new_amount = float(amount_text)
                if new_amount <= 0:
                    raise ValueError
            except ValueError:
                self._set_status(f'Row "{tx.get("category")}": enter a valid positive amount.')
                return
            new_payment = widgets["payment"].currentText() if widgets["payment"] is not None else tx.get("payment_type")
            new_note = widgets["note"].text().strip()

            unchanged = (
                new_type == tx.get("type") and new_category == tx.get("category")
                and abs(new_amount - (tx.get("amount") or 0)) < 1e-9
                and new_payment == tx.get("payment_type") and new_note == (tx.get("note") or "")
            )
            if unchanged:
                continue

            date_val = tx.get("date")
            if date_val is None:
                month_num = MONTH_NAMES.index(tx["month"]) + 1
                date_val = Date(schema.year, month_num, 1)
            to_write.append((tx, date_val, new_type, new_category, new_amount, new_payment, new_note))

        if not to_write:
            self._set_status("No changes to save.", error=False)
            return

        saved = 0
        error_msg = None
        for tx, date_val, new_type, new_category, new_amount, new_payment, new_note in to_write:
            try:
                schema.update_transaction(tx, date_val, new_type, new_category, new_amount, new_payment, new_note)
                saved += 1
            except (TransactionNotFoundError, WorkbookLockedError) as exc:
                error_msg = str(exc)
                break

        # refresh() clears the status label on success, so set the outcome
        # message only after it runs — otherwise refresh would wipe it.
        self.refresh(self._year, self._month)
        if error_msg:
            self._set_status(f"Saved {saved} change(s), then stopped: {error_msg}" if saved else error_msg)
        else:
            self._set_status(f"Saved {saved} change(s).", error=False)

    def _selected_tx(self) -> dict | None:
        row = self._table.currentRow()
        if row < 0 or row >= len(self._filtered_txs):
            return None
        return self._filtered_txs[row]

    def _on_edit(self) -> None:
        tx = self._selected_tx()
        if tx is None or self._current_schema is None:
            return
        dlg = TransactionDialog(tx=tx, source_schema=self._current_schema, parent=self)
        if dlg.exec():
            self.refresh(self._year, self._month)

    def _on_delete(self) -> None:
        tx = self._selected_tx()
        if tx is None or self._current_schema is None:
            return
        label = tx.get("date").strftime("%Y-%m-%d") if tx.get("date") else tx.get("month", "")
        details = f"{label} — {tx.get('type')} / {tx.get('category')} — {fmt_amount(tx.get('amount') or 0)}"
        if tx.get("payment_type"):
            details += f" — {tx['payment_type']}"
        if tx.get("note"):
            details += f'\nNote: "{tx["note"]}"'
        reply = QMessageBox.question(
            self, "Delete transaction",
            f"Delete this transaction?\n\n{details}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        try:
            self._current_schema.delete_transaction(tx)
        except (TransactionNotFoundError, WorkbookLockedError) as exc:
            self._set_status(str(exc))
            return
        self.refresh(self._year, self._month)
