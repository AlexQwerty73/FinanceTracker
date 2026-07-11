# FinanceTracker

Desktop companion for two OneDrive-synced Excel workbooks (`Finances_2025.xlsx`, `Finances_2026.xlsx`). Add, edit, or delete a transaction from a dialog — it's written straight into the right year's workbook, in its own schema, formulas untouched. Four pages — **Dashboard**, **Transactions**, **Analytics**, **Categories** — refresh themselves automatically when a file changes on disk (e.g. a transaction added from the phone via the OneDrive app).

## Requirements

- Python 3.11+
- Windows 10/11

## Run

```bash
pip install -r requirements.txt
python main.py
```

## Build (.exe)

```bat
build.bat
```

Output: `dist\FinanceTracker\FinanceTracker.exe`

## Layout

- **Sidebar** — switch between the four pages
- **Top bar** (shared by Dashboard/Transactions) — month navigation (`<`/`>`, **Today**), **+ Add Transaction**, **Refresh**, last-updated time
- **Dashboard** — income/expense/invest/balance tiles, how the balance progressed day-by-day this month, expense and income breakdowns as pie charts with %, and a 5-row recent-transactions preview with a link to the full list
- **Transactions** — the full table for the viewed month, a search box (filters by category or note), Edit/Delete, and a link back to Analytics
- **Analytics** — a cumulative balance-over-time line for a selectable period (last 6/12 months, this year, all time), a cash-flow chart (Cash-only income/expense per period), a GitHub-style daily-expense heatmap for a chosen year, and a category pie for the selected period
- **Categories** — per-year category list; add a new one, or rename one everywhere it's used (every month sheet, plus `AllData` for 2026) in one go — fix a typo once instead of chasing it through every row

## Features

- Add/edit a transaction: date (defaults to today), type, category, amount, payment type, note — in one dialog, reused for both
- The year is picked automatically from the date — 2025 and 2026 have different sheet layouts, handled by separate adapters (`core/excel/schema_2025.py`, `schema_2026.py`)
- Editing across the 2025/2026 boundary moves the transaction into the other year's file safely (writes the new row before deleting the old one)
- The last payment type used is remembered per year for the next **Add**
- Every chart has a hover tooltip (pie slices, line/bar points, heatmap cells) with the exact figure and, where relevant, a percentage
- Writes land inside the workbook's existing formula ranges and leave every SUMIF/SUMIFS total alone — Excel recalculates them itself next time it opens the file
- Live refresh: a file watcher (debounced ~2s) reloads the current page whenever either workbook changes on disk, from this app or from OneDrive sync
- Handles the file being locked by Excel or mid-sync with retry + backoff instead of crashing
- Reads are cached in memory keyed by the file's modified time, so flipping through months or scanning a whole year (Analytics) doesn't re-parse the workbook from disk each time — only actual writes or external edits invalidate it

## Data

Nothing is stored by this app — it reads and writes directly:

```
C:\Users\<you>\OneDrive\Finances\Finances_2025.xlsx
C:\Users\<you>\OneDrive\Finances\Finances_2026.xlsx
```

## Adding a new year

Each year's sheet layout is its own adapter implementing `core/excel/base.YearSchema`. To support a new year (e.g. 2027):

1. Add `core/excel/schema_2027.py` implementing `YearSchema`
2. Register it in `core/excel/registry.py` (`YEAR_SCHEMAS`)
3. Add the file path in `core/config.py` (`FILE_PATHS`)

If the new year has no daily dates (like 2025), set `HAS_DAILY_DATES = False` on the schema class — the running-balance chart and heatmap degrade gracefully to an empty state instead of erroring.
