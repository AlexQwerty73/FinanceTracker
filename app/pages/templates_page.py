"""
app/pages/templates_page.py — TemplatesPage: build a custom workbook
Template with a live, Excel-style table preview of the columns as you
edit them — a full page (not a modal) so it's a comfortable place to
experiment, reachable any time from the sidebar. Saved templates then show
up in the Settings dialog's "Create New File" tab's layout picker.

Interaction design is deliberately "direct manipulation" rather than
select-then-click-a-button: columns are added by clicking a "+ Date" style
pill and removed by clicking an inline ✕ next to that exact row; the
required Category/Type/Amount columns are visibly locked (no ✕, a
"required" tag) so it's obvious at a glance why they can't be dragged out.
Types combine the list and the Income/Expense/Cash-in role assignment into
one row each (a per-row role dropdown) instead of a separate list plus
three "which one is X" combos elsewhere on the page — picking "Income" for
one row automatically un-picks it from whichever row had it before, so
there's never a way to end up with two "Income" types by accident.

The preview shows the *whole picture*, not just an echo of the fields you
can edit: alongside the sample rows it shows the row of month tabs every
layout repeats across, and a totals strip (Income/Expense/Balance/Invest/
Cash/Card) computed the same way DynamicSchema.month_summary() computes it
for a real file — including the fact that cash tracking only kicks in for
expenses paid with a payment option literally named "Cash", which is
otherwise an easy thing to miss.

Investing is tracked the same way Schema2025/Schema2026 track it: a fixed
set of categories (e.g. Crypto, Stocks) counts toward "Invest" on the
Dashboard regardless of whether the transaction was typed as Income or
Expense. The Investments card lets you check which of your categories
those are — it stays in sync with the Categories list automatically (a
removed category disappears from the checklist too).

Always saves as a NEW template (never mutates one in place), even when
"Start from" loads an existing one's values as a starting point — editing
an in-use template's structure would silently corrupt any file already
created from it (DynamicSchema reads column positions from the template
fresh every time), and applying template changes to existing files is
explicitly out of scope for now (see project notes on the create-file-
from-template feature).
"""
from __future__ import annotations

from PyQt6.QtCore import QSize, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QCursor, QFont
from PyQt6.QtWidgets import (
    QAbstractItemView, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QPushButton, QSizePolicy, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)

from core.excel import template_model
from core.excel.template_model import (
    OPTIONAL_ROLES, REQUIRED_ROLES, ROLE_AMOUNT, ROLE_CATEGORY, ROLE_CURRENCY, ROLE_DATE,
    ROLE_LABELS, ROLE_NOTES, ROLE_PAYMENT, ROLE_TYPE, Template, TemplateValidationError,
)
from core.icons import icon
from core.themes import FIELD_HEIGHT, c, font_size, radius

from ..components.transaction_fields import field_label, input_style
from ..components.widgets import (
    NoWheelComboBox, bordered_box, card as _base_card, primary_button, scrollable_area,
)

_PREVIEW_ROWS = 4
_START_BLANK = "__blank__"
_MONTH_TABS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

_ROLE_NONE = "(no special meaning)"
_ROLE_INCOME = "Income"
_ROLE_EXPENSE = "Expense"
_ROLE_CASH_IN = "Cash-in transfer"
_TYPE_ROLE_OPTIONS = [_ROLE_NONE, _ROLE_INCOME, _ROLE_EXPENSE, _ROLE_CASH_IN]


