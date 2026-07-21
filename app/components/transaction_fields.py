"""
app/components/transaction_fields.py — TransactionFields: the shared
date/type/category/amount/payment/notes inputs, used by both the add-form
(left panel) and the edit dialog. Owns dropdown reloading when the selected
date's year changes; owns no persistence or save button.
"""
from __future__ import annotations

from datetime import date as Date

from PyQt6.QtCore import QDate, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import QDateEdit, QLabel, QLineEdit, QVBoxLayout, QWidget

from core import prefs
from core.excel import registry
from core.themes import FIELD_HEIGHT, c, font_size, radius

from .widgets import NoWheelComboBox


def input_style() -> str:
    return f"""
        QLineEdit, QDateEdit, QComboBox {{
            background:{c('in_bg')}; border:1px solid {c('in_bd')};
            border-radius:{radius('md')}px; color:{c('t1')}; padding:0 10px;
        }}
        QLineEdit:focus, QDateEdit:focus, QComboBox:focus {{ border-color:{c('ac')}; }}
        QComboBox::drop-down {{ border:none; width:22px; }}
        QComboBox QAbstractItemView {{
            background:{c('bg')}; color:{c('t1')}; selection-background-color:{c('btn_bg')};
        }}
    """


def field_label(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setFont(QFont("Segoe UI", font_size("label")))
    lbl.setStyleSheet(f"color:{c('t2')}; background:transparent;")
    return lbl


class TransactionFields(QWidget):
    changed = pyqtSignal()  # date, currency, or amount changed -- for callers that show
                            # derived info (e.g. TransactionDialog's rate-conversion preview)

    def __init__(self, parent=None, remember_payment: bool = False):
        super().__init__(parent)
        self._loaded_year: int | None = None
        self._remember_payment = remember_payment
        self._has_payment_field = False
        self._has_currency_field = False

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)

        lay.addWidget(field_label("Date"))
        self._date = QDateEdit(QDate.currentDate())
        self._date.setCalendarPopup(True)
        self._date.setFixedHeight(FIELD_HEIGHT)
        self._date.setStyleSheet(input_style())
        self._date.dateChanged.connect(self._on_date_changed)
        self._date.dateChanged.connect(lambda _d: self.changed.emit())
        lay.addWidget(self._date)

        lay.addWidget(field_label("Type"))
        self._type_combo = NoWheelComboBox()
        self._type_combo.setFixedHeight(FIELD_HEIGHT)
        self._type_combo.setStyleSheet(input_style())
        lay.addWidget(self._type_combo)

        lay.addWidget(field_label("Category"))
        self._category_combo = NoWheelComboBox()
        self._category_combo.setFixedHeight(FIELD_HEIGHT)
        self._category_combo.setStyleSheet(input_style())
        lay.addWidget(self._category_combo)

        lay.addWidget(field_label("Amount"))
        self._amount_field = QLineEdit()
        self._amount_field.setPlaceholderText("0.00")
        self._amount_field.setFixedHeight(FIELD_HEIGHT)
        self._amount_field.setStyleSheet(input_style())
        lay.addWidget(self._amount_field)

        self._payment_label = field_label("Payment type")
        lay.addWidget(self._payment_label)
        self._payment_combo = NoWheelComboBox()
        self._payment_combo.setFixedHeight(FIELD_HEIGHT)
        self._payment_combo.setStyleSheet(input_style())
        lay.addWidget(self._payment_combo)

        self._currency_label = field_label("Currency")
        lay.addWidget(self._currency_label)
        self._currency_combo = NoWheelComboBox()
        self._currency_combo.setFixedHeight(FIELD_HEIGHT)
        self._currency_combo.setStyleSheet(input_style())
        lay.addWidget(self._currency_combo)

        lay.addWidget(field_label("Notes"))
        self._notes_field = QLineEdit()
        self._notes_field.setPlaceholderText("Optional note...")
        self._notes_field.setFixedHeight(FIELD_HEIGHT)
        self._notes_field.setStyleSheet(input_style())
        lay.addWidget(self._notes_field)

        self._currency_combo.currentTextChanged.connect(lambda _t: self.changed.emit())
        self._amount_field.textChanged.connect(lambda _t: self.changed.emit())

        self._on_date_changed(self._date.date())

    # ── year-driven dropdown reload ─────────────────────────────────────

    def _on_date_changed(self, qdate: QDate) -> None:
        year = qdate.year()
        if year == self._loaded_year:
            return
        try:
            schema = registry.get_schema_for_date(Date(year, 1, 1))
        except ValueError:
            self._type_combo.clear()
            self._category_combo.clear()
            self._payment_label.setVisible(False)
            self._payment_combo.setVisible(False)
            self._has_payment_field = False
            self._currency_label.setVisible(False)
            self._currency_combo.setVisible(False)
            self._has_currency_field = False
            self._loaded_year = None
            return

        self._type_combo.clear()
        self._type_combo.addItems(schema.get_types())
        self._category_combo.clear()
        self._category_combo.addItems(schema.get_categories())

        payment_types = schema.get_payment_types()
        has_payment = payment_types is not None
        self._has_payment_field = has_payment
        self._payment_label.setVisible(has_payment)
        self._payment_combo.setVisible(has_payment)
        if has_payment:
            self._payment_combo.clear()
            self._payment_combo.addItems(payment_types)
            last = prefs.get_last_payment_type(year) if self._remember_payment else None
            # Default to Card over whatever the list's own first entry is
            # (e.g. 2026's "Lists" sheet has Cash first) — Card is the more
            # common case, so it should be the default rather than Cash.
            preferred = last if last in payment_types else ("Card" if "Card" in payment_types else None)
            if preferred:
                self._payment_combo.setCurrentText(preferred)

        currencies = schema.get_currencies()
        has_currency = currencies is not None
        self._has_currency_field = has_currency
        self._currency_label.setVisible(has_currency)
        self._currency_combo.setVisible(has_currency)
        if has_currency:
            self._currency_combo.clear()
            self._currency_combo.addItems(currencies)
            last_currency = prefs.get_last_currency(year) if self._remember_payment else None
            base = schema.get_base_currency()
            preferred_currency = last_currency if last_currency in currencies else (
                base if base in currencies else None
            )
            if preferred_currency:
                self._currency_combo.setCurrentText(preferred_currency)

        self._loaded_year = year

    # ── getters ─────────────────────────────────────────────────────────

    def get_date(self) -> Date:
        q = self._date.date()
        return Date(q.year(), q.month(), q.day())

    def get_type(self) -> str:
        return self._type_combo.currentText()

    def get_category(self) -> str:
        return self._category_combo.currentText()

    def get_amount_text(self) -> str:
        return self._amount_field.text()

    def get_payment_type(self) -> str | None:
        return self._payment_combo.currentText() if self._has_payment_field else None

    def get_currency(self) -> str | None:
        return self._currency_combo.currentText() if self._has_currency_field else None

    def get_note(self) -> str:
        return self._notes_field.text().strip()

    # ── setters (pre-fill for editing) ──────────────────────────────────

    def set_date(self, year: int, month: int, day: int = 1) -> None:
        self._date.setDate(QDate(year, month, day))

    def set_values(self, tx: dict) -> None:
        """Pre-fill fields from a transaction dict (as returned by
        transactions_for_month). Call set_date() first if tx["date"] is None
        (2025 has no date column) so the year-dependent dropdowns load."""
        if tx.get("date") is not None:
            d = tx["date"]
            self.set_date(d.year, d.month, d.day)
        self._type_combo.setCurrentText(tx.get("type") or "")
        self._category_combo.setCurrentText(tx.get("category") or "")
        amount = tx.get("amount")
        if amount is not None:
            self._amount_field.setText(f"{amount:g}")
        payment_type = tx.get("payment_type")
        if payment_type and self._has_payment_field:
            self._payment_combo.setCurrentText(payment_type)
        currency = tx.get("currency")
        if currency and self._has_currency_field:
            self._currency_combo.setCurrentText(currency)
        self._notes_field.setText(tx.get("note") or "")

    def clear_amount_and_note(self) -> None:
        self._amount_field.clear()
        self._notes_field.clear()
