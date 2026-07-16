"""
core/excel/registry.py — pick the right YearSchema for a given date.
Which years are supported, and which schema each one uses, comes from
core.settings (persisted, can grow at runtime as files are created via the
UI) rather than a fixed dict. A year's registered template id is either
one of the two built-in presets (routed to Schema2025/Schema2026) or a
custom template id (routed to DynamicSchema, looked up via
core.excel.template_model) — see core/settings.py, core/excel/
template_model.py and app/components/create_file_dialog.py.
"""
from __future__ import annotations

from datetime import date as Date

from .. import config, settings
from . import template_model
from .base import YearSchema
from .schema_2025 import Schema2025
from .schema_2026 import Schema2026
from .schema_dynamic import DynamicSchema

_BUILTIN_SCHEMA_CLASSES: dict[str, type[YearSchema]] = {
    settings.TEMPLATE_2025: Schema2025,
    settings.TEMPLATE_2026: Schema2026,
}

_instances: dict[int, YearSchema] = {}


def _is_resolvable(template_id: str) -> bool:
    return template_id in _BUILTIN_SCHEMA_CLASSES or template_model.get_template(template_id) is not None


def _resolvable_years() -> list[int]:
    return [year for year, template_id in settings.get_year_templates().items() if _is_resolvable(template_id)]


def _build_schema(year: int, template_id: str, path) -> YearSchema:
    if template_id in _BUILTIN_SCHEMA_CLASSES:
        return _BUILTIN_SCHEMA_CLASSES[template_id](path, year)
    custom = template_model.get_template(template_id)
    if custom is None:
        raise ValueError(f"Template '{template_id}' for year {year} no longer exists.")
    return DynamicSchema(path, year, custom)


def get_schema_for_date(d: Date) -> YearSchema:
    year = d.year
    templates_by_year = settings.get_year_templates()
    if year not in templates_by_year or not _is_resolvable(templates_by_year[year]):
        raise ValueError(
            f"No workbook template registered for year {year}. "
            f"Create a file for this year from the sidebar."
        )
    path = config.FILE_PATHS.get(year)
    if path is None or not path.exists():
        raise ValueError(f"No file yet for {year} — create one from the sidebar.")
    if year not in _instances or _instances[year].file_path != path:
        _instances[year] = _build_schema(year, templates_by_year[year], path)
    return _instances[year]


def supported_years() -> list[int]:
    return sorted(_resolvable_years())


def min_supported_period() -> tuple[int, int]:
    years = _resolvable_years()
    return (min(years), 1) if years else (9999, 1)


def max_supported_period() -> tuple[int, int]:
    years = _resolvable_years()
    return (max(years), 12) if years else (0, 12)
