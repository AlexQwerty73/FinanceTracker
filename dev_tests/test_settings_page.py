"""
dev_tests/test_settings_page.py — SettingsPage is a full page (not a
QDialog); saving a template on its Templates tab must immediately refresh
the Create New File tab's Layout combo — the live-refresh wiring this
needed once Settings became one persistent instance instead of a dialog
recreated fresh on every open (see CLAUDE.md's "Settings becomes a full
page" round).

Run directly: python dev_tests/test_settings_page.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dev_tests._isolation import isolate

_SCRATCH = isolate()

from PyQt6.QtWidgets import QApplication, QDialog
_app = QApplication.instance() or QApplication([])

from app.pages.settings_page import SettingsPage


def run(scratch: Path) -> None:
    sp = SettingsPage()
    assert not isinstance(sp, QDialog)
    assert [sp._tabs.tabText(i) for i in range(sp._tabs.count())] == ["Files", "Create New File", "Templates"]

    before_count = sp._create_widget._template_combo.count()
    tp = sp._templates_widget
    tp._name_field.setText("My Dev-Test Layout")
    tp._on_save()  # Template.new_blank()'s defaults already give Income/Expense roles
    after_count = sp._create_widget._template_combo.count()
    assert after_count == before_count + 1, (before_count, after_count)
    labels = [sp._create_widget._template_combo.itemText(i) for i in range(after_count)]
    assert any("My Dev-Test Layout" in lbl for lbl in labels)

    # "+ Design a new template..." switches to the Templates tab in place.
    sp._tabs.setCurrentIndex(1)
    idx = sp._create_widget._template_combo.findData("__new_template__")
    sp._create_widget._template_combo.setCurrentIndex(idx)
    assert sp._tabs.currentWidget() is sp._templates_widget

    print("test_settings_page: ALL CHECKS PASSED")


if __name__ == "__main__":
    run(_SCRATCH)
