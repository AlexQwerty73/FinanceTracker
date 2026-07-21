"""
core/rate_sources/ — one file per external exchange-rate data source,
each exposing the same shape: fetch_day(date) -> {currency_code: rate} |
None. Deliberately kept independent of each other (and of PyQt) so a
broken/unreachable source only ever affects the currencies it alone was
responsible for — see core/rate_fetcher.py for how they're combined.
"""
