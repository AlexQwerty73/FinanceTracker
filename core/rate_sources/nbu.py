"""
core/rate_sources/nbu.py — National Bank of Ukraine (NBU) public daily
exchange-rate history, no API key required. Used only to get UAH rates
(against USD/EUR/etc.) — ČNB's own daily fixing doesn't publish UAH at
all, so core/rate_fetcher.py triangulates CZK<->UAH through this source's
UAH<->USD rate plus ČNB's own CZK<->USD rate for the same day.

Independent of every other rate source: a change to NBU's endpoint or an
outage here only ever means "no UAH rate for that day" — it never
affects cnb.py or any currency it already provided.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from datetime import date as Date

URL = "https://bank.gov.ua/NBUStatService/v1/statdirectory/exchange"
TIMEOUT_SECONDS = 5
_USER_AGENT = "Mozilla/5.0"  # NBU's API otherwise 403s on requests with no User-Agent


def fetch_day(date: Date) -> dict[str, float] | None:
    """One HTTP GET — {currency_code: rate_to_uah} for every currency NBU
    published for that date, or None on failure. NBU already quotes "N
    UAH per 1 unit of currency" directly, no per-row unit normalization
    needed (unlike ČNB's Amount column). Never raises."""
    url = f"{URL}?date={date.strftime('%Y%m%d')}&json"
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as resp:
            raw = resp.read()
    except (urllib.error.URLError, TimeoutError, OSError):
        return None

    try:
        rows = json.loads(raw.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    if not isinstance(rows, list):
        return None

    rates: dict[str, float] = {}
    for row in rows:
        code = row.get("cc")
        rate = row.get("rate")
        if code and isinstance(rate, (int, float)) and rate > 0:
            rates[code] = float(rate)

    return rates or None
