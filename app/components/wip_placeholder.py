"""
app/components/wip_placeholder.py — WipPlaceholder: a plain "this page is
being redesigned" stand-in for a sidebar page that's temporarily disabled.
Used instead of instantiating the real page, so its (possibly large,
unfinished-redesign) implementation stays completely untouched and simply
isn't wired up for now — swap the import back in window.py to restore it.
"""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import QLabel, QVBoxLayout, QWidget

from core.themes import c, font_size

_CENTER = Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter


class WipPlaceholder(QWidget):
    def __init__(self, title: str, note: str = "This page is being redesigned.", parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.addStretch()

        hdr = QLabel(title)
        hdr.setFont(QFont("Segoe UI", font_size("title"), QFont.Weight.Bold))
        hdr.setStyleSheet(f"color:{c('t1')}; background:transparent;")
        hdr.setAlignment(_CENTER)
        lay.addWidget(hdr)

        msg = QLabel(note)
        msg.setFont(QFont("Segoe UI", font_size("label")))
        msg.setStyleSheet(f"color:{c('t3')}; background:transparent;")
        msg.setAlignment(_CENTER)
        lay.addWidget(msg)

        lay.addStretch()
