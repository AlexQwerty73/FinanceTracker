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
from PyQt6.QtWidgets import QDialog, QHBoxLayout, QLabel, QLineEdit, QVBoxLayout

from core import prefs, rate_history
from core.excel import registry
from core.excel.base import MONTH_NAMES, SheetFullError, TransactionNotFoundError
from core.excel.schema_dynamic import rate_from_amounts
from core.excel.workbook_io import WorkbookLockedError
from core.format import fmt_amount
from core.themes import FIELD_HEIGHT, c, font_size

from .rate_sync_worker import RateSyncWorker
from .transaction_fields import TransactionFields, field_label, input_style
from .widgets import primary_button, secondary_button

_RATE_EPSILON = 1e-6


def _parse_positive_float(text: str) -> float | None:
    try:
        value = float(text.strip().replace(",", "."))
    except ValueError:
        return None
    return value if value > 0 else None


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

        self._rate_sync: RateSyncWorker | None = None
        self._auto_rate: float | None = None
        self._auto_base: float | None = None
        self._syncing_rate_base = False  # reentrancy guard for the two-way rate<->base binding

        self._rate_label = field_label("Rate")
        self._rate_field = QLineEdit()
        self._rate_field.setPlaceholderText("e.g. official rate")
        self._rate_field.setFixedHeight(FIELD_HEIGHT)
        self._rate_field.setStyleSheet(input_style())
        self._rate_field.editingFinished.connect(self._on_rate_field_edited)
        self._base_label = field_label("Amount (base currency)")
        self._base_field = QLineEdit()
        self._base_field.setPlaceholderText("e.g. what your bank statement shows")
        self._base_field.setFixedHeight(FIELD_HEIGHT)
        self._base_field.setStyleSheet(input_style())
        self._base_field.editingFinished.connect(self._on_base_field_edited)
        lay.addWidget(self._rate_label)
        lay.addWidget(self._rate_field)
        lay.addWidget(self._base_label)
        lay.addWidget(self._base_field)

        refresh_row = QHBoxLayout()
        self._refresh_rate_btn = secondary_button("Refresh rate")
        self._refresh_rate_btn.clicked.connect(self._on_refresh_rate_clicked)
        refresh_row.addWidget(self._refresh_rate_btn)
        refresh_row.addStretch()
        lay.addLayout(refresh_row)

        self._rate_lbl = QLabel("")
        self._rate_lbl.setWordWrap(True)
        self._rate_lbl.setFont(QFont("Segoe UI", font_size("micro")))
        self._rate_lbl.setStyleSheet(f"color:{c('t3')}; background:transparent;")
        lay.addWidget(self._rate_lbl)
        self._fields.changed.connect(lambda: self._update_rate_info())
        self._update_rate_info(force=True)

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

    # ── rate/amount(base) preview + editing ──────────────────────────────

    def _rate_context(self):
        """(schema, currency, date, amount) for the currently-selected
        fields, or None if this date/currency combo has no currency
        tracking or is already in the base currency (nothing to convert).
        Income and Expense are treated identically -- both pin their rate
        to the transaction's own date."""
        date_ = self._fields.get_date()
        try:
            schema = registry.get_schema_for_date(date_)
        except ValueError:
            return None
        base = schema.get_base_currency()
        currency = self._fields.get_currency()
        if base is None or not currency or currency == base:
            return None
        try:
            amount = float(self._fields.get_amount_text().strip().replace(",", "."))
        except ValueError:
            amount = 0.0
        return schema, currency, date_, amount

    @staticmethod
    def _parse_rate(text: str) -> float | None:
        return _parse_positive_float(text)

    def _update_rate_info(self, force: bool = False) -> None:
        ctx = self._rate_context()
        if ctx is None:
            self._set_row_mode(visible=False)
            self._auto_rate = None
            self._auto_base = None
            return
        schema, currency, date_, amount = ctx

        self._set_row_mode(visible=True)
        # Editing an existing row that still has the same currency/date it
        # was saved with: show what's actually persisted on the row itself
        # (the table is the database), not a fresh cache/current-table
        # resolution that may have drifted since — e.g. a manually-priced
        # rate must keep showing as itself, not "correct" back to the
        # official rate just because the dialog reopened.
        if self._is_edit and self._tx.get("rate") is not None and currency == self._tx.get("currency") and date_ == (
            self._tx["date"].date() if hasattr(self._tx.get("date"), "date") else self._tx.get("date")
        ):
            new_auto_rate = self._tx["rate"]
        else:
            new_auto_rate = schema.resolve_rate(currency, date_)
        new_auto_base = amount * new_auto_rate if new_auto_rate is not None else None

        # Only overwrite a field if the user hasn't diverged it from the
        # last auto-filled value — an in-progress manual edit (e.g. typing
        # the bank's real rate or amount) shouldn't get silently reset just
        # because e.g. the Amount field also changed and re-triggered this.
        rate_text = self._rate_field.text().strip()
        rate_synced = force or rate_text == "" or (
            self._parse_rate(rate_text) is not None and self._auto_rate is not None
            and abs(self._parse_rate(rate_text) - self._auto_rate) < _RATE_EPSILON
        )
        if rate_synced:
            self._rate_field.setText(f"{new_auto_rate:g}" if new_auto_rate is not None else "")

        base_text = self._base_field.text().strip()
        base_synced = force or base_text == "" or (
            self._parse_rate(base_text) is not None and self._auto_base is not None
            and abs(self._parse_rate(base_text) - self._auto_base) < _RATE_EPSILON
        )
        if base_synced:
            self._base_field.setText(f"{new_auto_base:g}" if new_auto_base is not None else "")

        self._auto_rate = new_auto_rate
        self._auto_base = new_auto_base

        base_currency = schema.get_base_currency()
        if new_auto_rate is not None:
            cached = rate_history.get_rate(currency, date_)
            source = (
                f"historical rate for {date_.isoformat()}" if cached is not None
                else "current rate table (no historical rate cached for this date yet)"
            )
            self._rate_lbl.setText(f"≈ {fmt_amount(amount * new_auto_rate, base_currency)} — using the {source}.")
        else:
            self._rate_lbl.setText("No rate known for this date yet — enter one manually, or click Refresh rate.")

    def _set_row_mode(self, visible: bool) -> None:
        self._rate_label.setVisible(visible)
        self._rate_field.setVisible(visible)
        self._base_label.setVisible(visible)
        self._base_field.setVisible(visible)
        self._refresh_rate_btn.setVisible(visible)
        self._rate_lbl.setVisible(visible)

    def _on_rate_field_edited(self) -> None:
        if self._syncing_rate_base:
            return
        ctx = self._rate_context()
        if ctx is None:
            return
        _schema, _currency, _date, amount = ctx
        if amount <= 0:
            return
        rate = self._parse_rate(self._rate_field.text())
        if rate is None:
            return
        self._syncing_rate_base = True
        self._base_field.setText(f"{amount * rate:g}")
        self._syncing_rate_base = False

    def _on_base_field_edited(self) -> None:
        if self._syncing_rate_base:
            return
        ctx = self._rate_context()
        if ctx is None:
            return
        _schema, _currency, _date, amount = ctx
        if amount <= 0:
            return
        base_amount = self._parse_rate(self._base_field.text())
        if base_amount is None:
            return
        rate = rate_from_amounts(amount, base_amount)
        if rate is None:
            return
        self._syncing_rate_base = True
        self._rate_field.setText(f"{rate:g}")
        self._syncing_rate_base = False

    def _rate_override(self) -> float | None:
        """The effective rate to pass to add/update_transaction — None
        means "auto-resolve as usual". Only genuinely diverges from the
        last auto-resolved rate if the user actually edited the Rate or
        Amount(base currency) field (they stay mutually in sync, so
        comparing either against _auto_rate is equivalent)."""
        ctx = self._rate_context()
        if ctx is None:
            return None
        typed = self._parse_rate(self._rate_field.text())
        if typed is None:
            return None
        if self._auto_rate is not None and abs(typed - self._auto_rate) < _RATE_EPSILON:
            return None
        return typed

    def _on_refresh_rate_clicked(self) -> None:
        ctx = self._rate_context()
        if ctx is None or (self._rate_sync is not None and self._rate_sync.isRunning()):
            return
        _schema, currency, date_, _amount = ctx
        target_date = date_
        self._refresh_rate_btn.setEnabled(False)
        self._rate_lbl.setText("Fetching…")
        # Editing an existing transaction: force this exact row so an
        # explicit "refresh" click always wins for it, even if its Rate
        # cell was manually priced — clicking the button here is direct
        # intent to replace it, not an incidental day-wide update.
        force_rows = {self._tx["_row"]} if self._is_edit else None
        self._rate_sync = RateSyncWorker(self, targets={(currency, target_date)}, force_rows=force_rows)
        self._rate_sync.sync_finished.connect(self._on_rate_sync_finished)
        self._rate_sync.start()

    def _on_rate_sync_finished(self, _updated: int) -> None:
        self._refresh_rate_btn.setEnabled(True)
        # An explicit refresh always wins, even over an unsaved manual edit
        # sitting in the field — that's exactly what clicking the button
        # means: "go get me the real rate now."
        self._update_rate_info(force=True)

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
        rate = self._rate_override()

        try:
            if not self._is_edit:
                target_schema.add_transaction(new_date, type_, category, amount, payment_type, note, currency, rate)
            elif target_schema is self._source_schema:
                self._source_schema.update_transaction(
                    self._tx, new_date, type_, category, amount, payment_type, note, currency, rate
                )
            else:
                # Different year's file: add to the new one first, then remove
                # from the old one, so a failure here leaves a duplicate
                # rather than losing the transaction.
                target_schema.add_transaction(new_date, type_, category, amount, payment_type, note, currency, rate)
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
