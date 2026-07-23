"""
dev_tests/_isolation.py — shared setup for every dev_tests/test_*.py
script: redirect settings.json/templates.json/rate_history.json to a
fresh temp directory *before* core.config is ever imported (its
module-level code seeds settings.json with the real hardcoded 2025/2026
defaults on first import if "files" is empty — see CLAUDE.md's "Known
gotchas" — importing config only after redirecting the paths, and then
immediately unregistering anything it seeded, keeps every test fully
synthetic and never touches the real OneDrive files or ~/.financetracker).

Each test script calls isolate() once, at the top, before any other
project import.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def isolate() -> Path:
    scratch = Path(tempfile.mkdtemp(prefix="financetracker_devtest_"))

    import core.settings as settings
    settings.SETTINGS_PATH = scratch / "settings.json"
    import core.excel.template_model as template_model
    template_model.TEMPLATES_PATH = scratch / "templates.json"
    import core.rate_history as rate_history
    rate_history.RATE_HISTORY_PATH = scratch / "rate_history.json"
    rate_history._cache = None

    import core.config as config  # triggers the real-defaults seed exactly once
    from core.excel import registry

    # Undo the seed immediately -- config.py's module-level code writes
    # 2025/2026 pointing at the real OneDrive files if "files" was empty,
    # which it always is on a brand-new scratch settings.json.
    for year_str, entry in list(settings.load().get("files", {}).items()):
        for candidate in list(entry["candidates"]):
            try:
                settings.unregister_candidate(int(year_str), candidate["path"])
            except ValueError:
                pass
    config.FILE_PATHS.clear()
    registry.supported_years = lambda: sorted(int(y) for y in settings.get_year_templates().keys())

    return scratch
