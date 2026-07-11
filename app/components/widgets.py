"""
app/components/widgets.py — small reusable widget subclasses/helpers.
"""
from __future__ import annotations

from PyQt6.QtWidgets import QComboBox, QWidget

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
