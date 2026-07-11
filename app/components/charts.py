"""
app/components/charts.py — matplotlib charts embedded in the app.

Category breakdown pies are true multi-category identity charts, so they
use the app's fixed-order categorical palette (never color-by-value) with a
legend + on-wedge percentages as secondary encoding. Income vs Expense and
the balance/cash-flow charts are a fixed, small, semantically meaningful
pair/sign (income=green, expense=red; above/below zero), matching the stat
tiles and InvestTracker's buy/sell convention — position and a zero
baseline carry identity too, so it never rests on color alone. The category
breakdown bar and the calendar heatmap are single-series magnitude, so they
get one hue each (never color-per-category there — that would spend the
identity channel re-encoding what length/intensity already shows).

Every chart redraws via draw_idle() (not draw()) so Qt can coalesce rapid
successive updates — e.g. flipping through months fires several charts'
update_data() back to back — into a single repaint instead of blocking the
UI thread once per chart. Every chart also wires a hover tooltip: a bare
mark carries no value on its own without pointing at a number.
"""
from __future__ import annotations

from datetime import date as _date, timedelta as _timedelta

import matplotlib
matplotlib.use("QtAgg")

import matplotlib.patheffects as patheffects
import numpy as np
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.colors import ListedColormap
from matplotlib.figure import Figure
from PyQt6.QtCore import QPoint
from PyQt6.QtWidgets import QSizePolicy, QToolTip

from core.excel.base import MONTH_NAMES
from core.format import fmt_amount
from core.themes import CATEGORICAL, CATEGORICAL_OTHER, HEATMAP_BUCKETS, c

_FONT = "Segoe UI"
_TOP_CATEGORIES = 7  # token ceiling; the tail folds into "Other"


def _style_axes(ax) -> None:
    for spine in ("top", "right", "left"):
        ax.spines[spine].set_visible(False)
    ax.spines["bottom"].set_color(c("chart_line"))
    ax.tick_params(colors=c("t2"), labelsize=8, length=0)
    for label in ax.get_xticklabels() + ax.get_yticklabels():
        label.set_fontfamily(_FONT)


def _empty_state(ax, text: str) -> None:
    ax.text(0.5, 0.5, text, ha="center", va="center",
             color=c("t3"), fontsize=9, fontfamily=_FONT, transform=ax.transAxes)
    ax.set_xticks([])
    ax.set_yticks([])


def _fold_other(breakdown: dict[str, float]) -> list[tuple[str, float]]:
    items = sorted(((k, v) for k, v in breakdown.items() if v > 0), key=lambda kv: kv[1], reverse=True)
    if len(items) <= _TOP_CATEGORIES:
        return items

    head, tail = items[:_TOP_CATEGORIES], items[_TOP_CATEGORIES:]
    other_total = sum(v for _, v in tail)
    # A real category can itself be named "Other" (e.g. some years' sheets
    # have one) — if it lands in the top 7, folding the 8th+ overflow into
    # its own "Other" bucket would otherwise produce two identically
    # labeled, identically colored wedges instead of one merged slice.
    kept = []
    for k, v in head:
        if k == "Other":
            other_total += v
        else:
            kept.append((k, v))
    kept.append(("Other", other_total))
    return kept


class _HoverCanvas(FigureCanvasQTAgg):
    """Base for charts with a hover tooltip: subclasses implement
    _hit_test(event) -> str | None, returning the tooltip text for the
    mark under the cursor (or None to hide the tooltip)."""

    def __init__(self, fig: Figure):
        super().__init__(fig)
        self.setMouseTracking(True)
        self.mpl_connect("motion_notify_event", self._on_hover)
        self.mpl_connect("figure_leave_event", lambda _e: QToolTip.hideText())

    def wheelEvent(self, event) -> None:
        # matplotlib's Qt backend always accepts wheel events (to fire its
        # own unused "scroll_event"), which silently swallows touchpad
        # scrolling whenever the cursor is over a chart instead of letting
        # it bubble up to the page's QScrollArea. None of these charts have
        # scroll-to-zoom wired up, so just let the page scroll instead.
        event.ignore()

    def _hit_test(self, event) -> str | None:
        return None

    def _on_hover(self, event) -> None:
        text = self._hit_test(event) if event.inaxes is not None else None
        if text:
            # event.x/y are matplotlib's device-pixel canvas coordinates
            # (backend_qtagg scales them by devicePixelRatio for HiDPI);
            # mapToGlobal/height() expect Qt's logical-pixel space, so
            # without this conversion the tooltip lands far from the
            # cursor on any display with fractional scaling.
            ratio = self.devicePixelRatioF() or 1.0
            qt_x = event.x / ratio
            qt_y = self.height() - event.y / ratio
            pos = self.mapToGlobal(QPoint(int(qt_x), int(qt_y)))
            QToolTip.showText(pos, text, self)
        else:
            QToolTip.hideText()


