"""
app/components/widgets.py — small reusable widget subclasses/helpers.
"""
from __future__ import annotations

from PyQt6.QtCore import QPoint, QRect, QSize, Qt
from PyQt6.QtGui import QCursor, QFont
from PyQt6.QtWidgets import (
    QComboBox, QFrame, QLabel, QLayout, QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

from core.themes import FIELD_HEIGHT, c, font_size, radius

_box_seq = [0]


class FlowLayout(QLayout):
    """A layout that wraps its children left-to-right, wrapping to a new row
    when the current one runs out of width — Qt has no built-in equivalent
    (unlike CSS flex-wrap). Used for pill-chip rows (Categories, Payment
    types, Currencies) where the item count/width isn't known ahead of
    time, unlike Columns' fixed drag-orderable list."""

    def __init__(self, parent=None, margin: int = 0, spacing: int = 6):
        super().__init__(parent)
        self.setContentsMargins(margin, margin, margin, margin)
        self.setSpacing(spacing)
        self._items: list = []

    def addItem(self, item) -> None:
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int):
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index: int):
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def expandingDirections(self) -> Qt.Orientation:
        return Qt.Orientation(0)

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        return self._do_layout(QRect(0, 0, width, 0), test_only=True)

    def setGeometry(self, rect: QRect) -> None:
        super().setGeometry(rect)
        self._do_layout(rect, test_only=False)

    def sizeHint(self) -> QSize:
        return self.minimumSize()

    def minimumSize(self) -> QSize:
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        margins = self.contentsMargins()
        size += QSize(margins.left() + margins.right(), margins.top() + margins.bottom())
        return size

    def _do_layout(self, rect: QRect, test_only: bool) -> int:
        x, y = rect.x(), rect.y()
        line_height = 0
        spacing = self.spacing()
        for item in self._items:
            hint = item.sizeHint()
            next_x = x + hint.width() + spacing
            if next_x - spacing > rect.right() and line_height > 0:
                x = rect.x()
                y += line_height + spacing
                next_x = x + hint.width() + spacing
                line_height = 0
            if not test_only:
                item.setGeometry(QRect(QPoint(x, y), hint))
            x = next_x
            line_height = max(line_height, hint.height())
        return y + line_height - rect.y()


class NoWheelComboBox(QComboBox):
    """A QComboBox that never reacts to the mouse wheel/touchpad — otherwise
    scrolling a page that contains a dropdown changes the dropdown's
    selection instead of scrolling the page. Always ignored (not just when
    unfocused) so behavior is predictable: use the dropdown, not the wheel,
    to change its value."""

    def wheelEvent(self, event) -> None:
        event.ignore()


def bordered_box(bg: str, border: str | None = None, radius: int = 14, extra: str = "") -> QWidget:
    """A QWidget with a background/border scoped to its own object name.
    Qt Style Sheets, unlike CSS, propagate bare (unscoped) properties —
    border in particular — down through the widget tree, so a plain
    `widget.setStyleSheet("border: 1px solid ...")` leaks that border onto
    every unstyled child label inside it. Scoping the rule to `#<name>`
    keeps it on this widget only."""
    _box_seq[0] += 1
    name = f"Box{_box_seq[0]}"
    box = QWidget()
    box.setObjectName(name)
    border_rule = f"border:1px solid {border};" if border else "border:none;"
    box.setStyleSheet(f"QWidget#{name} {{ background:{bg}; {border_rule} border-radius:{radius}px; {extra} }}")
    return box


def section_label(text: str) -> QLabel:
    """The "card/section header" text style — bold, muted, one size up from
    a field label. Shared so every page's cards read at the same weight."""
    lbl = QLabel(text)
    lbl.setFont(QFont("Segoe UI", font_size("section"), QFont.Weight.Bold))
    lbl.setStyleSheet(f"color:{c('t2')}; background:transparent;")
    return lbl


def card(title: str) -> tuple[QWidget, QVBoxLayout]:
    """The canonical titled card (bordered_box + a section_label header) —
    the shape reused by every page for chart/list/form panels."""
    box = bordered_box(c("panel_bg"), c("panel_bd"), radius=radius("xl"))
    lay = QVBoxLayout(box)
    lay.setContentsMargins(20, 16, 20, 16)
    lay.setSpacing(8)
    lay.addWidget(section_label(title))
    return box, lay


def scrollable_area(content: QWidget) -> QScrollArea:
    """Wraps `content` in a borderless, transparent QScrollArea with the
    app's thin custom scrollbar — the block every scrollable page repeats."""
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.Shape.NoFrame)
    scroll.setStyleSheet(f"""
        QScrollArea {{ background:transparent; border:none; }}
        QScrollBar:vertical {{ background:transparent; width:8px; }}
        QScrollBar::handle:vertical {{ background:{c('in_bd')}; border-radius:4px; min-height:24px; }}
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height:0; }}
    """)
    scroll.setWidget(content)
    return scroll


def primary_button(text: str) -> QPushButton:
    """The app's one "affirmative action" button style (Save/Add/Rename/...)."""
    btn = QPushButton(text)
    btn.setFixedHeight(FIELD_HEIGHT)  # matches input-field height so forms line up
    btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
    btn.setStyleSheet(f"""
        QPushButton {{ background:{c('btn_bg')}; color:{c('ac')};
            border:1px solid {c('btn_bd')}; border-radius:{radius('md')}px; font-weight:bold; padding:0 16px; }}
        QPushButton:hover {{ background:{c('btn_hbg')}; }}
        QPushButton:disabled {{ background:transparent; color:{c('t3')}; border-color:{c('in_bd')}; }}
    """)
    return btn


def secondary_button(text: str) -> QPushButton:
    """The app's "neutral action" button style (Cancel/Delete/Edit/...)."""
    btn = QPushButton(text)
    btn.setFixedHeight(FIELD_HEIGHT)  # matches primary_button's height
    btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
    btn.setStyleSheet(f"""
        QPushButton {{ background:transparent; color:{c('t2')};
            border:1px solid {c('in_bd')}; border-radius:{radius('md')}px; padding:0 16px; }}
        QPushButton:hover {{ color:{c('ac')}; border-color:{c('ac')}; }}
        QPushButton:disabled {{ color:{c('t3')}; border-color:{c('in_bd')}; }}
    """)
    return btn


def nav_chip_style(selected: bool, *, ghost: bool = False, radius_key: str = "md") -> str:
    """QSS for a QPushButton acting as a selectable "chip" — the
    selected/unselected pairing shared by the sidebar nav, the month-picker
    popup, and Templates' month tabs (previously three separate
    implementations with three different unselected-text colors). `ghost`
    picks the sidebar's fully-transparent unselected look instead of the
    outlined one used by the other two."""
    r = radius(radius_key)
    if selected:
        return f"""
            QPushButton {{ background:{c('btn_bg')}; color:{c('ac')};
                border:1px solid {c('btn_bd')}; border-radius:{r}px; font-weight:bold; }}
            QPushButton:hover {{ background:{c('btn_hbg')}; }}
        """
    if ghost:
        return f"""
            QPushButton {{ background:transparent; color:{c('t2')};
                border:1px solid transparent; border-radius:{r}px; }}
            QPushButton:hover {{ background:{c('in_bg')}; color:{c('t1')}; }}
        """
    return f"""
        QPushButton {{ background:{c('in_bg')}; color:{c('t2')};
            border:1px solid {c('in_bd')}; border-radius:{r}px; }}
        QPushButton:hover {{ border-color:{c('ac')}; color:{c('ac')}; }}
        QPushButton:disabled {{ color:{c('t3')}; background:transparent; }}
    """
