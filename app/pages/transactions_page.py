"""
app/pages/transactions_page.py — TransactionsPage: the full, searchable,
editable transaction list for the viewed month. Every field commits
immediately on change (no "Save changes" button/batching) — see
_commit_row() for the single write path every field funnels through.
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
from core.excel.schema_dynamic import rate_from_amounts
from core.excel.workbook_io import WorkbookLockedError
from core.format import fmt_amount
from core.themes import c

from ..components.rate_sync_worker import RateSyncWorker
from ..components.transaction_dialog import TransactionDialog
from ..components.transaction_fields import input_style
from ..components.widgets import NoWheelComboBox

_BASE_COL = 5


def _parse_positive_float(text: str) -> float | None:
    try:
        value = float(text.strip().replace(",", "."))
    except ValueError:
        return None
    return value if value > 0 else None


class TransactionsPage(QWidget):
    analytics_clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._year = Date.today().year
        self._month = Date.today().month
        self._all_txs: list[dict] = []
        self._filtered_txs: list[dict] = []
        self._current_schema = None
        self._row_widgets: list[dict] = []  # per row: {"type","category","amount","currency","payment","note","base"}
        self._rate_sync: RateSyncWorker | None = None

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

        self._table = QTableWidget(0, 8)
        self._table.setHorizontalHeaderLabels(
            ["Date", "Type", "Category", "Amount", "Currency", "≈ Base", "Payment", "Note"]
        )
        self._table.verticalHeader().setVisible(False)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self._table.horizontalHeader().setStretchLastSection(True)
        for col, width in [(0, 90), (1, 130), (2, 170), (3, 100), (4, 70), (5, 100), (6, 90)]:
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
        self._refresh_rate_btn = QPushButton("Refresh rate")
        self._refresh_rate_btn.setFixedHeight(32)
        self._refresh_rate_btn.setToolTip(
            "Fetch the real exchange rate for the selected transaction's own date."
        )
        self._refresh_rate_btn.setStyleSheet(f"""
            QPushButton {{ background:transparent; color:{c('t2')};
                border:1px solid {c('in_bd')}; border-radius:6px; padding:0 16px; }}
            QPushButton:hover {{ color:{c('ac')}; border-color:{c('ac')}; }}
            QPushButton:disabled {{ color:{c('t3')}; border-color:{c('in_bd')}; }}
        """)
        self._refresh_rate_btn.clicked.connect(self._on_refresh_rate)
        self._delete_btn = QPushButton("Delete")
        self._delete_btn.setFixedHeight(32)
        self._delete_btn.setStyleSheet(f"""
            QPushButton {{ background:transparent; color:{c('t2')};
                border:1px solid {c('in_bd')}; border-radius:6px; padding:0 16px; }}
            QPushButton:hover {{ color:{c('err_c')}; border-color:{c('err_c')}; }}
        """)
        self._delete_btn.clicked.connect(self._on_delete)
        row_actions.addWidget(self._edit_btn)
        row_actions.addWidget(self._refresh_rate_btn)
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

    # ── rendering ────────────────────────────────────────────────────────

    def _render_table(self) -> None:
        schema = self._current_schema
        txs = self._filtered_txs
        self._row_widgets = []
        self._table.setRowCount(len(txs))

        types = schema.get_types() if schema is not None else []
        categories = schema.get_categories() if schema is not None else []
        payment_types = schema.get_payment_types() if schema is not None else None
        currencies = schema.get_currencies() if schema is not None else None

        for row, tx in enumerate(txs):
            date_val = tx.get("date")
            date_str = date_val.strftime("%Y-%m-%d") if date_val else tx.get("month", "")
            self._table.setItem(row, 0, QTableWidgetItem(date_str))

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

            currency_combo = None
            if currencies is not None:
                currency_combo = NoWheelComboBox()
                currency_combo.addItems(currencies)
                idx = currency_combo.findText(tx.get("currency") or "")
                if idx >= 0:
                    currency_combo.setCurrentIndex(idx)
                else:
                    base = schema.get_base_currency()
                    if base in currencies:
                        currency_combo.setCurrentText(base)
                currency_combo.setStyleSheet(input_style())
                self._table.setCellWidget(row, 4, currency_combo)
            else:
                self._table.setItem(row, 4, QTableWidgetItem(""))

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
                self._table.setCellWidget(row, 6, payment_combo)
            else:
                self._table.setItem(row, 6, QTableWidgetItem(""))

            note_field = QLineEdit(tx.get("note") or "")
            note_field.setStyleSheet(input_style())

            self._table.setCellWidget(row, 1, type_combo)
            self._table.setCellWidget(row, 2, category_combo)
            self._table.setCellWidget(row, 3, amount_field)
            self._table.setCellWidget(row, 7, note_field)

            self._row_widgets.append({
                "type": type_combo, "category": category_combo, "amount": amount_field,
                "currency": currency_combo, "payment": payment_combo, "note": note_field, "base": None,
            })
            self._render_base_cell(row)
            self._update_amount_color(row)

            # Connect change signals only after every field's initial value
            # is set, so pre-filling from the existing transaction doesn't
            # itself get flagged as an edit. Combos commit on selection;
            # text fields commit on editingFinished (Enter/focus-loss), not
            # every keystroke.
            type_combo.currentTextChanged.connect(lambda _t, r=row: self._on_type_changed(r))
            category_combo.currentTextChanged.connect(lambda _t, r=row: self._commit_row(r))
            amount_field.editingFinished.connect(lambda r=row: self._commit_row(r))
            note_field.editingFinished.connect(lambda r=row: self._commit_row(r))
            if currency_combo is not None:
                currency_combo.currentTextChanged.connect(lambda _t, r=row: self._on_currency_changed(r))
            if payment_combo is not None:
                payment_combo.currentTextChanged.connect(lambda _t, r=row: self._commit_row(r))

    def _render_base_cell(self, row: int) -> None:
        """(Re)build the "≈ Base" cell for `row` — an editable amount,
        two-way bound with Amount via the row's effective rate, for any
        foreign-currency row (Income and Expense alike, both pin their
        rate to the transaction's own date); blank for a base-currency
        row."""
        schema = self._current_schema
        tx = self._filtered_txs[row]
        widgets = self._row_widgets[row]
        type_text = widgets["type"].currentText()
        currency_text = widgets["currency"].currentText() if widgets["currency"] is not None else tx.get("currency")
        base_currency = schema.get_base_currency() if schema is not None else None

        # Tear down whatever's currently in that cell first -- this cell
        # switches between an editable widget and a plain item depending on
        # the row's currency, unlike the table's other conditional cells
        # (e.g. Currency/Payment) which are only ever set once.
        self._table.removeCellWidget(row, _BASE_COL)
        widgets["base"] = None

        if schema is None or not currency_text or currency_text == base_currency:
            self._table.takeItem(row, _BASE_COL)
            self._table.setItem(row, _BASE_COL, QTableWidgetItem(""))
            return

        matches_saved = type_text == tx.get("type") and currency_text == tx.get("currency")
        converted = schema.convert_transaction(tx) if matches_saved else None
        if converted is None:
            # Type/currency was changed live (not saved yet) -- estimate
            # with the best currently-known rate, same rule the save path
            # will use.
            amount = _parse_positive_float(widgets["amount"].text()) or 0.0
            converted = schema.to_base_amount(amount, currency_text, tx.get("date"))

        self._table.takeItem(row, _BASE_COL)
        base_field = QLineEdit(f"{converted:g}")
        base_field.setStyleSheet(input_style())
        base_field.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        base_field.setToolTip(
            "Edit this to the amount your bank actually charged/credited — the rate is derived "
            "from it and saved as a correction (banks often use a worse rate than official)."
        )
        base_field.editingFinished.connect(lambda r=row: self._commit_row(r, edited_base=True))
        self._table.setCellWidget(row, _BASE_COL, base_field)
        widgets["base"] = base_field

    def _update_amount_color(self, row: int) -> None:
        schema = self._current_schema
        amount_field = self._row_widgets[row]["amount"]
        type_text = self._row_widgets[row]["type"].currentText()
        is_expense = schema is not None and schema.is_expense_type(type_text)
        color = c("expense_c") if is_expense else c("income_c")
        amount_field.setStyleSheet(input_style() + f"QLineEdit {{ color:{color}; font-weight:bold; }}")

    # ── live autosave ────────────────────────────────────────────────────

    def _on_type_changed(self, row: int) -> None:
        self._update_amount_color(row)
        self._render_base_cell(row)  # ≈Base's converted estimate depends on the row's type/rate too
        self._commit_row(row)

    def _on_currency_changed(self, row: int) -> None:
        self._render_base_cell(row)  # a new currency means a fresh rate, not the old one carried over
        self._commit_row(row)

    def _commit_row(self, row: int, edited_base: bool = False) -> None:
        schema = self._current_schema
        if schema is None or row >= len(self._filtered_txs):
            return
        tx = self._filtered_txs[row]
        widgets = self._row_widgets[row]

        new_type = widgets["type"].currentText()
        new_category = widgets["category"].currentText()
        new_amount = _parse_positive_float(widgets["amount"].text())
        if new_amount is None:
            widgets["amount"].setText(f"{tx.get('amount') or 0:g}")
            self._set_status(f'Row "{tx.get("category")}": enter a valid positive amount.')
            return
        new_payment = widgets["payment"].currentText() if widgets["payment"] is not None else tx.get("payment_type")
        new_currency = widgets["currency"].currentText() if widgets["currency"] is not None else tx.get("currency")
        new_note = widgets["note"].text().strip()

        rate_override = None
        if edited_base and widgets["base"] is not None:
            new_base = _parse_positive_float(widgets["base"].text())
            if new_base is None:
                self._render_base_cell(row)  # revert to the last good value
                self._set_status(f'Row "{tx.get("category")}": enter a valid positive amount for ≈ Base.')
                return
            rate_override = rate_from_amounts(new_amount, new_base)

        unchanged = (
            not edited_base
            and new_type == tx.get("type") and new_category == tx.get("category")
            and abs(new_amount - (tx.get("amount") or 0)) < 1e-9
            and new_payment == tx.get("payment_type") and new_currency == tx.get("currency")
            and new_note == (tx.get("note") or "")
        )
        if unchanged:
            return

        date_val = tx.get("date")
        if date_val is None:
            month_num = MONTH_NAMES.index(tx["month"]) + 1
            date_val = Date(schema.year, month_num, 1)

        try:
            schema.update_transaction(
                tx, date_val, new_type, new_category, new_amount, new_payment, new_note, new_currency, rate_override
            )
        except (TransactionNotFoundError, WorkbookLockedError) as exc:
            self._set_status(str(exc))
            return

        # Re-read this exact row fresh from the workbook (rather than
        # hand-computing what changed) so the in-memory tx dict — and
        # anything derived from it, like the ≈Base preview — always
        # matches what's actually on disk. tx is mutated in place (not
        # replaced) so _all_txs, which shares the same dict objects with
        # _filtered_txs, stays in sync too.
        refreshed = schema.transactions_for_month(self._month)
        updated_tx = next((t for t in refreshed if t["_row"] == tx["_row"]), None)
        if updated_tx is not None:
            tx.clear()
            tx.update(updated_tx)
        self._render_base_cell(row)
        self._update_amount_color(row)
        self._set_status("Saved.", error=False)

    # ── row actions ──────────────────────────────────────────────────────

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

    def _on_refresh_rate(self) -> None:
        if self._rate_sync is not None and self._rate_sync.isRunning():
            return
        tx = self._selected_tx()
        schema = self._current_schema
        if tx is None or schema is None:
            self._set_status("Select a transaction first.")
            return
        currency = tx.get("currency")
        base = schema.get_base_currency()
        if not currency or base is None or currency == base:
            self._set_status("The selected transaction has no foreign currency to refresh a rate for.")
            return

        target_date = tx.get("date")
        if target_date is not None and hasattr(target_date, "date"):
            target_date = target_date.date()
        if target_date is None:
            self._set_status("This transaction has no date to refresh a rate for.")
            return

        self._refresh_rate_btn.setEnabled(False)
        self._set_status("Fetching…", error=False)
        self._rate_sync = RateSyncWorker(self, targets={(currency, target_date)})
        self._rate_sync.sync_finished.connect(self._on_rate_sync_finished)
        self._rate_sync.start()

    def _on_rate_sync_finished(self, updated: int) -> None:
        self._refresh_rate_btn.setEnabled(True)
        # refresh() clears the status label (same gotcha as _commit_row's
        # own save-status message) -- set the outcome message only after.
        self.refresh(self._year, self._month)
        self._set_status(
            "Rate updated." if updated else "No rate found (offline, or not published for that date).",
            error=not updated,
        )

    def _on_delete(self) -> None:
        tx = self._selected_tx()
        if tx is None or self._current_schema is None:
            return
        label = tx.get("date").strftime("%Y-%m-%d") if tx.get("date") else tx.get("month", "")
        tx_currency = tx.get("currency") or self._current_schema.get_base_currency()
        details = f"{label} — {tx.get('type')} / {tx.get('category')} — {fmt_amount(tx.get('amount') or 0, tx_currency)}"
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
