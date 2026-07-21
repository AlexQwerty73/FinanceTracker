"""
core/rate_sources/cnb.py — Czech National Bank (ČNB) public daily
exchange-rate fixing, no API key required. Covers most major currencies
directly in CZK, but notably NOT UAH — see rate_sources/nbu.py and the
triangulation in core/rate_fetcher.py for that one.

Independent of every other rate source: a change to ČNB's endpoint or an
outage here never affects nbu.py or any other source module.
"""
from __future__ import annotations

import urllib.error
import urllib.request
from datetime import date as Date

URL = (
    "https://www.cnb.cz/en/financial-markets/foreign-exchange-market/"
    "central-bank-exchange-rate-fixing/central-bank-exchange-rate-fixing/daily.txt"
)
TIMEOUT_SECONDS = 5


def fetch_day(date: Date) -> dict[str, float] | None:
    """One HTTP GET — {currency_code: rate_to_czk} for every currency ČNB
    published for that exact date, or None if the request failed or the
    date has no data at all (weekend/holiday/future date). Never raises —
    any failure here is just "this source has nothing for today"."""
    url = f"{URL}?date={date.strftime('%d.%m.%Y')}"
    try:
        with urllib.request.urlopen(url, timeout=TIMEOUT_SECONDS) as resp:
            raw = resp.read()
    except (urllib.error.URLError, TimeoutError, OSError):
        return None

    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = raw.decode("cp1250", errors="replace")

    lines = text.strip().splitlines()
    if len(lines) < 2:
        return None

    rates: dict[str, float] = {}
    for line in lines[2:]:  # line 0 = date header, line 1 = column header
        parts = line.split("|")
        if len(parts) != 5:
            continue
        _country, _name, amount_str, code, rate_str = parts
        try:
            amount = float(amount_str)
            rate = float(rate_str)
        except ValueError:
            continue
        if amount > 0:
            rates[code.strip()] = rate / amount  # normalize to "per 1 unit"

    return rates or None
