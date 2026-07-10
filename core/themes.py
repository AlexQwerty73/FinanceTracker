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


def c(key: str) -> str:
    return _PALETTE[key]
