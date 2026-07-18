"""
core/themes.py — colour palette (dark, single theme for the MVP).
"""
from __future__ import annotations

_PALETTE: dict[str, str] = {
    "bg":       "#1c1c30",
    "panel_bg": "rgba(255,255,255,7)",
    "panel_bd": "rgba(255,255,255,13)",
    "ac":       "#f0a500",
    "t1":       "#f5f0e8",
    "t2":       "#9898bc",
    "t3":       "#6870a0",
    "t_ph":     "#4a4a72",
    "in_bg":    "rgba(255,255,255,9)",
    "in_bd":    "rgba(255,255,255,16)",
    "btn_bg":   "rgba(240,165,0,22)",
    "btn_bd":   "rgba(240,165,0,45)",
    "btn_hbg":  "rgba(240,165,0,38)",
    "income_c":  "#50d878",
    "expense_c": "#ff7070",
    "invest_c":  "#80b8ff",
    "err_c":     "#ff6b6b",
    "sep":       "rgba(255,255,255,12)",
    "chart_bg":   "#222236",
    "chart_line": "#3a3a58",
}

# Fixed-order categorical hues for multi-category charts (pies), distinct
# from the semantic income/expense/invest colors used elsewhere. Assigned in
# order, never cycled; the last slot is reserved for the "Other" bucket.
CATEGORICAL: list[str] = [
    "#f0a500",  # gold
    "#6ca6f0",  # blue
    "#e07bb0",  # magenta
    "#9f8ef0",  # violet
    "#4fc9c2",  # teal
    "#f0834a",  # orange
    "#cbb26a",  # sand
]
CATEGORICAL_OTHER = "#7a7f99"  # muted gray, reserved for the "Other" bucket

# Discrete (bucketed, not a smooth gradient) sequential scale for the
# calendar heatmap — 5 steps: no activity, then 4 quartile levels rising
# from muted gold to a hot orange-red, chosen for strong contrast between
# adjacent buckets so activity actually pops out (a smooth gradient made
# most cells look like near-indistinguishable shades of the same brown).
HEATMAP_BUCKETS: list[str] = ["#22223a", "#7a5f10", "#c98500", "#f0a500", "#ff6a2b"]


def c(key: str) -> str:
    return _PALETTE[key]


# Design tokens — the small set of radius/font/height values every
# component should draw from, instead of a fresh magic number per call
# site. Collapses what used to be an ad hoc spread (radii 4/5/6/8/10/12/13/14,
# font sizes 8-16 with no scale, input heights split 30px/34px) into one
# source of truth. Palette/semantic colors above are unaffected.
RADIUS: dict[str, int] = {"sm": 6, "md": 8, "lg": 10, "xl": 14}

FONT: dict[str, int] = {
    "micro": 8,     # chart tick labels, tiny tags
    "label": 9,     # field labels, helper/status text
    "body": 10,     # default list/table cell text
    "section": 11,  # card/section headers, stat-chip values
    "dialog": 13,   # modal dialog headers
    "title": 14,    # page-level titles (TopBar month title, page headers)
    "stat": 16,     # big numeric readouts (Dashboard tiles, stat chips)
}

FIELD_HEIGHT = 32  # QLineEdit/QComboBox/QDateEdit — was split 30px/34px by file


def radius(key: str) -> int:
    return RADIUS[key]


def font_size(key: str) -> int:
    return FONT[key]
