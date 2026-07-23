"""
app/pages/templates_page.py — TemplatesPage: build a custom workbook
Template with a live, Excel-style table preview of the columns as you
edit them — a full page (not a modal) so it's a comfortable place to
experiment, reachable via Settings → Templates (app/pages/settings_page.py).
Saving emits template_saved so the Settings page's "Create New File" tab
can refresh its layout picker immediately.

Layout is a three-pane body, each pane independently scrollable: a narrow
mini-nav rail on the left (jump to / see at-a-glance which sections you've
customized), the editable form in the middle, and the live preview pinned
on the right — its own QScrollArea, so it never scrolls out of view no
matter how far down the form is scrolled (the single biggest complaint
against the old one-column layout, where scrolling to "Types" or below
lost the preview entirely).

Interaction design is deliberately "direct manipulation" rather than
select-then-click-a-button: columns are added by clicking a "+ Date" style
pill and removed by clicking an inline ✕ next to that exact row; the
required Category/Type/Amount columns show a lock icon instead (no ✕, no
separate tag box) so it's obvious at a glance why they can't be dragged
out. Optional columns render as ordered, squarish drag-tags (order and
lock-state matter); Categories/Payment types/Currencies render as
unordered, fully-rounded pill chips in a wrapping FlowLayout — the two
shapes are deliberately different, not just decorative, since only
Columns has a meaningful order.

Categories and Investments share one card: each category is a chip with
an inline star toggle — starring a category marks it as counting toward
"Invest" on the Dashboard (exactly `invest_categories`), no more duplicate
list shown twice.

Types combine the list and the Income/Expense/Cash-in role assignment
into one row each: a neutral (uncolored) name field plus a 4-button
segmented role control (Income/Expense/Cash-in/Other), the active option
filled in that role's color, with a matching thin color bar down the
row's left edge as a second cue. Picking a role that's already taken
auto-clears it from whichever row had it, so there's never a way to end
up with two "Income" types by accident.

The preview shows the *whole picture*, not just an echo of the fields you
can edit: alongside the sample rows it shows the row of month tabs every
layout repeats across, and a totals strip (Income/Expense/Balance/Invest/
Cash/Card) computed the same way DynamicSchema.month_summary() computes it
for a real file — including the fact that cash tracking only kicks in for
expenses paid with a payment option literally named "Cash", which is
otherwise an easy thing to miss.

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
    FlowLayout, NoWheelComboBox, bordered_box, card as _base_card, primary_button, scrollable_area,
)

_PREVIEW_ROWS = 4
_START_BLANK = "__blank__"
_MONTH_TABS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

_ROLE_NONE = "(no special meaning)"
_ROLE_INCOME = "Income"
_ROLE_EXPENSE = "Expense"
_ROLE_CASH_IN = "Cash-in transfer"
_TYPE_ROLE_OPTIONS = [_ROLE_INCOME, _ROLE_EXPENSE, _ROLE_CASH_IN, _ROLE_NONE]
_TYPE_ROLE_SHORT = {_ROLE_INCOME: "Income", _ROLE_EXPENSE: "Expense", _ROLE_CASH_IN: "Cash-in", _ROLE_NONE: "Other"}
_TYPE_ROLE_COLOR = {_ROLE_INCOME: c("income_c"), _ROLE_EXPENSE: c("expense_c"), _ROLE_CASH_IN: c("invest_c"), _ROLE_NONE: c("t3")}

# Mini-nav sections, in form order — each maps to the card widget added under
# the same key in TemplatesPage._section_widgets, and to a _is_<key>_dirty
# predicate deciding whether its status dot lights up.
_NAV_SECTIONS = [
    ("name", "Name"), ("columns", "Columns"), ("categories", "Categories"),
    ("types", "Types"), ("payment", "Payment types"), ("currency", "Currencies"),
]


def _tint(hex_color: str, alpha: int) -> str:
    """hex_color ('#rrggbb') -> 'rgba(r,g,b,alpha)' — the palette only has
    solid role colors (income_c/expense_c/invest_c), not pre-mixed
    translucent variants like btn_bg/btn_bd, so segmented role buttons mix
    their own on the fly."""
    r, g, b = int(hex_color[1:3], 16), int(hex_color[3:5], 16), int(hex_color[5:7], 16)
    return f"rgba({r},{g},{b},{alpha})"


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


def _star_btn(active: bool, tooltip: str) -> QPushButton:
    btn = QPushButton()
    btn.setIcon(icon("star" if active else "star-outline", c("invest_c") if active else c("t3")))
    btn.setIconSize(QSize(13, 13))
    btn.setFixedSize(22, 22)
    btn.setToolTip(tooltip)
    btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
    btn.setStyleSheet(f"""
        QPushButton {{ background:transparent; border:none; border-radius:{radius('sm') - 1}px; }}
        QPushButton:hover {{ background:{c('in_bg')}; }}
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