def _helper_text(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setWordWrap(True)
    lbl.setFont(QFont("Segoe UI", font_size("micro")))
    lbl.setStyleSheet(f"color:{c('t3')}; background:transparent;")
    return lbl


def _card(title: str, helper: str | None = None) -> tuple[QWidget, QVBoxLayout]:
    box, lay = _base_card(title)
    if helper:
        lay.addWidget(_helper_text(helper))
    return box, lay


def _small_btn(text: str) -> QPushButton:
    btn = QPushButton(text)
    btn.setFixedHeight(30)
    btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
    btn.setStyleSheet(f"""
        QPushButton {{ background:transparent; color:{c('t2')};
            border:1px solid {c('in_bd')}; border-radius:{radius('sm')}px; padding:0 10px; }}
        QPushButton:hover {{ color:{c('t1')}; border-color:{c('t2')}; }}
        QPushButton:disabled {{ color:{c('t3')}; border-color:{c('sep')}; }}
    """)
    return btn


def _pill_btn(text: str) -> QPushButton:
    """A dashed '+ Date'-style button — click to add, no dropdown involved."""
    btn = QPushButton(text)
    btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
    btn.setFixedHeight(26)
    btn.setStyleSheet(f"""
        QPushButton {{ background:{c('in_bg')}; color:{c('ac')};
            border:1px dashed {c('in_bd')}; border-radius:13px; padding:0 12px; }}
        QPushButton:hover {{ background:{c('btn_bg')}; border-color:{c('btn_bd')}; }}
    """)
    return btn


def _remove_btn(tooltip: str = "Remove") -> QPushButton:
    btn = QPushButton()
    btn.setIcon(icon("close", c("t3")))
    btn.setIconSize(QSize(12, 12))
    btn.setFixedSize(22, 22)
    btn.setToolTip(tooltip)
    btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
    btn.setStyleSheet(f"""
        QPushButton {{ background:transparent; border:none; border-radius:{radius('sm') - 1}px; }}
        QPushButton:hover {{ background:{c('err_c')}; }}
    """)
    return btn


def _stat_chip() -> tuple[QWidget, QLabel, QLabel]:
    """A small 'Income / 1 500.00'-style readout used in the totals strip."""
    box = bordered_box(c("in_bg"), c("in_bd"), radius=radius("lg"))
    lay = QVBoxLayout(box)
    lay.setContentsMargins(10, 6, 10, 6)
    lay.setSpacing(2)
    title_lbl = QLabel("")
    title_lbl.setFont(QFont("Segoe UI", font_size("micro")))
    title_lbl.setStyleSheet(f"color:{c('t3')}; background:transparent;")
    value_lbl = QLabel("0.00")
    value_lbl.setFont(QFont("Segoe UI", font_size("stat"), QFont.Weight.Bold))
    value_lbl.setStyleSheet(f"color:{c('t1')}; background:transparent;")
    lay.addWidget(title_lbl)
    lay.addWidget(value_lbl)
    return box, title_lbl, value_lbl


class _ListEditor(QWidget):
    """A tag-list editor: type a value, hit Add/Enter, or click the ✕ next
    to any row to remove it directly — no select-then-click-Remove step.
    Used for Categories and Payment types."""

    changed = pyqtSignal()

    def __init__(self, placeholder: str, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)

        self.list_widget = QListWidget()
        self.list_widget.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.list_widget.setFixedHeight(96)
        self.list_widget.setSpacing(2)
        self.list_widget.setStyleSheet(f"""
            QListWidget {{ background:{c('in_bg')}; border:1px solid {c('in_bd')}; border-radius:8px; }}
            QListWidget::item {{ border:none; }}
        """)
        lay.addWidget(self.list_widget)

        row = QHBoxLayout()
        self._input = QLineEdit()
        self._input.setPlaceholderText(placeholder)
        self._input.setFixedHeight(30)
        self._input.setStyleSheet(input_style())
        self._input.returnPressed.connect(self._on_add)
        add_btn = _small_btn("+ Add")
        add_btn.clicked.connect(self._on_add)
        row.addWidget(self._input, 1)
        row.addWidget(add_btn)
        lay.addLayout(row)

    def _row_widget(self, text: str) -> QWidget:
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(8, 0, 4, 0)
        h.setSpacing(6)
        lbl = QLabel(text)
        lbl.setStyleSheet(f"color:{c('t1')}; background:transparent;")
        h.addWidget(lbl, 1)
        rm = _remove_btn(f'Remove "{text}"')
        rm.clicked.connect(lambda: self._remove(text))
        h.addWidget(rm)
        return w

    def _add_item(self, text: str) -> None:
        item = QListWidgetItem()
        item.setData(Qt.ItemDataRole.UserRole, text)
        item.setSizeHint(QSize(0, 28))
        self.list_widget.addItem(item)
        self.list_widget.setItemWidget(item, self._row_widget(text))

    def _remove(self, text: str) -> None:
        for i in range(self.list_widget.count()):
            if self.list_widget.item(i).data(Qt.ItemDataRole.UserRole) == text:
                self.list_widget.takeItem(i)
                break
        self.changed.emit()

    def _on_add(self) -> None:
        text = self._input.text().strip()
        if not text or text in self.values():
            self._input.clear()
            return
        self._add_item(text)
        self._input.clear()
        self.changed.emit()

    def values(self) -> list[str]:
        return [self.list_widget.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.list_widget.count())]

    def set_values(self, values: list[str]) -> None:
        self.list_widget.clear()
        for v in values:
            self._add_item(v)
        self.changed.emit()


