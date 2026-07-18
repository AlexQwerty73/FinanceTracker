"""
app/components/topbar.py — TopBar: month navigation, Add Transaction, and a
last-refreshed indicator, shared above whichever page (Dashboard,
Transactions) is currently shown so both stay on the same viewed month.
"""
from __future__ import annotations

from datetime import date as Date, datetime

from PyQt6.QtCore import QPoint, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QCursor, QFont
from PyQt6.QtWidgets import QDialog, QGridLayout, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from core import config
from core.excel import registry
from core.excel.base import MONTH_NAMES
from core.icons import icon
from core.themes import c, font_size, radius

from .transaction_dialog import TransactionDialog
from .widgets import nav_chip_style, primary_button


class _MonthPicker(QDialog):
    """A calendar-style month/year popup — flipping year by year and
    clicking a month directly is much faster than stepping through the
    prev/next arrows one month at a time to reach a date far away."""

    month_picked = pyqtSignal(int, int)  # year, month

    def __init__(self, year: int, month: int, parent=None):
        super().__init__(parent, Qt.WindowType.Popup)
        self._year = year
        self._active = (year, month)
        # A frameless Popup window won't paint a QSS `background` unless
        # explicitly told to. It also needs an *opaque* color here, unlike
        # the cards elsewhere in the app: panel_bg is an intentionally
        # near-transparent overlay meant to sit within the same widget tree
        # as the app's dark window background, but this popup is its own
        # standalone top-level surface with nothing dark to composite over
        # — panel_bg here would render as barely-visible white.
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(f"""
            QDialog {{ background:{c('chart_bg')}; border:1px solid {c('panel_bd')}; border-radius:{radius('lg')}px; }}
        """)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 12, 14, 14)
        lay.setSpacing(10)

        year_row = QHBoxLayout()
        prev_y = QPushButton("<")
        prev_y.setFixedSize(26, 26)
        prev_y.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        prev_y.clicked.connect(lambda: self._shift_year(-1))
        self._year_lbl = QLabel(str(year))
        self._year_lbl.setFont(QFont("Segoe UI", font_size("section"), QFont.Weight.Bold))
        self._year_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._year_lbl.setStyleSheet(f"color:{c('t1')}; background:transparent;")
        next_y = QPushButton(">")
        next_y.setFixedSize(26, 26)
        next_y.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        next_y.clicked.connect(lambda: self._shift_year(1))
        for btn in (prev_y, next_y):
            btn.setStyleSheet(nav_chip_style(False, radius_key="sm"))
        year_row.addWidget(prev_y)
        year_row.addWidget(self._year_lbl, 1)
        year_row.addWidget(next_y)
        lay.addLayout(year_row)

        grid = QGridLayout()
        grid.setSpacing(6)
        self._month_btns: list[QPushButton] = []
        for i, name in enumerate(MONTH_NAMES):
            btn = QPushButton(name[:3])
            btn.setFixedSize(56, 30)
            btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            btn.clicked.connect(lambda _checked, m=i + 1: self._pick(m))
            grid.addWidget(btn, i // 3, i % 3)
            self._month_btns.append(btn)
        lay.addLayout(grid)

        self._refresh()

    def _refresh(self) -> None:
        self._year_lbl.setText(str(self._year))
        floor = registry.min_supported_period()
        ceiling = registry.max_supported_period()
        for i, btn in enumerate(self._month_btns):
            m = i + 1
            in_range = floor <= (self._year, m) <= ceiling
            btn.setEnabled(in_range)
            is_selected = in_range and (self._year, m) == self._active
            btn.setStyleSheet(nav_chip_style(is_selected, radius_key="sm"))

    def _shift_year(self, delta: int) -> None:
        self._year += delta
        self._refresh()

    def _pick(self, month: int) -> None:
        self.month_picked.emit(self._year, month)
        self.close()


def _nav_btn(text: str) -> QPushButton:
    btn = QPushButton(text)
    btn.setFixedSize(30, 28)
    btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
    btn.setStyleSheet(nav_chip_style(False, radius_key="sm"))
    return btn


def _ghost_btn(text: str) -> QPushButton:
    btn = QPushButton(text)
    btn.setFixedHeight(28)
    btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
    btn.setStyleSheet(f"""
        QPushButton {{ background:transparent; color:{c('t2')};
            border:1px solid {c('in_bd')}; border-radius:{radius('sm')}px; padding:0 10px; }}
        QPushButton:hover {{ color:{c('ac')}; border-color:{c('ac')}; }}
    """)
    return btn


class TopBar(QWidget):
    period_changed = pyqtSignal(int, int)  # year, month
    transaction_saved = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        today = Date.today()
        self.year = today.year
        self.month = today.month

        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)

        self._prev_btn = _nav_btn("<")
        self._prev_btn.clicked.connect(self._go_prev)
        lay.addWidget(self._prev_btn)

        self._title = QPushButton("")
        self._title.setFont(QFont("Segoe UI", font_size("title"), QFont.Weight.Bold))
        self._title.setIcon(icon("chevron-down", c("t1")))
        self._title.setIconSize(QSize(14, 14))
        self._title.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._title.setToolTip("Click to pick a month/year directly")
        self._title.setStyleSheet(f"""
            QPushButton {{ color:{c('t1')}; background:transparent; border:none; text-align:left; }}
            QPushButton:hover {{ color:{c('ac')}; }}
        """)
        self._title.clicked.connect(self._open_month_picker)
        lay.addWidget(self._title, 1)

        self._file_lbl = QLabel("")
        self._file_lbl.setFont(QFont("Segoe UI", font_size("micro")))
        self._file_lbl.setStyleSheet(f"color:{c('t3')}; background:transparent;")
        self._file_lbl.setToolTip("The file currently active for this year — change it from ⚙ Manage files")
        lay.addWidget(self._file_lbl)

        self._next_btn = _nav_btn(">")
        self._next_btn.clicked.connect(self._go_next)
        lay.addWidget(self._next_btn)

        today_btn = _ghost_btn("Today")
        today_btn.clicked.connect(self._go_today)
        lay.addWidget(today_btn)

        self._updated_lbl = QLabel("")
        self._updated_lbl.setFont(QFont("Segoe UI", font_size("micro")))
        self._updated_lbl.setStyleSheet(f"color:{c('t3')}; background:transparent;")
        lay.addWidget(self._updated_lbl)

        refresh_btn = _ghost_btn("Refresh")
        refresh_btn.clicked.connect(lambda: self.period_changed.emit(self.year, self.month))
        lay.addWidget(refresh_btn)

        add_btn = primary_button("+ Add Transaction")
        add_btn.clicked.connect(self._on_add)
        lay.addWidget(add_btn)

        self._update_title()

    def _update_title(self) -> None:
        self._title.setText(f"{MONTH_NAMES[self.month - 1]} {self.year}")
        active_path = config.FILE_PATHS.get(self.year)
        self._file_lbl.setText(active_path.name if active_path else "")
        self._prev_btn.setEnabled((self.year, self.month) > registry.min_supported_period())
        self._next_btn.setEnabled((self.year, self.month) < registry.max_supported_period())

    def refresh_active_file_label(self) -> None:
        """Re-reads config.FILE_PATHS for the viewed year — call after the
        active file for a year may have changed (FileSelectionDialog),
        since that doesn't otherwise trigger _update_title()."""
        active_path = config.FILE_PATHS.get(self.year)
        self._file_lbl.setText(active_path.name if active_path else "")

    def mark_updated(self) -> None:
        self._updated_lbl.setText(f"Updated {datetime.now().strftime('%H:%M:%S')}")

    def _go_prev(self) -> None:
        y, m = self.year, self.month - 1
        if m == 0:
            y, m = y - 1, 12
        if (y, m) < registry.min_supported_period():
            return
        self.year, self.month = y, m
        self._update_title()
        self.period_changed.emit(self.year, self.month)

    def _go_next(self) -> None:
        y, m = self.year, self.month + 1
        if m == 13:
            y, m = y + 1, 1
        if (y, m) > registry.max_supported_period():
            return
        self.year, self.month = y, m
        self._update_title()
        self.period_changed.emit(self.year, self.month)

    def _go_today(self) -> None:
        today = Date.today()
        self.year, self.month = today.year, today.month
        self._update_title()
        self.period_changed.emit(self.year, self.month)

    def _open_month_picker(self) -> None:
        picker = _MonthPicker(self.year, self.month, parent=self)
        picker.month_picked.connect(self._on_month_picked)
        pos = self._title.mapToGlobal(QPoint(0, self._title.height()))
        picker.move(pos)
        picker.show()

    def _on_month_picked(self, year: int, month: int) -> None:
        if not (registry.min_supported_period() <= (year, month) <= registry.max_supported_period()):
            return
        self.year, self.month = year, month
        self._update_title()
        self.period_changed.emit(self.year, self.month)

    def _on_add(self) -> None:
        dlg = TransactionDialog(parent=self)
        if dlg.exec():
            self.transaction_saved.emit()
