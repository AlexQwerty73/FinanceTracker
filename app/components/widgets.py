"""
app/components/widgets.py — small reusable widget subclasses/helpers.
"""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QCursor, QFont
from PyQt6.QtWidgets import (
    QComboBox, QFrame, QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

from core.themes import FIELD_HEIGHT, c, font_size, radius

_box_seq = [0]


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