class _ChipListEditor(QWidget):
    """A wrapping row of fully-rounded pill chips — type a value, hit
    Add/Enter, or click a chip's inline ✕ to remove it directly. Used for
    Payment types and Currencies (unordered sets — a FlowLayout, unlike
    Columns' ordered drag-list). `star=True` (Categories only) adds an
    inline star toggle per chip for investment-category marking."""

    changed = pyqtSignal()

    def __init__(self, placeholder: str, parent=None, star: bool = False):
        super().__init__(parent)
        self._star = star
        self._values: list[str] = []
        self._starred: set[str] = set()

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)

        self._chip_area = QWidget()
        self._flow = FlowLayout(self._chip_area, margin=0, spacing=6)
        lay.addWidget(self._chip_area)

        self._empty_hint = _helper_text("Nothing added yet — use the field below.")
        lay.addWidget(self._empty_hint)

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

    def _chip_widget(self, text: str) -> QWidget:
        chip = bordered_box(c("in_bg"), c("in_bd"), radius=13)
        h = QHBoxLayout(chip)
        h.setContentsMargins(10, 3, 4, 3)
        h.setSpacing(2)
        if self._star:
            star = _star_btn(text in self._starred, f'Mark "{text}" as investing' if text not in self._starred else f'Unmark "{text}"')
            star.clicked.connect(lambda _c=False, t=text: self._toggle_star(t))
            h.addWidget(star)
        lbl = QLabel(text)
        lbl.setStyleSheet(f"color:{c('invest_c') if text in self._starred else c('t1')}; background:transparent;")
        h.addWidget(lbl)
        rm = _remove_btn(f'Remove "{text}"')
        rm.clicked.connect(lambda _c=False, t=text: self._remove(t))
        h.addWidget(rm)
        return chip

    def _rebuild(self) -> None:
        while self._flow.count():
            item = self._flow.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        for v in self._values:
            self._flow.addWidget(self._chip_widget(v))
        self._chip_area.setVisible(bool(self._values))
        self._empty_hint.setVisible(not self._values)
        self._flow.update()

    def _toggle_star(self, text: str) -> None:
        if text in self._starred:
            self._starred.discard(text)
        else:
            self._starred.add(text)
        self._rebuild()
        self.changed.emit()

    def _remove(self, text: str) -> None:
        self._values = [v for v in self._values if v != text]
        self._starred.discard(text)
        self._rebuild()
        self.changed.emit()

    def _on_add(self) -> None:
        text = self._input.text().strip()
        if not text or text in self._values:
            self._input.clear()
            return
        self._values.append(text)
        self._input.clear()
        self._rebuild()
        self.changed.emit()

    def values(self) -> list[str]:
        return list(self._values)

    def starred(self) -> list[str]:
        return [v for v in self._values if v in self._starred]

    def set_values(self, values: list[str], starred: list[str] | None = None) -> None:
        self._values = list(values)
        self._starred = set(starred or []) & set(values)
        self._rebuild()


