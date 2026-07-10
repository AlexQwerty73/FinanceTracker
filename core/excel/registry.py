"""
core/excel/registry.py — pick the right YearSchema for a given date.
To support a new year, add a schema module and register it in YEAR_SCHEMAS.
"""
from __future__ import annotations

from datetime import date as Date

from ..config import FILE_PATHS
from .base import YearSchema
from .schema_2025 import Schema2025
from .schema_2026 import Schema2026

YEAR_SCHEMAS: dict[int, type[YearSchema]] = {
    2025: Schema2025,
    2026: Schema2026,
}

_instances: dict[int, YearSchema] = {}


def get_schema_for_date(d: Date) -> YearSchema:
    year = d.year
    if year not in YEAR_SCHEMAS:
        raise ValueError(
            f"No workbook schema registered for year {year}. "
            f"Add core/excel/schema_{year}.py and register it in registry.YEAR_SCHEMAS."
        )
    if year not in _instances:
        _instances[year] = YEAR_SCHEMAS[year](FILE_PATHS[year], year)
    return _instances[year]


def supported_years() -> list[int]:
    return sorted(YEAR_SCHEMAS)


def min_supported_period() -> tuple[int, int]:
    return (min(YEAR_SCHEMAS), 1)


def max_supported_period() -> tuple[int, int]:
    return (max(YEAR_SCHEMAS), 12)