class _TypesEditor(QWidget):
    """Types and their Income/Expense/Cash-in role live in one place: each
    row is a name plus a role dropdown, instead of a separate type list and
    three "which type means X" combos elsewhere on the page. Picking a role
    that's already taken automatically clears it from whichever row had it,
    so Income/Expense/Cash-in can never point at two rows at once. The
    first type added is auto-assigned Income, the second Expense, since
    that's what almost everyone wants for their first two entries."""

    changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows: list[dict] = []

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)

        self.list_widget = QListWidget()
        self.list_widget.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.list_widget.setFixedHeight(150)
        self.list_widget.setSpacing(2)
        self.list_widget.setStyleSheet(f"""
            QListWidget {{ background:{c('in_bg')}; border:1px solid {c('in_bd')}; border-radius:8px; }}
            QListWidget::item {{ border:none; }}
        """)
        lay.addWidget(self.list_widget)

        row = QHBoxLayout()
        self._input = QLineEdit()
        self._input.setPlaceholderText("New type, e.g. Income, Expense, Savings…")
        self._input.setFixedHeight(30)
        self._input.setStyleSheet(input_style())
        self._input.returnPressed.connect(self._on_add)
        add_btn = _small_btn("+ Add type")
        add_btn.clicked.connect(self._on_add)
        row.addWidget(self._input, 1)
        row.addWidget(add_btn)
        lay.addLayout(row)

    def _row_widget(self, name: str, role: str) -> QWidget:
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(8, 0, 4, 0)
        h.setSpacing(6)
        lbl = QLabel(name)
        if role == _ROLE_INCOME:
            lbl.setStyleSheet(f"color:{c('income_c')}; background:transparent; font-weight:bold;")
        elif role == _ROLE_EXPENSE:
            lbl.setStyleSheet(f"color:{c('expense_c')}; background:transparent; font-weight:bold;")
        else:
            lbl.setStyleSheet(f"color:{c('t1')}; background:transparent;")
        h.addWidget(lbl, 1)

        combo = NoWheelComboBox()
        combo.addItems(_TYPE_ROLE_OPTIONS)
        combo.setCurrentText(role)
        combo.setFixedHeight(26)
        combo.setFixedWidth(160)
        combo.setStyleSheet(input_style())
        combo.setToolTip("What this type means for Dashboard totals.")
        combo.currentTextChanged.connect(lambda new_role, n=name: self._set_role(n, new_role))
        h.addWidget(combo)

        rm = _remove_btn(f'Remove "{name}"')
        rm.clicked.connect(lambda _checked=False, n=name: self._remove(n))
        h.addWidget(rm)
        return w

    def _rebuild(self) -> None:
        self.list_widget.clear()
        for r in self._rows:
            item = QListWidgetItem()
            item.setSizeHint(QSize(0, 32))
            self.list_widget.addItem(item)
            self.list_widget.setItemWidget(item, self._row_widget(r["name"], r["role"]))

    def _on_add(self) -> None:
        text = self._input.text().strip()
        if not text or any(r["name"] == text for r in self._rows):
            self._input.clear()
            return
        role = _ROLE_NONE
        if not any(r["role"] == _ROLE_INCOME for r in self._rows):
            role = _ROLE_INCOME
        elif not any(r["role"] == _ROLE_EXPENSE for r in self._rows):
            role = _ROLE_EXPENSE
        self._rows.append({"name": text, "role": role})
        self._input.clear()
        self._rebuild()
        self.changed.emit()

    def _remove(self, name: str) -> None:
        self._rows = [r for r in self._rows if r["name"] != name]
        self._rebuild()
        self.changed.emit()

    def _set_role(self, name: str, role: str) -> None:
        if role in (_ROLE_INCOME, _ROLE_EXPENSE, _ROLE_CASH_IN):
            for r in self._rows:
                if r["name"] != name and r["role"] == role:
                    r["role"] = _ROLE_NONE
        for r in self._rows:
            if r["name"] == name:
                r["role"] = role
        self._rebuild()
        self.changed.emit()

    def types(self) -> list[str]:
        return [r["name"] for r in self._rows]

    def income_type(self) -> str | None:
        return next((r["name"] for r in self._rows if r["role"] == _ROLE_INCOME), None)

    def expense_type(self) -> str | None:
        return next((r["name"] for r in self._rows if r["role"] == _ROLE_EXPENSE), None)

    def cash_in_type(self) -> str | None:
        return next((r["name"] for r in self._rows if r["role"] == _ROLE_CASH_IN), None)

    def set_from(self, types: list[str], income: str, expense: str, cash_in: str | None) -> None:
        self._rows = []
        for t in types:
            if t == income:
                role = _ROLE_INCOME
            elif t == expense:
                role = _ROLE_EXPENSE
            elif cash_in and t == cash_in:
                role = _ROLE_CASH_IN
            else:
                role = _ROLE_NONE
            self._rows.append({"name": t, "role": role})
        self._rebuild()


