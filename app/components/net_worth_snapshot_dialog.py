"""
app/components/net_worth_snapshot_dialog.py — TakeSnapshotDialog (enter
today's real Cash/Card for every currency at once; on save, computes and
permanently freezes the historical ledger via core.net_worth_ledger) and
ManageSnapshotsDialog (browse every past snapshot, pick which one is
active, or delete one) for CurrenciesPage's net worth block.
"""
from __future__ import annotations

from datetime import date as Date, datetime

from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QDialog, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QVBoxLayout, QWidget,
)

from core import settings
from core.net_worth_ledger import compute_full_ledger
from core.themes import c, font_size

from .transaction_fields import input_style
from .widgets import primary_button, secondary_button


def _parse_amount(text: str) -> float:
    try:
        return float(text.strip().replace(",", "."))
    except ValueError:
        return 0.0


class TakeSnapshotDialog(QDialog):
    """One Cash/Card row per currency, always dated today — a snapshot is
    "what I have right now", not a backdated entry. Save computes and
    stores the full historical ledger (opening + balance at every past
    month) in one shot; nothing here is editable after the fact — take a
    new snapshot instead (see ManageSnapshotsDialog)."""

    def __init__(self, currencies: list[str], all_txs, parent=None):
        super().__init__(parent)
        self._currencies = currencies
        self._all_txs = all_txs
        self._fields: dict[str, tuple[QLineEdit, QLineEdit]] = {}

        self.setWindowTitle("Take snapshot")
        self.setStyleSheet(f"QDialog {{ background:{c('bg')}; }}")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 20, 20, 20)
        lay.setSpacing(10)

        hdr = QLabel("Take snapshot")
        hdr.setFont(QFont("Segoe UI", font_size("dialog"), QFont.Weight.Bold))
        hdr.setStyleSheet(f"color:{c('t1')}; background:transparent;")
        lay.addWidget(hdr)

        date_lbl = QLabel(f"How much you have right now — as of today, {Date.today().isoformat()}")
        date_lbl.setWordWrap(True)
        date_lbl.setStyleSheet(f"color:{c('t3')}; background:transparent;")
        lay.addWidget(date_lbl)

        grid = QGridLayout()
        grid.setSpacing(8)
        for col, h in enumerate(["Currency", "Cash", "Card"]):
            lbl = QLabel(h)
            lbl.setFont(QFont("Segoe UI", font_size("label"), QFont.Weight.Bold))
            lbl.setStyleSheet(f"color:{c('t2')}; background:transparent;")
            grid.addWidget(lbl, 0, col)
        for row, currency in enumerate(currencies, start=1):
            name_lbl = QLabel(currency)
            name_lbl.setStyleSheet(f"color:{c('t1')}; background:transparent; font-weight:bold;")
            grid.addWidget(name_lbl, row, 0)
            cash_field = QLineEdit("0")
            cash_field.setFixedWidth(100)
            cash_field.setStyleSheet(input_style())
            card_field = QLineEdit("0")
            card_field.setFixedWidth(100)
            card_field.setStyleSheet(input_style())
            grid.addWidget(cash_field, row, 1)
            grid.addWidget(card_field, row, 2)
            self._fields[currency] = (cash_field, card_field)
        lay.addLayout(grid)

        btn_row = QHBoxLayout()
        cancel_btn = secondary_button("Cancel")
        cancel_btn.clicked.connect(self.reject)
        save_btn = primary_button("Save")
        save_btn.clicked.connect(self._on_save)
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(save_btn)
        lay.addLayout(btn_row)

    def _on_save(self) -> None:
        balances = {
            currency: {"cash": _parse_amount(cash_field.text()), "card": _parse_amount(card_field.text())}
            for currency, (cash_field, card_field) in self._fields.items()
        }
        today = Date.today()
        opening, monthly_history = compute_full_ledger(self._all_txs, self._currencies, today, balances)
        settings.add_net_worth_snapshot(today.isoformat(), datetime.now().isoformat(), balances, opening, monthly_history)
        self.accept()


class ManageSnapshotsDialog(QDialog):
    """Every stored snapshot, newest first — "Use" makes it the active
    one (the one the page-wide "Use snapshot" checkbox applies), "Delete"
    removes it outright (confirmed). Deleting the active one clears the
    active pointer — nothing silently becomes active in its place."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Manage snapshots")
        self.setFixedWidth(440)
        self.setStyleSheet(f"QDialog {{ background:{c('bg')}; }}")

        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 20, 20, 20)
        lay.setSpacing(10)

        hdr = QLabel("Manage snapshots")
        hdr.setFont(QFont("Segoe UI", font_size("dialog"), QFont.Weight.Bold))
        hdr.setStyleSheet(f"color:{c('t1')}; background:transparent;")
        lay.addWidget(hdr)

        self._rows_lay = QVBoxLayout()
        self._rows_lay.setSpacing(6)
        lay.addLayout(self._rows_lay)
        self._row_widgets: list[QWidget] = []

        close_btn = primary_button("Close")
        close_btn.clicked.connect(self.accept)
        lay.addWidget(close_btn)

        self._refresh_rows()

    def _refresh_rows(self) -> None:
        for w in self._row_widgets:
            self._rows_lay.removeWidget(w)
            w.deleteLater()
        self._row_widgets.clear()

        snapshots = settings.get_net_worth_snapshots()
        active_id = settings.get_active_net_worth_snapshot_id()
        if not snapshots:
            empty_lbl = QLabel("No snapshots yet — take one from the Currencies page first.")
            empty_lbl.setWordWrap(True)
            empty_lbl.setStyleSheet(f"color:{c('t3')}; background:transparent;")
            self._rows_lay.addWidget(empty_lbl)
            self._row_widgets.append(empty_lbl)
            return

        for snap in snapshots:
            is_active = snap["id"] == active_id
            row = QWidget()
            row.setStyleSheet("background:transparent;")
            row_lay = QHBoxLayout(row)
            row_lay.setContentsMargins(0, 0, 0, 0)

            taken = snap["taken_at"][:16].replace("T", " ")
            label_text = f"{snap['date']} (taken {taken})" + ("  — active" if is_active else "")
            lbl = QLabel(label_text)
            weight = "font-weight:bold;" if is_active else ""
            lbl.setStyleSheet(f"color:{c('ac') if is_active else c('t1')}; background:transparent; {weight}")
            row_lay.addWidget(lbl, 1)

            use_btn = secondary_button("Use")
            use_btn.setFixedHeight(26)
            use_btn.setEnabled(not is_active)
            use_btn.clicked.connect(lambda _c=False, sid=snap["id"]: self._on_use(sid))
            row_lay.addWidget(use_btn)

            delete_btn = secondary_button("Delete")
            delete_btn.setFixedHeight(26)
            delete_btn.clicked.connect(lambda _c=False, sid=snap["id"]: self._on_delete(sid))
            row_lay.addWidget(delete_btn)

            self._rows_lay.addWidget(row)
            self._row_widgets.append(row)

    def _on_use(self, snapshot_id: str) -> None:
        settings.set_active_net_worth_snapshot_id(snapshot_id)
        self._refresh_rows()

    def _on_delete(self, snapshot_id: str) -> None:
        reply = QMessageBox.question(self, "Delete snapshot?", "Delete this snapshot? This can't be undone.")
        if reply != QMessageBox.StandardButton.Yes:
            return
        settings.delete_net_worth_snapshot(snapshot_id)
        self._refresh_rows()