class CategoryBreakdownChart(_HoverCanvas):
    """Horizontal bar chart: expense amount per category for one month."""

    def __init__(self, parent=None):
        fig = Figure(figsize=(4, 2.6), dpi=100, facecolor=c("chart_bg"))
        super().__init__(fig)
        if parent is not None:
            self.setParent(parent)
        self.setStyleSheet("background:transparent;")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumHeight(180)
        self._ax = fig.add_subplot(111, facecolor=c("chart_bg"))
        fig.subplots_adjust(left=0.32, right=0.82, top=0.95, bottom=0.08)
        self._bars = []
        self._items: list[tuple[str, float]] = []

    def update_data(self, breakdown: dict[str, float]) -> None:
        ax = self._ax
        ax.clear()
        ax.set_facecolor(c("chart_bg"))

        items = _fold_other(breakdown)
        items.reverse()  # largest at top
        self._items = items
        self._bars = []

        if not items:
            _empty_state(ax, "No expenses this month")
        else:
            labels = [k for k, _ in items]
            values = [v for _, v in items]
            self._bars = ax.barh(labels, values, color=c("ac"), height=0.6)
            max_v = max(values)
            for bar, value in zip(self._bars, values):
                ax.text(bar.get_width() + max_v * 0.02, bar.get_y() + bar.get_height() / 2,
                        f"{value:,.0f}", va="center", ha="left",
                        color=c("t2"), fontsize=8, fontfamily=_FONT)
            ax.set_xlim(0, max_v * 1.45)
            ax.set_xticks([])

        _style_axes(ax)
        self.draw_idle()

    def _hit_test(self, event) -> str | None:
        for bar, (label, value) in zip(self._bars, self._items):
            contained, _ = bar.contains(event)
            if contained:
                return f"{label}: {fmt_amount(value)}"
        return None


class CategoryPieChart(_HoverCanvas):
    """Pie chart with on-wedge percentages: share of total per category.
    True multi-category identity data, so it uses the fixed-order
    categorical palette (never color-by-value) plus a legend."""

    def __init__(self, parent=None):
        fig = Figure(figsize=(4, 2.8), dpi=100, facecolor=c("chart_bg"))
        super().__init__(fig)
        if parent is not None:
            self.setParent(parent)
        self.setStyleSheet("background:transparent;")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumHeight(200)
        self._ax = fig.add_subplot(111, facecolor=c("chart_bg"))
        fig.subplots_adjust(left=0.02, right=0.58, top=0.95, bottom=0.05)
        self._wedges = []
        self._items: list[tuple[str, float]] = []

    def update_data(self, breakdown: dict[str, float]) -> None:
        ax = self._ax
        ax.clear()
        ax.set_facecolor(c("chart_bg"))
        ax.axis("off")

        items = _fold_other(breakdown)
        self._items = items
        self._wedges = []
        if not items:
            _empty_state(ax, "No data")
            self.draw_idle()
            return

        labels = [k for k, _ in items]
        values = [v for _, v in items]
        colors = []
        for i, label in enumerate(labels):
            if label == "Other":
                colors.append(CATEGORICAL_OTHER)
            else:
                colors.append(CATEGORICAL[i % len(CATEGORICAL)])

        wedges, _texts, autotexts = ax.pie(
            values, colors=colors, autopct="%1.0f%%", pctdistance=0.72,
            startangle=90, counterclock=False,
            wedgeprops={"linewidth": 2, "edgecolor": c("chart_bg")},
            textprops={"fontsize": 8, "fontfamily": _FONT},
        )
        self._wedges = wedges
        for at in autotexts:
            at.set_color("white")
            at.set_fontweight("bold")
            at.set_path_effects([patheffects.withStroke(linewidth=2.5, foreground=c("chart_bg"))])

        legend = ax.legend(
            wedges, labels, loc="center left", bbox_to_anchor=(1.02, 0.5),
            frameon=False, fontsize=8,
        )
        for text in legend.get_texts():
            text.set_color(c("t2"))
            text.set_fontfamily(_FONT)

        self.draw_idle()

    def _hit_test(self, event) -> str | None:
        total = sum(v for _, v in self._items) or 1.0
        for wedge, (label, value) in zip(self._wedges, self._items):
            contained, _ = wedge.contains(event)
            if contained:
                return f"{label}: {fmt_amount(value)} ({value / total * 100:.1f}%)"
        return None


