"""
core/format.py — shared display formatting.
"""
from __future__ import annotations


def fmt_amount(v: float) -> str:
    return f"{v:,.2f} Kč"