class _InvestCategoriesEditor(QWidget):
    """A checklist of the current Categories — tick the ones that count as
    investing (e.g. Crypto, Stocks). Always mirrors whatever's in the
    Categories card: call refresh_categories() whenever that list changes
    and a removed category quietly drops off here too, so this can never
    point at a category that no longer exists."""

    changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._checked: set[str] = set()
        self._categories: list[str] = []

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)

        self.list_widget = QListWidget()
        self.list_widget.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.list_widget.setFixedHeight(84)
        self.list_widget.setSpacing(2)
        self.list_widget.setStyleSheet(f"""
            QListWidget {{ background:{c('in_bg')}; border:1px solid {c('in_bd')}; border-radius:8px; }}
            QListWidget::item {{ border:none; padding:2px 6px; }}
        """)
        self.list_widget.itemChanged.connect(self._on_item_changed)
        lay.addWidget(self.list_widget)

        self._empty_hint = _helper_text("Add a category above first, then check it off here if it's investing.")
        lay.addWidget(self._empty_hint)

    def _on_item_changed(self, item: QListWidgetItem) -> None:
        name = item.data(Qt.ItemDataRole.UserRole)
        if item.checkState() == Qt.CheckState.Checked:
            self._checked.add(name)
        else:
            self._checked.discard(name)
        self.changed.emit()

    def refresh_categories(self, categories: list[str]) -> None:
        self._categories = list(categories)
        self._checked &= set(categories)
        self.list_widget.blockSignals(True)
        self.list_widget.clear()
        for cat in categories:
            item = QListWidgetItem(cat)
            item.setData(Qt.ItemDataRole.UserRole, cat)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if cat in self._checked else Qt.CheckState.Unchecked)
            self.list_widget.addItem(item)
        self.list_widget.blockSignals(False)
        self.list_widget.setVisible(bool(categories))
        self._empty_hint.setVisible(not categories)

    def values(self) -> list[str]:
        return [cat for cat in self._categories if cat in self._checked]

    def set_checked(self, checked: list[str]) -> None:
        self._checked = set(checked)


class TemplatesPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)

        outer_lay = QVBoxLayout(self)
        outer_lay.setContentsMargins(0, 0, 0, 0)

        content = QWidget()
        content.setStyleSheet("background:transparent;")
        outer_lay.addWidget(scrollable_area(content))

        lay = QVBoxLayout(content)
        lay.setContentsMargins(4, 4, 4, 20)
        lay.setSpacing(16)

        header_row = QHBoxLayout()
        hdr = QLabel("Templates")
        hdr.setFont(QFont("Segoe UI", font_size("title"), QFont.Weight.Bold))
        hdr.setStyleSheet(f"color:{c('t1')}; background:transparent;")
        header_row.addWidget(hdr)
        header_row.addStretch()
        lay.addLayout(header_row)

        desc = QLabel(
            "Design a workbook layout — which columns, in what order — and see it update live on the right. "
            "Saved templates show up as a layout choice when creating a new finances file."
        )
        desc.setWordWrap(True)
        desc.setStyleSheet(f"color:{c('t2')}; background:transparent;")
        lay.addWidget(desc)

        # ── Start from ────────────────────────────────────────────────
        start_box, start_lay = _card("Start from (optional)")
        start_row = QHBoxLayout()
        self._start_combo = NoWheelComboBox()
        self._start_combo.setFixedHeight(FIELD_HEIGHT)
        self._start_combo.setStyleSheet(input_style())
        start_row.addWidget(self._start_combo, 1)
        load_btn = _small_btn("Load")
        load_btn.setFixedHeight(FIELD_HEIGHT)
        load_btn.clicked.connect(self._on_load_start)
        start_row.addWidget(load_btn)
        start_lay.addLayout(start_row)
        note = QLabel("Loads those values as a starting point for a new template — never overwrites the original.")
        note.setWordWrap(True)
        note.setStyleSheet(f"color:{c('t3')}; background:transparent;")
        start_lay.addWidget(note)
        lay.addWidget(start_box)

        # ── Editor + live preview, side by side ─────────────────────────
        body = QHBoxLayout()
        body.setSpacing(16)

        editor_col = QVBoxLayout()
        editor_col.setSpacing(16)

        name_box, name_lay = _card("1 · Template name")
        self._name_field = QLineEdit("My Template")
        self._name_field.setFixedHeight(FIELD_HEIGHT)
        self._name_field.setStyleSheet(input_style())
        self._name_field.textChanged.connect(self._refresh_preview)
        name_lay.addWidget(self._name_field)
        editor_col.addWidget(name_box)

        cols_box, cols_lay = _card(
            "2 · Columns",
            "Category, Type and Amount are always included and locked in place — you can "
            "see them marked \"required\" below. Click a button to add Date, Payment type "
            "or Notes; drag any row to reorder; click ✕ to remove an optional one.",
        )
        self._columns_list = QListWidget()
        self._columns_list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self._columns_list.setFixedHeight(150)
        self._columns_list.setSpacing(2)
        self._columns_list.setToolTip("Drag rows up or down to reorder — this is the left-to-right column order in the file.")
        self._columns_list.setStyleSheet(f"""
            QListWidget {{ background:{c('in_bg')}; border:1px solid {c('in_bd')}; border-radius:8px; }}
            QListWidget::item {{ border:none; }}
            QListWidget::item:selected {{ background:{c('btn_bg')}; }}
        """)
        model = self._columns_list.model()
        model.rowsMoved.connect(self._on_columns_reordered)
        cols_lay.addWidget(self._columns_list)

        self._add_col_pills_row = QHBoxLayout()
        self._add_col_pills_row.setSpacing(6)
        cols_lay.addLayout(self._add_col_pills_row)
        self._add_col_hint = _helper_text("All optional columns are already included.")
        cols_lay.addWidget(self._add_col_hint)
        editor_col.addWidget(cols_box)

        cats_box, cats_lay = _card(
            "3 · Categories", "What you'll pick from when logging a transaction, e.g. Food, Rent, Salary.",
        )
        self._categories_editor = _ListEditor("New category…")
        self._categories_editor.changed.connect(self._on_categories_changed)
        cats_lay.addWidget(self._categories_editor)
        editor_col.addWidget(cats_box)

        invest_box, invest_lay = _card(
            "4 · Investments (optional)",
            "Check which categories count as investing, e.g. Crypto, Stocks. Tracked as "
            "\"Invest\" on the Dashboard regardless of whether it's Income or Expense type.",
        )
        self._invest_editor = _InvestCategoriesEditor()
        self._invest_editor.changed.connect(self._refresh_preview)
        invest_lay.addWidget(self._invest_editor)
        editor_col.addWidget(invest_box)

        types_box, types_lay = _card(
            "5 · Types",
            "Add every transaction type you use, then pick its role from the dropdown on "
            "the right of each row — Income, Expense, or Cash-in transfer. Anything left "
            "as \"no special meaning\" is still usable, it just isn't totaled specially.",
        )
        self._types_editor = _TypesEditor()
        self._types_editor.changed.connect(self._refresh_preview)
        types_lay.addWidget(self._types_editor)
        editor_col.addWidget(types_box)

        self._payment_box, payment_lay = _card(
            "6 · Payment types",
            'How each transaction was paid, e.g. Cash, Card. Name one of them exactly '
            '"Cash" to enable cash-vs-card tracking on the Dashboard.',
        )
        self._payment_editor = _ListEditor("New payment type…")
        self._payment_editor.changed.connect(self._refresh_preview)
        payment_lay.addWidget(self._payment_editor)
        editor_col.addWidget(self._payment_box)

        self._currency_box, currency_lay = _card(
            "7 · Currencies (optional)",
            "Which currencies you enter amounts in, e.g. CZK, USD. Pick one as the base "
            "currency — that's what Dashboard/Analytics totals convert everything into. "
            "Exchange rates themselves aren't set here — they live in the file's own Lists "
            "sheet and are edited directly in Excel, so the preview totals below don't "
            "convert between currencies.",
        )
        self._currency_editor = _ListEditor("New currency, e.g. USD…")
        self._currency_editor.changed.connect(self._on_currencies_changed)
        currency_lay.addWidget(self._currency_editor)
        currency_lay.addWidget(field_label("Base currency"))
        self._base_currency_combo = NoWheelComboBox()
        self._base_currency_combo.setFixedHeight(FIELD_HEIGHT)
        self._base_currency_combo.setStyleSheet(input_style())
        self._base_currency_combo.currentTextChanged.connect(self._refresh_preview)
        currency_lay.addWidget(self._base_currency_combo)
        editor_col.addWidget(self._currency_box)

        body.addLayout(editor_col, 1)

        # ── Live preview ─────────────────────────────────────────────────
        preview_col = QVBoxLayout()
        preview_col.setSpacing(16)

        preview_box, preview_lay = _card(
            "Live preview — how a month sheet will look",
            "Every month (Jan–Dec) gets an identical sheet with this same layout.",
        )

        tabs_row = QHBoxLayout()
        tabs_row.setSpacing(4)
        for i, month_name in enumerate(_MONTH_TABS):
            tab_lbl = QLabel(month_name)
            tab_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            tab_lbl.setFixedHeight(20)
            tab_lbl.setFont(QFont("Segoe UI", font_size("micro"), QFont.Weight.Bold if i == 0 else QFont.Weight.Normal))
            if i == 0:
                tab_lbl.setStyleSheet(f"""
                    background:{c('btn_bg')}; color:{c('ac')};
                    border:1px solid {c('btn_bd')}; border-radius:4px; padding:2px 6px;
                """)
            else:
                tab_lbl.setStyleSheet(f"""
                    background:{c('in_bg')}; color:{c('t2')};
                    border:1px solid {c('in_bd')}; border-radius:4px; padding:2px 6px;
                """)
            tabs_row.addWidget(tab_lbl)
        tabs_row.addStretch()
        preview_lay.addLayout(tabs_row)

        self._preview_table = QTableWidget(_PREVIEW_ROWS, 0)
        self._preview_table.verticalHeader().setVisible(False)
        self._preview_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._preview_table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self._preview_table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._preview_table.setAlternatingRowColors(True)
        self._preview_table.setStyleSheet(f"""
            QTableWidget {{ background:{c('panel_bg')}; alternate-background-color:{c('in_bg')};
                color:{c('t1')}; border:1px solid {c('panel_bd')};
                border-radius:10px; gridline-color:{c('sep')}; }}
            QHeaderView::section {{ background:{c('btn_bg')}; color:{c('t1')}; border:none;
                border-bottom:1px solid {c('sep')}; border-right:1px solid {c('sep')}; padding:6px; font-weight:bold; }}
            QTableWidget::item {{ padding:4px; }}
        """)
        preview_lay.addWidget(self._preview_table)

        summary_row = QHBoxLayout()
        summary_row.setSpacing(8)
        self._summary_chips: dict[str, tuple[QWidget, QLabel, QLabel]] = {}
        for key, title in [("income", "Income"), ("expense", "Expense"), ("balance", "Balance"),
                            ("invest", "Invest"), ("cash", "Cash"), ("card", "Card")]:
            chip, title_lbl, value_lbl = _stat_chip()
            title_lbl.setText(title)
            if key == "invest":
                value_lbl.setStyleSheet(f"color:{c('invest_c')}; background:transparent;")
            self._summary_chips[key] = (chip, title_lbl, value_lbl)
            summary_row.addWidget(chip)
        preview_lay.addLayout(summary_row)
        summary_note = QLabel("Totals as computed on the Dashboard for a month with these sample rows.")
        summary_note.setWordWrap(True)
        summary_note.setFont(QFont("Segoe UI", font_size("micro")))
        summary_note.setStyleSheet(f"color:{c('t3')}; background:transparent;")
        preview_lay.addWidget(summary_note)

        preview_col.addWidget(preview_box)
        preview_col.addStretch()
        body.addLayout(preview_col, 1)

        lay.addLayout(body)

        self._status = QLabel("")
        self._status.setWordWrap(True)
        self._status.setFont(QFont("Segoe UI", font_size("label")))
        lay.addWidget(self._status)

        save_btn = primary_button("Save as New Template")
        save_btn.clicked.connect(self._on_save)
        lay.addWidget(save_btn)

        self._load_from(Template.new_blank())
        self._refresh_start_combo()

    # ── loading a starting point ────────────────────────────────────────

    def _refresh_start_combo(self) -> None:
        self._start_combo.clear()
        self._start_combo.addItem("Blank template", _START_BLANK)
        for t in template_model.list_templates():
            self._start_combo.addItem(t.name, t.id)

    def _on_load_start(self) -> None:
        template_id = self._start_combo.currentData()
        if template_id == _START_BLANK or template_id is None:
            self._load_from(Template.new_blank())
            return
        template = template_model.get_template(template_id)
        if template is None:
            self._set_status("That template no longer exists.")
            return
        self._load_from(template)

    def _load_from(self, template: Template) -> None:
        self._name_field.setText(template.name)
        self._columns_list.clear()
        for role in template.columns:
            self._add_column_item(role)
        self._invest_editor.set_checked(template.invest_categories or [])
        self._categories_editor.set_values(template.categories)
        self._types_editor.set_from(template.types, template.income_type, template.expense_type, template.cash_in_type)
        if template.payment_types:
            self._payment_editor.set_values(template.payment_types)
        else:
            self._payment_editor.set_values([])
        if template.currencies:
            self._currency_editor.set_values(template.currencies)
            if template.base_currency in template.currencies:
                self._base_currency_combo.setCurrentText(template.base_currency)
        else:
            self._currency_editor.set_values([])
        self._refresh_add_column_row()
        self._update_payment_visibility()
        self._update_currency_visibility()
        self._refresh_preview()

    # ── columns ──────────────────────────────────────────────────────────

    def _current_columns(self) -> list[str]:
        return [self._columns_list.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self._columns_list.count())]

    def _column_row_widget(self, role: str) -> QWidget:
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(8, 0, 4, 0)
        h.setSpacing(6)
        handle = QLabel()
        handle.setPixmap(icon("drag-handle", c("t3")).pixmap(QSize(14, 14)))
        handle.setStyleSheet("background:transparent;")
        h.addWidget(handle)
        lbl = QLabel(ROLE_LABELS[role])
        lbl.setStyleSheet(f"color:{c('t1')}; background:transparent;")
        h.addWidget(lbl, 1)
        if role in REQUIRED_ROLES:
            tag = QLabel("required")
            tag.setFont(QFont("Segoe UI", font_size("micro") - 1))
            tag.setStyleSheet(f"color:{c('t3')}; background:{c('bg')}; border-radius:4px; padding:2px 8px;")
            h.addWidget(tag)
        else:
            rm = _remove_btn(f'Remove the {ROLE_LABELS[role]} column')
            rm.clicked.connect(lambda _checked=False, role=role: self._on_remove_column(role))
            h.addWidget(rm)
        return w

    def _add_column_item(self, role: str) -> None:
        item = QListWidgetItem()
        item.setData(Qt.ItemDataRole.UserRole, role)
        item.setSizeHint(QSize(0, 32))
        if role in REQUIRED_ROLES:
            item.setToolTip("Required — can't be removed")
        self._columns_list.addItem(item)
        self._columns_list.setItemWidget(item, self._column_row_widget(role))

    def _refresh_add_column_row(self) -> None:
        while self._add_col_pills_row.count():
            taken = self._add_col_pills_row.takeAt(0)
            w = taken.widget()
            if w is not None:
                w.deleteLater()
        used = set(self._current_columns())
        unused = [r for r in OPTIONAL_ROLES if r not in used]
        for role in unused:
            pill = _pill_btn(f"+ {ROLE_LABELS[role]}")
            pill.setToolTip(f"Add the {ROLE_LABELS[role]} column to this layout.")
            pill.clicked.connect(lambda _checked=False, role=role: self._on_add_column(role))
            self._add_col_pills_row.addWidget(pill)
        self._add_col_pills_row.addStretch()
        self._add_col_hint.setVisible(not unused)

    def _on_add_column(self, role: str) -> None:
        self._add_column_item(role)
        self._refresh_add_column_row()
        self._update_payment_visibility()
        self._update_currency_visibility()
        self._refresh_preview()

    def _on_remove_column(self, role: str) -> None:
        if role in REQUIRED_ROLES:
            return  # the UI never shows a ✕ for these; defensive no-op if called anyway
        for i in range(self._columns_list.count()):
            if self._columns_list.item(i).data(Qt.ItemDataRole.UserRole) == role:
                self._columns_list.takeItem(i)
                break
        self._refresh_add_column_row()
        self._update_payment_visibility()
        self._update_currency_visibility()
        self._refresh_preview()

    def _on_columns_reordered(self, *_args) -> None:
        self._refresh_preview()

    def _update_payment_visibility(self) -> None:
        has_payment = ROLE_PAYMENT in self._current_columns()
        self._payment_box.setVisible(has_payment)

    def _update_currency_visibility(self) -> None:
        has_currency = ROLE_CURRENCY in self._current_columns()
        self._currency_box.setVisible(has_currency)

    def _on_currencies_changed(self) -> None:
        currencies = self._currency_editor.values()
        current = self._base_currency_combo.currentText()
        self._base_currency_combo.blockSignals(True)
        self._base_currency_combo.clear()
        self._base_currency_combo.addItems(currencies)
        if current in currencies:
            self._base_currency_combo.setCurrentText(current)
        self._base_currency_combo.blockSignals(False)
        self._refresh_preview()

    def _on_categories_changed(self) -> None:
        self._invest_editor.refresh_categories(self._categories_editor.values())
        self._refresh_preview()

    # ── live preview ─────────────────────────────────────────────────────

    def _refresh_preview(self, *_args) -> None:
        columns = self._current_columns()
        self._preview_table.setColumnCount(len(columns))
        self._preview_table.setHorizontalHeaderLabels([ROLE_LABELS[r] for r in columns])

        categories = self._categories_editor.values() or ["(category)"]
        types = self._types_editor.types() or ["(type)"]
        payments = self._payment_editor.values() or ["Cash"]
        currencies = self._currency_editor.values() or ["CZK"]
        sample_dates = ["2026-01-05", "2026-01-12", "2026-01-18", "2026-01-27"]
        sample_amounts = [1200.00, 85.50, 300.00, 42.00]
        sample_notes = ["monthly pay", "", "groceries", ""]

        income_type = self._types_editor.income_type() or ""
        expense_type = self._types_editor.expense_type() or ""
        cash_in_type = self._types_editor.cash_in_type()
        invest_categories = set(self._invest_editor.values())
        has_payment_col = ROLE_PAYMENT in columns
        has_currency_col = ROLE_CURRENCY in columns

        income = expense = invest = cash = 0.0
        for row in range(_PREVIEW_ROWS):
            row_type = types[row % len(types)]
            row_amount = sample_amounts[row % len(sample_amounts)]
            row_payment = payments[row % len(payments)] if has_payment_col else None
            row_currency = currencies[row % len(currencies)] if has_currency_col else None
            row_category = categories[row % len(categories)]

            for col, role in enumerate(columns):
                if role == ROLE_DATE:
                    value = sample_dates[row % len(sample_dates)]
                elif role == ROLE_CATEGORY:
                    value = row_category
                elif role == ROLE_TYPE:
                    value = row_type
                elif role == ROLE_AMOUNT:
                    value = f"{row_amount:.2f}"
                elif role == ROLE_PAYMENT:
                    value = row_payment
                elif role == ROLE_CURRENCY:
                    value = row_currency
                elif role == ROLE_NOTES:
                    value = sample_notes[row % len(sample_notes)]
                else:
                    value = ""
                item = QTableWidgetItem(value)
                if role == ROLE_AMOUNT:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                if role == ROLE_TYPE and value == income_type:
                    item.setForeground(QColor(c("income_c")))
                elif role == ROLE_TYPE and value == expense_type:
                    item.setForeground(QColor(c("expense_c")))
                elif role == ROLE_CATEGORY and value in invest_categories:
                    item.setForeground(QColor(c("invest_c")))
                self._preview_table.setItem(row, col, item)

            # Mirror DynamicSchema.month_summary()'s exact logic, including the
            # literal "Cash" payment match, so the totals below are what the
            # Dashboard would actually show for a month with these rows.
            if row_type == income_type:
                income += row_amount
            elif row_type == expense_type:
                expense += row_amount
            if row_category in invest_categories:
                invest += row_amount
            if cash_in_type and row_type == cash_in_type:
                cash += row_amount
            elif row_type == expense_type and row_payment == "Cash":
                cash -= row_amount

        self._preview_table.resizeRowsToContents()
        header_h = self._preview_table.horizontalHeader().height()
        rows_h = sum(self._preview_table.rowHeight(r) for r in range(self._preview_table.rowCount()))
        self._preview_table.setFixedHeight(header_h + rows_h + 4)

        balance = income - expense
        has_tracking = cash_in_type is not None
        self._set_summary_chip("income", income)
        self._set_summary_chip("expense", expense)
        self._set_summary_chip("balance", balance)
        self._set_summary_chip("invest", invest)
        self._set_summary_chip("cash", cash if has_tracking else None)
        self._set_summary_chip("card", (balance - cash) if has_tracking else None)

    def _set_summary_chip(self, key: str, value: float | None) -> None:
        chip, _title_lbl, value_lbl = self._summary_chips[key]
        if value is None:
            chip.setVisible(False)
            return
        chip.setVisible(True)
        value_lbl.setText(f"{value:,.2f}")

    # ── save ─────────────────────────────────────────────────────────────

    def _set_status(self, text: str, error: bool = True) -> None:
        self._status.setStyleSheet(f"color:{c('err_c') if error else c('income_c')}; background:transparent;")
        self._status.setText(text)

    def _on_save(self) -> None:
        template = Template.new_blank()
        template.name = self._name_field.text().strip()
        template.columns = self._current_columns()
        template.categories = self._categories_editor.values()
        template.types = self._types_editor.types()
        template.income_type = self._types_editor.income_type() or ""
        template.expense_type = self._types_editor.expense_type() or ""
        template.cash_in_type = self._types_editor.cash_in_type()
        template.payment_types = self._payment_editor.values() if ROLE_PAYMENT in template.columns else None
        template.invest_categories = self._invest_editor.values()
        if ROLE_CURRENCY in template.columns:
            template.currencies = self._currency_editor.values()
            template.base_currency = self._base_currency_combo.currentText() or None
        else:
            template.currencies = None
            template.base_currency = None

        try:
            template.validate()
        except TemplateValidationError as exc:
            self._set_status(str(exc))
            return

        template_model.save_template(template)
        self._refresh_start_combo()
        self._set_status(f'Saved "{template.name}" — it now shows up when creating a new file.', error=False)
