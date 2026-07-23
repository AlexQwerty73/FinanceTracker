"""
app/pages/review_page.py — ReviewPage: three lists worth a second look —
possible accidental double-entries and outlier amounts (core/duplicates.py,
heuristic) plus rows that fail outright (core/excel/transaction_validator.py:
bad date, non-numeric amount, a non-positive rate, or an unknown currency).
All-time/all-years, refreshed lazily only when the page becomes visible,
mirroring Currencies.

Duplicates are directly actionable here: each row's own "Delete" button
calls schema.delete_transaction() straight from this page — no detour
through TransactionsPage. All three lists support "dismiss" (an ignore-list,
core/settings.py's ignored_review_items) for flagged items that turn out
to be legitimate, so they stop resurfacing on every visit.
"""
from __future__ import annotations

from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QHBoxLayout, QLabel, QMessageBox, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from datetime import date as Date

from core import prefs, settings
from core.duplicates import DuplicateGroup, Outlier, detect_duplicates, detect_outliers
from core.excel import registry
from core.excel.base import MONTH_NAMES, TransactionNotFoundError
from core.excel.transaction_validator import InvalidRow, detect_invalid_rows
from core.excel.workbook_io import WorkbookLockedError
from core.format import fmt_amount
from core.themes import c, font_size

from ..components.widgets import card, scrollable_area, secondary_button


def _action_cell(*buttons) -> QWidget:
    cell = QWidget()
    cell.setStyleSheet("background:transparent;")
    lay = QHBoxLayout(cell)
    lay.setContentsMargins(4, 2, 4, 2)
    lay.setSpacing(6)
    for btn in buttons:
        lay.addWidget(btn)
    lay.addStretch()
    return cell


class ReviewPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._duplicate_groups: list[DuplicateGroup] = []
        self._outliers: list[Outlier] = []
        self._invalid_rows: list[InvalidRow] = []

        outer_lay = QVBoxLayout(self)
        outer_lay.setContentsMargins(0, 0, 0, 0)

        content = QWidget()
        content.setStyleSheet("background:transparent;")
        outer_lay.addWidget(scrollable_area(content))

        lay = QVBoxLayout(content)
        lay.setContentsMargins(4, 4, 4, 20)
        lay.setSpacing(16)

        hdr = QLabel("Review")
        hdr.setFont(QFont("Segoe UI", font_size("title"), QFont.Weight.Bold))
        hdr.setStyleSheet(f"color:{c('t1')}; background:transparent;")
        lay.addWidget(hdr)

        status_row = QHBoxLayout()
        self._status = QLabel("")
        self._status.setWordWrap(True)
        self._status.setStyleSheet(f"color:{c('err_c')}; background:transparent;")
        status_row.addWidget(self._status, 1)
        self._undo_btn = secondary_button("Undo delete")
        self._undo_btn.setVisible(False)
        self._undo_btn.clicked.connect(self._on_undo_delete)
        status_row.addWidget(self._undo_btn)
        lay.addLayout(status_row)

        # ── Possible duplicates ─────────────────────────────────────────
        dup_box, dup_lay = card("Possible duplicates")
        dup_helper = QLabel(
            "Same date, type, category, and amount entered more than once — often an accidental "
            "double-entry. Delete the extra one, or dismiss if these are genuinely separate purchases."
        )
        dup_helper.setWordWrap(True)
        dup_helper.setFont(QFont("Segoe UI", font_size("micro")))
        dup_helper.setStyleSheet(f"color:{c('t3')}; background:transparent;")
        dup_lay.addWidget(dup_helper)
        self._dup_empty_lbl = QLabel("Nothing found.")
        self._dup_empty_lbl.setStyleSheet(f"color:{c('t3')}; background:transparent;")
        dup_lay.addWidget(self._dup_empty_lbl)

        self._dup_table = QTableWidget(0, 7)
        self._dup_table.setHorizontalHeaderLabels(["Year", "When", "Type", "Category", "Amount", "Payment", ""])
        self._dup_table.verticalHeader().setVisible(False)
        self._dup_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._dup_table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self._dup_table.horizontalHeader().setStretchLastSection(True)
        for col, width in [(0, 60), (1, 100), (2, 90), (3, 130), (4, 100), (5, 90)]:
            self._dup_table.setColumnWidth(col, width)
        self._dup_table.setMinimumHeight(180)
        self._dup_table.setStyleSheet(self._table_style())
        dup_lay.addWidget(self._dup_table)
        lay.addWidget(dup_box)

        # ── Outliers ─────────────────────────────────────────────────────
        out_box, out_lay = card("Outliers")
        out_helper = QLabel(
            "Expenses far larger than usual for their category — not necessarily a mistake, just "
            "worth a second look."
        )
        out_helper.setWordWrap(True)
        out_helper.setFont(QFont("Segoe UI", font_size("micro")))
        out_helper.setStyleSheet(f"color:{c('t3')}; background:transparent;")
        out_lay.addWidget(out_helper)
        self._out_empty_lbl = QLabel("Nothing found.")
        self._out_empty_lbl.setStyleSheet(f"color:{c('t3')}; background:transparent;")
        out_lay.addWidget(self._out_empty_lbl)

        self._out_table = QTableWidget(0, 6)
        self._out_table.setHorizontalHeaderLabels(["Year", "Date", "Category", "Amount", "Typical for category", ""])
        self._out_table.verticalHeader().setVisible(False)
        self._out_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._out_table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self._out_table.horizontalHeader().setStretchLastSection(True)
        for col, width in [(0, 60), (1, 100), (2, 130), (3, 100), (4, 160)]:
            self._out_table.setColumnWidth(col, width)
        self._out_table.setMinimumHeight(180)
        self._out_table.setStyleSheet(self._table_style())
        out_lay.addWidget(self._out_table)
        lay.addWidget(out_box)

        # ── Data problems ───────────────────────────────────────────────
        bad_box, bad_lay = card("Data problems")
        bad_helper = QLabel(
            "A row whose date/amount/currency/rate doesn't hold up — the table is the database, "
            "so a mistake here means the app's totals are wrong too until it's fixed in Excel."
        )
        bad_helper.setWordWrap(True)
        bad_helper.setFont(QFont("Segoe UI", font_size("micro")))
        bad_helper.setStyleSheet(f"color:{c('t3')}; background:transparent;")
        bad_lay.addWidget(bad_helper)
        self._bad_empty_lbl = QLabel("Nothing found.")
        self._bad_empty_lbl.setStyleSheet(f"color:{c('t3')}; background:transparent;")
        bad_lay.addWidget(self._bad_empty_lbl)

        self._bad_table = QTableWidget(0, 5)
        self._bad_table.setHorizontalHeaderLabels(["Year", "When", "Category", "Problem", ""])
        self._bad_table.verticalHeader().setVisible(False)
        self._bad_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._bad_table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self._bad_table.horizontalHeader().setStretchLastSection(True)
        for col, width in [(0, 60), (1, 100), (2, 130), (3, 260)]:
            self._bad_table.setColumnWidth(col, width)
        self._bad_table.setMinimumHeight(180)
        self._bad_table.setStyleSheet(self._table_style())
        bad_lay.addWidget(self._bad_table)
        lay.addWidget(bad_box)

        ignored_box, ignored_lay = card("Dismissed")
        self._ignored_empty_lbl = QLabel("Nothing dismissed.")
        self._ignored_empty_lbl.setStyleSheet(f"color:{c('t3')}; background:transparent;")
        ignored_lay.addWidget(self._ignored_empty_lbl)
        self._ignored_list_lay = QVBoxLayout()
        self._ignored_list_lay.setSpacing(4)
        ignored_lay.addLayout(self._ignored_list_lay)
        lay.addWidget(ignored_box)

    @staticmethod
    def _table_style() -> str:
        return f"""
            QTableWidget {{ background:{c('panel_bg')}; color:{c('t1')}; border:1px solid {c('panel_bd')};
                border-radius:10px; gridline-color:{c('sep')}; }}
            QHeaderView::section {{ background:transparent; color:{c('t2')}; border:none;
                border-bottom:1px solid {c('sep')}; padding:6px; }}
            QTableWidget::item {{ padding:4px; }}
        """

    def _set_status(self, text: str) -> None:
        self._status.setText(text)

    def refresh(self) -> None:
        self._set_status("")
        ignored = set(settings.get_ignored_review_items())
        self._duplicate_groups = detect_duplicates(ignored)
        self._outliers = detect_outliers(ignored)
        self._invalid_rows = detect_invalid_rows(ignored)
        self._refresh_duplicates_table()
        self._refresh_outliers_table()
        self._refresh_invalid_rows_table()
        self._refresh_ignored_list()
        self._undo_btn.setVisible(prefs.has_last_deleted())

    def _refresh_duplicates_table(self) -> None:
        rows = [(group, tx) for group in self._duplicate_groups for tx in group.transactions]
        self._dup_empty_lbl.setVisible(len(rows) == 0)
        self._dup_table.setRowCount(len(rows))

        seen_signatures: set[str] = set()
        for row, (group, tx) in enumerate(rows):
            currency = tx.get("currency") or group.schema.get_base_currency()
            self._dup_table.setItem(row, 0, QTableWidgetItem(str(group.year)))
            self._dup_table.setItem(row, 1, QTableWidgetItem(group.period_label))
            self._dup_table.setItem(row, 2, QTableWidgetItem(group.type_ or ""))
            self._dup_table.setItem(row, 3, QTableWidgetItem(group.category))
            self._dup_table.setItem(row, 4, QTableWidgetItem(fmt_amount(tx.get("amount") or 0, currency)))
            self._dup_table.setItem(row, 5, QTableWidgetItem(tx.get("payment_type") or ""))

            delete_btn = secondary_button("Delete")
            delete_btn.clicked.connect(lambda _checked, g=group, t=tx: self._on_delete_duplicate(g, t))
            buttons = [delete_btn]
            if group.signature not in seen_signatures:
                seen_signatures.add(group.signature)
                dismiss_btn = secondary_button("Not a duplicate")
                dismiss_btn.clicked.connect(lambda _checked, sig=group.signature: self._on_dismiss(sig))
                buttons.append(dismiss_btn)
            self._dup_table.setCellWidget(row, 6, _action_cell(*buttons))

    def _refresh_outliers_table(self) -> None:
        self._out_empty_lbl.setVisible(len(self._outliers) == 0)
        self._out_table.setRowCount(len(self._outliers))
        for row, outlier in enumerate(self._outliers):
            tx = outlier.tx
            currency = tx.get("currency") or outlier.schema.get_base_currency()
            date_val = tx.get("date")
            date_str = date_val.strftime("%Y-%m-%d") if date_val else tx.get("month", "")
            self._out_table.setItem(row, 0, QTableWidgetItem(str(outlier.year)))
            self._out_table.setItem(row, 1, QTableWidgetItem(date_str))
            self._out_table.setItem(row, 2, QTableWidgetItem(outlier.category))
            self._out_table.setItem(row, 3, QTableWidgetItem(fmt_amount(tx.get("amount") or 0, currency)))
            # category_mean/category_stdev are computed in base currency (so a
            # multi-currency category's stats aren't skewed) -- format with
            # the schema's base currency, not this one transaction's own.
            typical = f"~{fmt_amount(outlier.category_mean, outlier.schema.get_base_currency())} avg"
            self._out_table.setItem(row, 4, QTableWidgetItem(typical))

            dismiss_btn = secondary_button("Dismiss")
            dismiss_btn.clicked.connect(lambda _checked, sig=outlier.signature: self._on_dismiss(sig))
            self._out_table.setCellWidget(row, 5, _action_cell(dismiss_btn))

    def _refresh_invalid_rows_table(self) -> None:
        self._bad_empty_lbl.setVisible(len(self._invalid_rows) == 0)
        self._bad_table.setRowCount(len(self._invalid_rows))
        for row, bad in enumerate(self._invalid_rows):
            date_val = bad.tx.get("date")
            when = date_val.strftime("%Y-%m-%d") if hasattr(date_val, "strftime") else (bad.tx.get("month") or "")
            self._bad_table.setItem(row, 0, QTableWidgetItem(str(bad.year)))
            self._bad_table.setItem(row, 1, QTableWidgetItem(when))
            self._bad_table.setItem(row, 2, QTableWidgetItem(bad.tx.get("category") or ""))
            self._bad_table.setItem(row, 3, QTableWidgetItem("; ".join(bad.problems)))
            dismiss_btn = secondary_button("Dismiss")
            dismiss_btn.clicked.connect(lambda _checked, sig=bad.signature: self._on_dismiss(sig))
            self._bad_table.setCellWidget(row, 4, _action_cell(dismiss_btn))

    def _on_delete_duplicate(self, group: DuplicateGroup, tx: dict) -> None:
        reply = QMessageBox.question(
            self, "Delete transaction",
            f"Delete this transaction?\n\n{group.period_label} — {group.type_} / {group.category} — "
            f"{fmt_amount(tx.get('amount') or 0, tx.get('currency') or group.schema.get_base_currency())}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        try:
            group.schema.delete_transaction(tx)
        except (TransactionNotFoundError, WorkbookLockedError) as exc:
            self._set_status(str(exc))
            return
        prefs.set_last_deleted({
            "year": group.schema.year, "month": tx.get("month"), "date": tx.get("date"),
            "type": tx.get("type"), "category": tx.get("category"), "amount": tx.get("amount"),
            "payment_type": tx.get("payment_type"), "note": tx.get("note") or "",
            "currency": tx.get("currency"), "rate": tx.get("rate"),
        })
        self.refresh()
        self._set_status("Deleted.")

    def _on_undo_delete(self) -> None:
        entry = prefs.pop_last_deleted()
        if entry is None:
            self._undo_btn.setVisible(False)
            return
        date_val = entry["date"]
        if date_val is None:
            month_num = MONTH_NAMES.index(entry["month"]) + 1
            date_val = Date(entry["year"], month_num, 1)
        try:
            schema = registry.get_schema_for_date(date_val)
            schema.add_transaction(
                date_val, entry["type"], entry["category"], entry["amount"], entry["payment_type"],
                entry["note"], entry["currency"], entry["rate"],
            )
        except (ValueError, WorkbookLockedError) as exc:
            self._set_status(str(exc))
            return
        self.refresh()
        self._set_status("Restored.")

    def _on_dismiss(self, signature: str) -> None:
        settings.set_review_item_ignored(signature, True)
        self.refresh()

    def _on_restore(self, signature: str) -> None:
        settings.set_review_item_ignored(signature, False)
        self.refresh()

    def _refresh_ignored_list(self) -> None:
        while self._ignored_list_lay.count():
            item = self._ignored_list_lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

        ignored_signatures = settings.get_ignored_review_items()
        self._ignored_empty_lbl.setVisible(len(ignored_signatures) == 0)
        for signature in ignored_signatures:
            row = QWidget()
            row.setStyleSheet("background:transparent;")
            row_lay = QHBoxLayout(row)
            row_lay.setContentsMargins(0, 2, 0, 2)
            label = QLabel(signature.replace("|", "  ·  "))
            label.setStyleSheet(f"color:{c('t2')}; background:transparent;")
            row_lay.addWidget(label, 1)
            restore_btn = secondary_button("Restore")
            restore_btn.clicked.connect(lambda _checked, sig=signature: self._on_restore(sig))
            row_lay.addWidget(restore_btn)
            self._ignored_list_lay.addWidget(row)