class RunningBalanceChart(_HoverCanvas):
    """Line chart: cumulative balance day-by-day within a month."""

    def __init__(self, parent=None):
        fig = Figure(figsize=(4, 2.2), dpi=100, facecolor=c("chart_bg"))
        super().__init__(fig)
        if parent is not None:
            self.setParent(parent)
        self.setStyleSheet("background:transparent;")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumHeight(160)
        self._ax = fig.add_subplot(111, facecolor=c("chart_bg"))
        fig.subplots_adjust(left=0.12, right=0.95, top=0.92, bottom=0.15)
        self._points: list[tuple[int, float]] = []

    def update_data(self, points: list[tuple[int, float]] | None) -> None:
        """points: [(day, cumulative_balance), ...] sorted by day, or None
        if this year has no daily dates to plot (e.g. the legacy 2025 schema)."""
        ax = self._ax
        ax.clear()
        ax.set_facecolor(c("chart_bg"))
        self._points = points or []

        if points is None:
            _empty_state(ax, "No daily dates in this year's data")
            _style_axes(ax)
            self.draw_idle()
            return
        if not points:
            _empty_state(ax, "No transactions this month")
            _style_axes(ax)
            self.draw_idle()
            return

        days = [p[0] for p in points]
        balances = [p[1] for p in points]
        ax.axhline(0, color=c("chart_line"), linewidth=1)
        ax.plot(days, balances, color=c("ac"), linewidth=2, marker="o", markersize=3)
        ax.fill_between(days, balances, 0, color=c("ac"), alpha=0.12)
        ax.set_xlim(min(days) - 0.5, max(days) + 0.5)

        _style_axes(ax)
        self.draw_idle()

    def _hit_test(self, event) -> str | None:
        if not self._points or event.xdata is None:
            return None
        nearest = min(self._points, key=lambda p: abs(p[0] - event.xdata))
        day, balance = nearest
        if abs(day - event.xdata) > 1.5:
            return None
        return f"Day {day}: {fmt_amount(balance)}"


