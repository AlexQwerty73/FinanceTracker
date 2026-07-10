"""
app/components/charts.py — matplotlib charts embedded in the dashboard.

Category breakdown is a single expense series compared by magnitude, so it
gets one hue (never color-per-category — that would spend the identity
channel re-encoding what bar length already shows). Income vs Expense is two
distinct series, so it gets the app's own established green/red pair
(matching the stat tiles and InvestTracker's buy/sell convention), with
position (income always left, expense always right) and the legend as
secondary encoding so identity never rests on color alone.
"""
from __future__ import annotations

import matplotlib
matplotlib.use("QtAgg")

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure

from core.themes import c

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


class CategoryBreakdownChart(FigureCanvasQTAgg):
    """Horizontal bar chart: expense amount per category for one month."""

    def __init__(self, parent=None):
        fig = Figure(figsize=(4, 2.6), dpi=100, facecolor=c("chart_bg"))
        super().__init__(fig)
        if parent is not None:
            self.setParent(parent)
        self.setStyleSheet("background:transparent;")
        self.setMinimumHeight(180)
        self._ax = fig.add_subplot(111, facecolor=c("chart_bg"))
        fig.subplots_adjust(left=0.32, right=0.92, top=0.95, bottom=0.08)

    def update_data(self, breakdown: dict[str, float]) -> None:
        ax = self._ax
        ax.clear()
        ax.set_facecolor(c("chart_bg"))

        items = sorted(((k, v) for k, v in breakdown.items() if v > 0), key=lambda kv: kv[1], reverse=True)
        if len(items) > _TOP_CATEGORIES:
            head = items[:_TOP_CATEGORIES]
            other_total = sum(v for _, v in items[_TOP_CATEGORIES:])
            items = head + [("Other", other_total)]
        items.reverse()  # largest at top

        if not items:
            _empty_state(ax, "No expenses this month")
        else:
            labels = [k for k, _ in items]
            values = [v for _, v in items]
            bars = ax.barh(labels, values, color=c("ac"), height=0.6)
            max_v = max(values)
            for bar, value in zip(bars, values):
                ax.text(bar.get_width() + max_v * 0.02, bar.get_y() + bar.get_height() / 2,
                        f"{value:,.0f}", va="center", ha="left",
                        color=c("t2"), fontsize=8, fontfamily=_FONT)
            ax.set_xlim(0, max_v * 1.22)
            ax.set_xticks([])

        _style_axes(ax)
        self.draw()


class TrendChart(FigureCanvasQTAgg):
    """Grouped bar chart: income vs expense across a trailing run of months."""

    def __init__(self, parent=None):
        fig = Figure(figsize=(4, 2.4), dpi=100, facecolor=c("chart_bg"))
        super().__init__(fig)
        if parent is not None:
            self.setParent(parent)
        self.setStyleSheet("background:transparent;")
        self.setMinimumHeight(170)
        self._ax = fig.add_subplot(111, facecolor=c("chart_bg"))
        fig.subplots_adjust(left=0.08, right=0.95, top=0.82, bottom=0.15)

    def update_data(self, points: list[tuple[str, float, float]]) -> None:
        """points: list of (month_label, income, expense), oldest first."""
        ax = self._ax
        ax.clear()
        ax.set_facecolor(c("chart_bg"))

        if not points:
            _empty_state(ax, "No data")
            _style_axes(ax)
            self.draw()
            return

        labels = [p[0] for p in points]
        income = [p[1] for p in points]
        expense = [p[2] for p in points]
        x = list(range(len(points)))
        width = 0.36

        ax.bar([i - width / 2 for i in x], income, width=width, color=c("income_c"), label="Income")
        ax.bar([i + width / 2 for i in x], expense, width=width, color=c("expense_c"), label="Expense")

        ax.set_xticks(x)
        ax.set_xticklabels(labels)
        ax.set_yticks([])
        legend = ax.legend(
            loc="lower left", bbox_to_anchor=(0, 1.02), ncols=2,
            frameon=False, fontsize=8, handlelength=1.2, columnspacing=1.2,
        )
        for text in legend.get_texts():
            text.set_color(c("t2"))
            text.set_fontfamily(_FONT)

        _style_axes(ax)
        self.draw()
