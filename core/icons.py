"""
core/icons.py — loads the app's own small SVG icon set (assets/icons/*.svg)
as recolorable QIcons, replacing emoji/glyph-as-icon usage (emoji can render
as blank "tofu" glyphs if the environment lacks a color-emoji font). Each
SVG carries a `{COLOR}` placeholder instead of a baked-in color so the same
file serves every state (normal/hover/selected) a caller needs.
"""
from __future__ import annotations

import sys
from functools import lru_cache
from pathlib import Path

from PyQt6.QtCore import QByteArray, QSize, Qt
from PyQt6.QtGui import QIcon, QPainter, QPixmap
from PyQt6.QtSvg import QSvgRenderer


def _icons_dir() -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    return base / "assets" / "icons"


@lru_cache(maxsize=None)
def _svg_template(name: str) -> str:
    return (_icons_dir() / f"{name}.svg").read_text(encoding="utf-8")


@lru_cache(maxsize=None)
def icon(name: str, color: str, size: int = 20) -> QIcon:
    """Render assets/icons/<name>.svg with {COLOR} substituted, at `size`
    device-independent pixels. Cached per (name, color, size) — icons are
    reused across refreshes/rebuilds of the same widgets."""
    svg = _svg_template(name).replace("{COLOR}", color)
    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    pixmap = QPixmap(QSize(size, size))
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    renderer.render(painter)
    painter.end()
    return QIcon(pixmap)
