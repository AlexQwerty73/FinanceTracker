"""
core/format.py — shared display formatting.
"""
from __future__ import annotations


_CURRENCY_SYMBOLS = {"CZK": "Kč"}


def fmt_amount(v: float, currency: str | None = None) -> str:
    symbol = _CURRENCY_SYMBOLS.get(currency, currency) if currency else "Kč"
    return f"{v:,.2f} {symbol}"