class BalanceLineChart(_HoverCanvas):
    """Line chart, one axis a continuous time scale, the other the
    (typically cumulative) balance — a standard single-series time series,
    one hue, with a zero baseline. Used for both "balance over time" and
    "cash flow" (the same shape, a running total, just scoped to Cash
    transactions for the latter).

    The x position of each point is a real day-offset supplied by the
    caller (not just its index in the list), so a gap of five months
    between two points stretches proportionally across the axis instead of
    being squeezed into a single equal-width step next to a gap of five
    days."""

    def __init__(self, parent=None):
        fig = Figure(figsize=(7, 2.6), dpi=100, facecolor=c("chart_bg"))
        super().__init__(fig)
        if parent is not None:
            self.setParent(parent)
        self.setStyleSheet("background:transparent;")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumHeight(200)
        self._ax = fig.add_subplot(111, facecolor=c("chart_bg"))
        fig.subplots_adjust(left=0.07, right=0.97, top=0.92, bottom=0.18)
        self._labels: list[str] = []
        self._values: list[float] = []
        self._x: list[float] = []

    def update_data(
        self, points: list[tuple[str, float, float]], x_range: tuple[float, float] | None = None,
    ) -> None:
        """points: [(label, value, x_position), ...], oldest first, where
        x_position is a real day-offset (or other continuous measure) so
        spacing reflects actual elapsed time between points. Pass x_range
        (the other chart's data span) when this chart should line up with a
        companion chart above/below it even if its own data covers less —
        otherwise each chart's x-axis fits only its own data and the same
        calendar date lands at a different horizontal position in each."""
        ax = self._ax
        ax.clear()
        ax.set_facecolor(c("chart_bg"))
        self._labels = [p[0] for p in points]
        self._values = [p[1] for p in points]
        self._x = [p[2] for p in points]

        if not points:
            _empty_state(ax, "No data")
            _style_axes(ax)
            if x_range is not None:
                ax.set_xlim(*x_range)
            self.draw_idle()
            return

        ax.axhline(0, color=c("chart_line"), linewidth=1)
        ax.plot(self._x, self._values, color=c("ac"), linewidth=2, marker="o", markersize=4)
        ax.fill_between(self._x, self._values, 0, color=c("ac"), alpha=0.1)

        # Hard-set xlim from the actual data rather than trusting autoscale:
        # matplotlib recomputes autoscale lazily at draw time (and depends
        # on axes.autoscale being on), so a stale xlim from a *wider*
        # previous period (e.g. switching from "All time" to "Last 6
        # months") could otherwise stick around and squeeze the new,
        # narrower data into the left part of the axes.
        if x_range is not None:
            ax.set_xlim(*x_range)
        else:
            x_min, x_max = min(self._x), max(self._x)
            pad = (x_max - x_min) * 0.02 or 1
            ax.set_xlim(x_min - pad, x_max + pad)
        y_min, y_max = min(0, min(self._values)), max(0, max(self._values))
        y_pad = (y_max - y_min) * 0.08 or 1
        ax.set_ylim(y_min - y_pad, y_max + y_pad)

        # Thin x-tick labels when there are many points (e.g. daily
        # granularity over a year) — hover still works on every point.
        step = max(1, len(points) // 12)
        tick_idx = list(range(0, len(points), step))
        ax.set_xticks([self._x[i] for i in tick_idx])
        rotate = len(tick_idx) > 8
        ax.set_xticklabels(
            [self._labels[i] for i in tick_idx], rotation=45 if rotate else 0, ha="right" if rotate else "center"
        )
        ax.set_yticks([])

        _style_axes(ax)
        self.draw_idle()

    def _hit_test(self, event) -> str | None:
        if not self._values or event.xdata is None:
            return None
        nearest = min(range(len(self._x)), key=lambda i: abs(self._x[i] - event.xdata))
        span = (max(self._x) - min(self._x)) or 1
        gaps = [b - a for a, b in zip(self._x, self._x[1:])] or [span]
        tolerance = max(span * 0.02, (sum(gaps) / len(gaps)) * 0.6)
        if abs(self._x[nearest] - event.xdata) > tolerance:
            return None
        return f"{self._labels[nearest]}: {fmt_amount(self._values[nearest])}"


class CalendarHeatmap(_HoverCanvas):
    """True GitHub-style calendar heatmap: columns = weeks of the year, rows
    = weekday (Mon..Sun), color = a discrete 5-step bucket (none / 4
    quartile levels of that day's expenses) — bucketed rather than a smooth
    gradient so activity actually stands out instead of blurring into
    near-identical shades. Magnitude, so one hue family, never
    color-per-day-of-week."""

    def __init__(self, parent=None):
        fig = Figure(figsize=(10, 2.4), dpi=100, facecolor=c("chart_bg"))
        super().__init__(fig)
        if parent is not None:
            self.setParent(parent)
        self.setStyleSheet("background:transparent;")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumHeight(220)
        self._ax = fig.add_subplot(111, facecolor=c("chart_bg"))
        fig.subplots_adjust(left=0.04, right=0.995, top=0.88, bottom=0.05)
        self._daily: dict[tuple[int, int], float] | None = None
        self._year = 0
        self._cell_info: dict[tuple[int, int], tuple[int, int, float]] = {}  # (weekday,week) -> (month,day,amount)

    def update_data(
        self, daily: dict[tuple[int, int], float] | None, year: int, end_date: _date | None = None,
    ) -> None:
        """daily: {(month, day): amount}, or None if this year has no daily
        dates to plot (e.g. the legacy 2025 schema). end_date caps the grid
        at that day (e.g. today, for the current year) instead of always
        reserving space out to Dec 31 — otherwise a still-in-progress year
        leaves most of the chart blank instead of using the full width for
        the days that actually happened."""
        ax = self._ax
        ax.clear()
        ax.set_facecolor(c("chart_bg"))
        self._daily = daily
        self._year = year
        self._cell_info = {}

        if daily is None:
            _empty_state(ax, "No daily dates in this year's data")
            ax.set_xticks([])
            ax.set_yticks([])
            self.draw_idle()
            return

        jan1 = _date(year, 1, 1)
        last_day = min(end_date, _date(year, 12, 31)) if end_date else _date(year, 12, 31)
        n_days = (last_day - jan1).days + 1
        jan1_weekday = jan1.weekday()  # Monday = 0
        n_weeks = (jan1_weekday + n_days + 6) // 7

        nonzero = sorted(v for v in daily.values() if v > 0)

        def _threshold(pct: float) -> float:
            idx = min(len(nonzero) - 1, int(pct * len(nonzero)))
            return nonzero[idx]

        thresholds = (_threshold(0.25), _threshold(0.50), _threshold(0.75)) if nonzero else (1.0, 2.0, 3.0)

        grid = np.full((7, n_weeks), np.nan)
        month_label_week: dict[int, str] = {}
        for offset in range(n_days):
            day_date = jan1 + _timedelta(days=offset)
            week_idx = (offset + jan1_weekday) // 7
            weekday_idx = day_date.weekday()
            amount = daily.get((day_date.month, day_date.day), 0.0)
            self._cell_info[(weekday_idx, week_idx)] = (day_date.month, day_date.day, amount)

            if amount <= 0:
                bucket = 0
            elif amount <= thresholds[0]:
                bucket = 1
            elif amount <= thresholds[1]:
                bucket = 2
            elif amount <= thresholds[2]:
                bucket = 3
            else:
                bucket = 4
            grid[weekday_idx, week_idx] = bucket

            if day_date.day == 1:
                month_label_week[week_idx] = MONTH_NAMES[day_date.month - 1][:3]

        cmap = ListedColormap(HEATMAP_BUCKETS)
        cmap.set_bad(color=c("bg"))
        masked = np.ma.masked_invalid(grid)
        ax.imshow(masked, cmap=cmap, vmin=-0.5, vmax=4.5, aspect="auto")
        # Explicit, not left to lazy autoscale — otherwise switching from a
        # year with more weeks to one with fewer would leave the old, wider
        # xlim in place (see BalanceLineChart's relim/autoscale_view note).
        ax.set_xlim(-0.5, n_weeks - 0.5)
        ax.set_ylim(6.5, -0.5)

        ax.set_yticks(range(7))
        ax.set_yticklabels(["Mon", "", "Wed", "", "Fri", "", "Sun"])
        week_ticks = sorted(month_label_week)
        ax.set_xticks(week_ticks)
        ax.set_xticklabels([month_label_week[w] for w in week_ticks])
        ax.xaxis.tick_top()

        for spine in ax.spines.values():
            spine.set_visible(False)
        ax.tick_params(colors=c("t2"), labelsize=8, length=0)
        for label in ax.get_xticklabels() + ax.get_yticklabels():
            label.set_fontfamily(_FONT)

        self.draw_idle()

    def _hit_test(self, event) -> str | None:
        if not self._cell_info or event.xdata is None or event.ydata is None:
            return None
        week = round(event.xdata)
        weekday = round(event.ydata)
        info = self._cell_info.get((weekday, week))
        if info is None:
            return None
        month, day, amount = info
        label = f"{MONTH_NAMES[month - 1]} {day}, {self._year}"
        if amount <= 0:
            return f"{label}: no expenses"
        return f"{label}: {fmt_amount(amount)}"
