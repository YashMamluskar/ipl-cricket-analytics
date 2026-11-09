# Power BI Setup Guide — IPL Cricket Analytics Dashboard

## 1. What's in `dashboard/`

| Path | What it is |
|---|---|
| `IPL_Cricket_Analytics/IPL_Cricket_Analytics.pbip` | **Power BI Project**. Open this in Power BI Desktop. |
| `IPL_Cricket_Analytics/*.SemanticModel/` | The model in TMDL text: 9 tables, 2 comparison tables, 16 relationships, 111 measures |
| `IPL_Cricket_Analytics/*.Report/` | The report in PBIR JSON: 3 pages, a hidden drill-through page, and the custom theme |
| `IPL_Cricket_Analytics.pbix` | Single-file version, saved from Desktop (see step 4) |
| `screenshots/` | Page screenshots (cropped to the canvas); `raw/` holds the full-window captures |
| `docs/` | This guide, `power_bi_dax_measures.md` and `power_bi_data_model.md` |

Everything in the project folder is **generated** by `python/06c_build_pbip.py`. To change a visual or measure, edit that script and regenerate, rather than editing the JSON or TMDL by hand.

## 2. Requirements
- Power BI Desktop, September 2025 or later. Built and tested with the Microsoft Store build 2.159.
- No database connection or credentials are needed. The model reads the validated CSV extracts in `data/final/powerbi/`.

## 3. Rebuild from scratch (run from the project root)

```bash
python python/06b_export_powerbi_model.py   # validated CSV extracts (13 checks incl. MySQL reconciliation)
python python/06c_build_pbip.py             # generate the .pbip (model + report + theme)
```

```powershell
powershell -ExecutionPolicy Bypass -File python/06d_open_refresh_capture.ps1   # open, refresh, capture pages
```

```bash
python python/06e_validate_dashboard.py     # DAX validation against Phase 3/4/5 (needs Desktop open)
python python/06f_crop_screenshots.py       # crop captures to the report canvas
python python/06g_write_powerbi_docs.py     # regenerate measure and model docs
```

- `06d` closes any running Power BI Desktop, so save other work first.
- `06d` refreshes the data through Desktop's local engine, the same engine the Refresh button uses.

**Manual alternative:** open the `.pbip`, then choose **Home → Refresh**.

## 4. Save a `.pbix`
A `.pbip` project is source-control friendly. A `.pbix` is the single file people expect to download.

1. Open `IPL_Cricket_Analytics.pbip` and refresh it.
2. Choose **File → Save as**, set "Save as type" to **Power BI file (\*.pbix)**, and save to `dashboard/IPL_Cricket_Analytics.pbix`.

## 5. If you move the project
The data path is a Power Query parameter. To change it, go to **Home → Transform data → Edit parameters → `DataFolder`** and set it to the new `…/data/final/powerbi` folder. Then refresh. You can also set the new path in `python/06c_build_pbip.py` and regenerate.

## 6. Using the dashboard

| Page | Slicers | Notes |
|---|---|---|
| IPL overview | Season range, venue | KPIs, run rate by phase, average first-innings score, wins, batting first vs chasing |
| Player performance | Season, franchise, Player A, Player B | Rankings apply the minimum-sample thresholds. The franchise filter means the batting team for batting measures and the bowling team for bowling measures. |
| Match and team insights | Season range, venue | Toss, chase success by target, wickets-in-hand matrix, team phase strengths, venues, close matches |
| Player detail (hidden) | Drill-through on Player | Right-click any player and choose **Drill through → Player detail** |

- **Tooltips:** hover over bars for sample sizes, confidence intervals and secondary metrics.
- **Blank values are deliberate.** A blank means the player, venue or team doesn't meet the sample threshold under the current filters.

## 7. Design system
| Role | Colour | Used for |
|---|---|---|
| Page background | `#1A0F2E` | Canvas |
| Cards and containers | `#3B1B4F` | Visual backgrounds, slicers, KPI cards |
| Secondary purple | `#7A2E6F` | Borders, table headers, selection. Not used for data marks (only 1.7:1 contrast on cards). |
| Primary pink | `#D6598F` | Primary data series |
| Light neutral | `#F4D7D4` | Text, second series in comparisons |
| Coral highlight | `#FF6B6B` | One standout KPI per page, "all overs" line, below-league values |
| Derived: muted text | `#AA8C9F` | Subtitles, axis labels (4.8:1 on cards) |
| Derived: phase ramp | `#F4D7D4` → `#E492AE` → `#D6598F` | Powerplay → Middle → Death (ordered light-to-dark ramp, validated) |
| Derived: gridlines | `#573763` | Recessive gridlines |

- **Contrast:** text `#F4D7D4` reaches 10.7:1 on cards. No light text is placed on pink fills, because that combination is only 2.7:1.
- **Font:** Segoe UI and Segoe UI Semibold.
- **Theme file:** `IPL_Cricket_Analytics.Report/StaticResources/RegisteredResources/IPL_Dark_Theme.json`.

## 8. Not included (by design)
- **The in-chase win-probability model is excluded.** It failed its publication audit: it under-predicted 2024 chases by 8.5 percentage points, and its calibration-error interval exceeded the limit. See `reports/powerbi/win_probability_audit.md`.
- **No live MySQL connection.** See `power_bi_data_model.md` for the reasoning.