class _TypesEditor(QWidget):
    """Types and their Income/Expense/Cash-in role live in one place: each
    row is a neutral (uncolored) name plus a 4-button segmented role
    control, instead of a separate type list and three "which type means
    X" combos elsewhere on the page — and instead of a dropdown whose text
    used to visually collide with the name label for the default "Income"/
    "Expense" rows. Picking a role that's already taken automatically
    clears it from whichever row had it, so Income/Expense/Cash-in can
    never point at two rows at once. The first type added is auto-assigned
    Income, the second Expense, since that's what almost everyone wants for
    their first two entries."""

    changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows: list[dict] = []

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)

        self.list_widget = QListWidget()
        self.list_widget.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.list_widget.setFixedHeight(170)
        self.list_widget.setSpacing(3)
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

    def _role_btn(self, name: str, role: str, active: bool) -> QPushButton:
        color = _TYPE_ROLE_COLOR[role]
        btn = QPushButton(_TYPE_ROLE_SHORT[role])
        btn.setFixedHeight(24)
        btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        if active:
            btn.setStyleSheet(f"""
                QPushButton {{ background:{_tint(color, 30)}; color:{color};
                    border:1px solid {_tint(color, 90)}; border-radius:{radius('sm')}px; font-weight:bold; }}
            """)
        else:
            btn.setStyleSheet(f"""
                QPushButton {{ background:transparent; color:{c('t3')};
                    border:1px solid {c('in_bd')}; border-radius:{radius('sm')}px; }}
                QPushButton:hover {{ color:{c('t2')}; border-color:{c('t2')}; }}
            """)
        btn.clicked.connect(lambda _c=False, n=name, r=role: self._set_role(n, r))
        return btn

    def _row_widget(self, name: str, role: str) -> QWidget:
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 4, 0)
        h.setSpacing(8)

        bar = QLabel()
        bar.setFixedWidth(4)
        bar.setStyleSheet(f"background:{_TYPE_ROLE_COLOR[role]}; border-radius:2px;")
        h.addWidget(bar)

        lbl = QLabel(name)
        lbl.setStyleSheet(f"color:{c('t1')}; background:transparent;")
        h.addWidget(lbl, 1)

        roles_row = QHBoxLayout()
        roles_row.setSpacing(4)
        for role_opt in _TYPE_ROLE_OPTIONS:
            roles_row.addWidget(self._role_btn(name, role_opt, role_opt == role))
        h.addLayout(roles_row)

        rm = _remove_btn(f'Remove "{name}"')
        rm.clicked.connect(lambda _checked=False, n=name: self._remove(n))
        h.addWidget(rm)
        return w

    def _rebuild(self) -> None:
        self.list_widget.clear()
        for r in self._rows:
            item = QListWidgetItem()
            item.setSizeHint(QSize(0, 36))
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


