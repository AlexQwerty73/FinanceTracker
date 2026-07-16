"""
core/excel/template_model.py — Template: a user-configurable workbook
layout (which columns, in what order, plus the Category/Type/Payment
lists, which Type values mean income/expense/cash-transfer-in, and which
categories count as investing), used to generate brand-new files via
create_custom_workbook() and read them back via DynamicSchema — see
core/excel/templates.py and schema_dynamic.py.

A template can only pick from a fixed, closed set of column roles: nothing
in the app's logic (is_income_type, category grouping in the charts, etc.)
would know what to do with an unknown role, so "configurable" means
"which of these six, in what order" rather than truly arbitrary fields.

Persisted as JSON at ~/.financetracker/templates.json — a flat list of
serialized Template objects. Dependency-free (no import of core.config),
same reasoning as core/settings.py: the storage path is overridable for
tests by reassigning TEMPLATES_PATH before first use.
"""
from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path

ROLE_DATE = "date"
ROLE_CATEGORY = "category"
ROLE_TYPE = "type"
ROLE_AMOUNT = "amount"
ROLE_PAYMENT = "payment"
ROLE_NOTES = "notes"

ALL_ROLES = [ROLE_DATE, ROLE_CATEGORY, ROLE_TYPE, ROLE_AMOUNT, ROLE_PAYMENT, ROLE_NOTES]
REQUIRED_ROLES = {ROLE_CATEGORY, ROLE_TYPE, ROLE_AMOUNT}
OPTIONAL_ROLES = [r for r in ALL_ROLES if r not in REQUIRED_ROLES]

ROLE_LABELS = {
    ROLE_DATE: "Date",
    ROLE_CATEGORY: "Category",
    ROLE_TYPE: "Type",
    ROLE_AMOUNT: "Amount",
    ROLE_PAYMENT: "Payment type",
    ROLE_NOTES: "Notes",
}

TEMPLATES_DIR = Path.home() / ".financetracker"
TEMPLATES_PATH = TEMPLATES_DIR / "templates.json"


class TemplateValidationError(Exception):
    """Raised by Template.validate() — the message is meant to be shown
    directly to the user (e.g. in TemplateEditorDialog's status label)."""


@dataclass
class Template:
    id: str
    name: str
    columns: list[str]
    categories: list[str]
    types: list[str]
    income_type: str
    expense_type: str
    cash_in_type: str | None = None
    payment_types: list[str] | None = None
    invest_categories: list[str] = field(default_factory=list)

    @staticmethod
    def new_blank() -> "Template":
        return Template(
            id=f"custom-{uuid.uuid4().hex[:8]}",
            name="My Template",
            columns=[ROLE_CATEGORY, ROLE_TYPE, ROLE_AMOUNT, ROLE_NOTES],
            categories=["Food", "Transport", "Utilities", "Entertainment", "Other"],
            types=["Income", "Expense"],
            income_type="Income",
            expense_type="Expense",
            cash_in_type=None,
            payment_types=None,
            invest_categories=[],
        )

    def validate(self) -> None:
        missing = REQUIRED_ROLES - set(self.columns)
        if missing:
            labels = ", ".join(ROLE_LABELS[r] for r in missing)
            raise TemplateValidationError(f"Missing required column(s): {labels}.")
        if not self.name.strip():
            raise TemplateValidationError("Enter a template name.")
        if not self.categories:
            raise TemplateValidationError("Add at least one category.")
        if len(self.types) < 2:
            raise TemplateValidationError("Add at least two types (e.g. Income and Expense).")
        if self.income_type not in self.types:
            raise TemplateValidationError("Income type must be one of the types listed.")
        if self.expense_type not in self.types:
            raise TemplateValidationError("Expense type must be one of the types listed.")
        if self.income_type == self.expense_type:
            raise TemplateValidationError("Income and Expense must be different types.")
        if self.cash_in_type is not None:
            if self.cash_in_type not in self.types:
                raise TemplateValidationError("Cash-in type must be one of the types listed.")
            if self.cash_in_type in (self.income_type, self.expense_type):
                raise TemplateValidationError("Cash-in type must be different from Income and Expense.")
        if ROLE_PAYMENT in self.columns and not self.payment_types:
            raise TemplateValidationError("Add at least one payment type (e.g. Cash, Card).")
        if any(cat not in self.categories for cat in self.invest_categories):
            raise TemplateValidationError("Investment categories must be picked from the categories list.")

    def has_daily_dates(self) -> bool:
        return ROLE_DATE in self.columns


def _load_all() -> list[dict]:
    if not TEMPLATES_PATH.exists():
        return []
    try:
        return json.loads(TEMPLATES_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []


def _save_all(items: list[dict]) -> None:
    TEMPLATES_PATH.parent.mkdir(parents=True, exist_ok=True)
    TEMPLATES_PATH.write_text(json.dumps(items, indent=2), encoding="utf-8")


def list_templates() -> list[Template]:
    return [Template(**item) for item in _load_all()]


def get_template(template_id: str) -> Template | None:
    for t in list_templates():
        if t.id == template_id:
            return t
    return None


def save_template(template: Template) -> None:
    items = _load_all()
    items = [item for item in items if item["id"] != template.id]
    items.append(asdict(template))
    _save_all(items)


def delete_template(template_id: str) -> None:
    items = [item for item in _load_all() if item["id"] != template_id]
    _save_all(items)
