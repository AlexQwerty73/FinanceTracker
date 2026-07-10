"""
core/config.py — file paths and shared constants.
"""
from __future__ import annotations

from pathlib import Path

FINANCES_DIR = Path.home() / "OneDrive" / "Finances"

FILE_PATHS: dict[int, Path] = {
    2025: FINANCES_DIR / "Finances_2025.xlsx",
    2026: FINANCES_DIR / "Finances_2026.xlsx",
}