class TemplatesPage(QWidget):
    template_saved = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)

        outer_lay = QVBoxLayout(self)
        outer_lay.setContentsMargins(4, 4, 4, 4)
        outer_lay.setSpacing(12)

        header_row = QHBoxLayout()
        hdr = QLabel("Templates")
        hdr.setFont(QFont("Segoe UI", font_size("title"), QFont.Weight.Bold))
        hdr.setStyleSheet(f"color:{c('t1')}; background:transparent;")
        header_row.addWidget(hdr)
        header_row.addStretch()
        outer_lay.addLayout(header_row)

        desc = QLabel(
            "Design a workbook layout — which columns, in what order — and see it update live on the right. "
            "Saved templates show up as a layout choice when creating a new finances file."
        )
        desc.setWordWrap(True)
        desc.setStyleSheet(f"color:{c('t2')}; background:transparent;")
        outer_lay.addWidget(desc)

        # ── Three-pane body: mini-nav | form | live preview ─────────────
        body = QHBoxLayout()
        body.setSpacing(16)
        outer_lay.addLayout(body, 1)

        self._section_widgets: dict[str, QWidget] = {}
        self._nav_dots: dict[str, QLabel] = {}
        self._build_mini_nav(body)
        self._build_form(body)
        self._build_preview(body)

        self._load_from(Template.new_blank())
        self._refresh_start_combo()

    # ── mini-nav ─────────────────────────────────────────────────────────

    def _build_mini_nav(self, body: QHBoxLayout) -> None:
        nav_box = bordered_box(c("panel_bg"), c("panel_bd"), radius=radius("xl"))
        nav_box.setFixedWidth(150)
        nav_lay = QVBoxLayout(nav_box)
        nav_lay.setContentsMargins(8, 12, 8, 12)
        nav_lay.setSpacing(2)

        self._nav_btns: dict[str, QPushButton] = {}
        for key, label in _NAV_SECTIONS:
            row_w = QWidget()
            row = QHBoxLayout(row_w)
            row.setContentsMargins(4, 0, 4, 0)
            row.setSpacing(6)
            dot = QLabel()
            dot.setFixedSize(7, 7)
            self._style_dot(dot, False)
            row.addWidget(dot)
            btn = QPushButton(label)
            btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            btn.setFixedHeight(28)
            btn.setStyleSheet(f"""
                QPushButton {{ background:transparent; color:{c('t2')}; border:none;
                    text-align:left; padding:0 4px; }}
                QPushButton:hover {{ color:{c('ac')}; }}
            """)
            btn.clicked.connect(lambda _c=False, k=key: self._jump_to(k))
            row.addWidget(btn, 1)
            nav_lay.addWidget(row_w)
            self._nav_btns[key] = btn
            self._nav_dots[key] = dot
        nav_lay.addStretch()
        body.addWidget(nav_box)

    def _style_dot(self, dot: QLabel, active: bool) -> None:
        color = c("ac") if active else "transparent"
        border = c("ac") if active else c("t3")
        dot.setStyleSheet(f"background:{color}; border:1px solid {border}; border-radius:3px;")

    def _jump_to(self, key: str) -> None:
        target = self._section_widgets.get(key)
        if target is not None:
            self._form_scroll.ensureWidgetVisible(target, yMargin=40)

    # ── form (scrollable, with a sticky footer outside the scroll area) ──

    def _build_form(self, body: QHBoxLayout) -> None:
        form_col = QVBoxLayout()
        form_col.setSpacing(0)

        content = QWidget()
        content.setStyleSheet("background:transparent;")
        self._form_scroll = scrollable_area(content)
        form_col.addWidget(self._form_scroll, 1)

        lay = QVBoxLayout(content)
        lay.setContentsMargins(4, 4, 12, 20)
        lay.setSpacing(16)

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

        name_box, name_lay = _card("Template name")
        self._name_field = QLineEdit("My Template")
        self._name_field.setFixedHeight(FIELD_HEIGHT)
        self._name_field.setStyleSheet(input_style())
        self._name_field.textChanged.connect(self._refresh_preview)
        name_lay.addWidget(self._name_field)
        lay.addWidget(name_box)
        self._section_widgets["name"] = name_box

        cols_box, cols_lay = _card(
            "Columns",
            "Category, Type and Amount are always included — shown locked below with a "
            "padlock icon. Click a button to add Date, Payment type or Notes; drag any row "
            "to reorder; click ✕ to remove an optional one.",
        )
        self._columns_list = QListWidget()
        self._columns_list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self._columns_list.setFixedHeight(150)
        self._columns_list.setSpacing(3)
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
        lay.addWidget(cols_box)
        self._section_widgets["columns"] = cols_box

        cats_box, cats_lay = _card(
            "Categories",
            "What you'll pick from when logging a transaction, e.g. Food, Rent, Salary. "
            "Click the star on a category to track it as \"Invest\" on the Dashboard "
            "regardless of whether it's logged as Income or Expense.",
        )
        self._categories_editor = _ChipListEditor("New category…", star=True)
        self._categories_editor.changed.connect(self._refresh_preview)
        cats_lay.addWidget(self._categories_editor)
        lay.addWidget(cats_box)
        self._section_widgets["categories"] = cats_box

        types_box, types_lay = _card(
            "Types",
            "Add every transaction type you use, then pick its role with the buttons on "
            "the right of each row — Income, Expense, or Cash-in. Anything left as "
            "\"Other\" is still usable, it just isn't totaled specially.",
        )
        self._types_editor = _TypesEditor()
        self._types_editor.changed.connect(self._refresh_preview)
        types_lay.addWidget(self._types_editor)
        lay.addWidget(types_box)
        self._section_widgets["types"] = types_box

        self._payment_box, payment_lay = _card(
            "Payment types",
            'How each transaction was paid, e.g. Cash, Card. Name one of them exactly '
            '"Cash" to enable cash-vs-card tracking on the Dashboard.',
        )
        self._payment_editor = _ChipListEditor("New payment type…")
        self._payment_editor.changed.connect(self._refresh_preview)
        payment_lay.addWidget(self._payment_editor)
        lay.addWidget(self._payment_box)
        self._section_widgets["payment"] = self._payment_box

        self._currency_box, currency_lay = _card(
            "Currencies (optional)",
            "Which currencies you enter amounts in, e.g. CZK, USD. Pick one as the base "
            "currency — that's what Dashboard/Analytics totals convert everything into. "
            "Exchange rates themselves aren't set here — they live in the file's own Lists "
            "sheet and are edited directly in Excel, so the preview totals below don't "
            "convert between currencies.",
        )
        self._currency_editor = _ChipListEditor("New currency, e.g. USD…")
        self._currency_editor.changed.connect(self._on_currencies_changed)
        currency_lay.addWidget(self._currency_editor)
        currency_lay.addWidget(field_label("Base currency"))
        self._base_currency_combo = NoWheelComboBox()
        self._base_currency_combo.setFixedHeight(FIELD_HEIGHT)
        self._base_currency_combo.setStyleSheet(input_style())
        self._base_currency_combo.currentTextChanged.connect(self._refresh_preview)
        currency_lay.addWidget(self._base_currency_combo)
        lay.addWidget(self._currency_box)
        self._section_widgets["currency"] = self._currency_box

        lay.addStretch()

        # ── Sticky save footer — pinned under the scroll area, not full app width ──
        footer = QWidget()
        footer_lay = QVBoxLayout(footer)
        footer_lay.setContentsMargins(4, 10, 12, 0)
        footer_lay.setSpacing(6)
        self._status = QLabel("")
        self._status.setWordWrap(True)
        self._status.setFont(QFont("Segoe UI", font_size("label")))
        footer_lay.addWidget(self._status)
        save_btn = primary_button("Save as New Template")
        save_btn.clicked.connect(self._on_save)
        footer_lay.addWidget(save_btn)
        form_col.addWidget(footer)

        body.addLayout(form_col, 1)

    # ── live preview (own scroll area, independent of the form) ──────────

    def _build_preview(self, body: QHBoxLayout) -> None:
        preview_content = QWidget()
        preview_content.setStyleSheet("background:transparent;")
        preview_scroll = scrollable_area(preview_content)
        preview_scroll.setMinimumWidth(360)

        preview_col = QVBoxLayout(preview_content)
        preview_col.setContentsMargins(4, 4, 4, 20)
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

        body.addWidget(preview_scroll, 1)

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
        self._categories_editor.set_values(template.categories, template.invest_categories or [])
        self._types_editor.set_from(template.types, template.income_type, template.expense_type, template.cash_in_type)
        self._payment_editor.set_values(template.payment_types or [])
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
        w = bordered_box(c("in_bg"), c("in_bd"), radius=radius("sm"))
        h = QHBoxLayout(w)
        h.setContentsMargins(8, 2, 4, 2)
        h.setSpacing(6)
        handle = QLabel()
        handle.setPixmap(icon("drag-handle", c("t3")).pixmap(QSize(14, 14)))
        handle.setStyleSheet("background:transparent;")
        h.addWidget(handle)
        lbl = QLabel(ROLE_LABELS[role])
        lbl.setStyleSheet(f"color:{c('t1')}; background:transparent;")
        h.addWidget(lbl, 1)
        if role in REQUIRED_ROLES:
            lock = QLabel()
            lock.setPixmap(icon("lock", c("t3")).pixmap(QSize(13, 13)))
            lock.setStyleSheet("background:transparent;")
            lock.setToolTip("Required — can't be removed")
            h.addWidget(lock)
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
        invest_categories = set(self._categories_editor.starred())
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

        self._refresh_nav_dots()

    def _set_summary_chip(self, key: str, value: float | None) -> None:
        chip, _title_lbl, value_lbl = self._summary_chips[key]
        if value is None:
            chip.setVisible(False)
            return
        chip.setVisible(True)
        value_lbl.setText(f"{value:,.2f}")

    # ── mini-nav status dots ─────────────────────────────────────────────

    def _refresh_nav_dots(self) -> None:
        blank = Template.new_blank()
        dirty = {
            "name": self._name_field.text().strip() != blank.name,
            "columns": self._current_columns() != blank.columns,
            "categories": (self._categories_editor.values() != blank.categories
                           or self._categories_editor.starred() != blank.invest_categories),
            "types": (self._types_editor.types() != blank.types
                      or self._types_editor.income_type() != blank.income_type
                      or self._types_editor.expense_type() != blank.expense_type
                      or self._types_editor.cash_in_type() != blank.cash_in_type),
            "payment": bool(self._payment_editor.values()),
            "currency": bool(self._currency_editor.values()),
        }
        for key, is_dirty in dirty.items():
            self._style_dot(self._nav_dots[key], is_dirty)

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
        template.invest_categories = self._categories_editor.starred()
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
        status = f'Saved "{template.name}" — it now shows up when creating a new file.'
        # Cash tracking only ever fires for a payment type literally named
        # "Cash" (schema_dynamic.py/schema_2026.py both hardcode the exact
        # string) -- a template that defines a cash-in type but whose own
        # payment list doesn't include it would never see its cash total
        # move, a real gotcha this app doesn't otherwise catch anywhere.
        if template.cash_in_type and template.payment_types and "Cash" not in template.payment_types:
            status += (
                ' Note: this template has a cash-in type but no payment option literally named '
                '"Cash" — cash tracking on the Dashboard will never move for it.'
            )
        self._set_status(status, error=False)
        self.template_saved.emit()
