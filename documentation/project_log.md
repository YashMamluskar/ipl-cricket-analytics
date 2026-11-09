# Project Log & File Register

## Phase 1 — Dataset Understanding & Profiling (2026-11-08)

### Files created

| Path | Type | Purpose |
|---|---|---|
| `data/raw/matches.csv` | data (read-only) | Hash-verified copy of the original match file |
| `data/raw/deliveries.csv` | data (read-only) | Hash-verified copy of the original ball-by-ball file |
| `python/ipl_config.py` | code | Central paths, raw-file hashes, cricket rule constants |
| `python/01_data_profiling.py` | code | Reproducible profiling and data-quality checks (55 checks) |
| `notebooks/01_data_profiling.ipynb` | notebook (executed) | Walkthrough of the profiling, with outputs and charts |
| `reports/profiling/dataset_profiling_report.md` | report | Generated profiling report (shape, coverage, column profiles, distributions) |
| `reports/profiling/column_profile_matches.csv` | report | Column-level profile |
| `reports/profiling/column_profile_deliveries.csv` | report | Column-level profile |
| `reports/profiling/season_coverage.csv` | report | Matches, deliveries, venues, ties and DLS per season |
| `reports/profiling/team_name_eras.csv` | report | Each team-name string with first/last year |
| `reports/profiling/venue_name_variants.csv` | report | Venue strings grouped by base name |
| `reports/profiling/figures/missing_values.png` | figure | Missing values by column |
| `reports/profiling/figures/matches_per_season.png` | figure | Matches per season |
| `reports/validation/phase1_data_quality_checks.csv` | report | All 55 checks with PASS/FLAG/INFO |
| `reports/validation/phase1_initial_data_quality_report.md` | report | Generated data-quality report |
| `documentation/data_dictionary.md` | doc | Column definitions and verified rules |
| `documentation/dataset_relationship.md` | doc | Join, keys and integrity results |
| `documentation/data_source_and_lineage.md` | doc | Source, coverage, lineage and limitations |
| `documentation/project_log.md` | doc | This file |

**Note:** the original `matches.csv` and `deliveries.csv` are still in the project root, untouched. They are byte-identical to `data/raw/` and can be deleted once the owner is happy with the copies.

### Reproduce

```
python python/01_data_profiling.py
jupyter nbconvert --to notebook --execute --inplace notebooks/01_data_profiling.ipynb
```

### Decisions needed before Phase 2 (owner sign-off)

1. **Franchise mapping.** Proposed: merge pure renames into one `franchise` field, *Delhi Daredevils → Delhi Capitals*, *Kings XI Punjab → Punjab Kings*, *Royal Challengers Bangalore → Royal Challengers Bengaluru*, *Rising Pune Supergiants → Rising Pune Supergiant*. Keep the original name in a `team_name_as_played` column. Keep *Deccan Chargers* and *Sunrisers Hyderabad* separate (different franchises) and keep *Gujarat Lions* separate from *Gujarat Titans*.
2. **Venue standardisation.** Strip the city suffixes (30 variant strings across 13 grounds, detected by the script). The following renamed grounds are proposed from general cricket knowledge, **not** from the data, and need confirmation: *Feroz Shah Kotla → Arun Jaitley Stadium*, *Sardar Patel Stadium, Motera → Narendra Modi Stadium*, *Sheikh Zayed Stadium ↔ Zayed Cricket Stadium, Abu Dhabi*, *Punjab Cricket Association Stadium, Mohali ↔ PCA IS Bindra Stadium*, *Subrata Roy Sahara Stadium ↔ Maharashtra Cricket Association Stadium, Pune*.
3. **Season.** Add `season_year` taken from `date`, and keep the original label.
4. **Super overs.** Keep the rows, but add an `is_super_over` flag and leave them out of regulation stats by default.
5. **Retired hurt.** Not treated as a dismissal (batter not out, no bowler wicket).

---

## Phase 2 — Owner decisions (approved 2026-11-08)

Recorded **before** any cleaning was run.

| # | Decision | Applied in |
|---|---|---|
| D1 | Franchise merges: Delhi Daredevils → **Delhi Capitals**; Kings XI Punjab → **Punjab Kings**; Royal Challengers Bangalore → **Royal Challengers Bengaluru**; Rising Pune Supergiant (2017) → **Rising Pune Supergiants** | `data/reference/franchise_mapping.csv` |
| D2 | Kept separate: Deccan Chargers vs Sunrisers Hyderabad; Gujarat Lions vs Gujarat Titans | same |
| D3 | Venue suffix and punctuation variants merged (22 strings) | `data/reference/venue_mapping.csv` |
| D4 | Five externally verified ground mappings: Feroz Shah Kotla → Arun Jaitley Stadium; Sardar Patel Stadium, Motera → Narendra Modi Stadium (**caveat kept: demolished and rebuilt 2015–2020**); Punjab Cricket Association Stadium, Mohali → Punjab Cricket Association IS Bindra Stadium; Subrata Roy Sahara Stadium → Maharashtra Cricket Association Stadium; Zayed Cricket Stadium, Abu Dhabi → Sheikh Zayed Stadium (**note kept: alternate name, not a formal rename**) | same |
| D5 | City: fill the 51 missing values (Dubai, Sharjah) from the same venue's recorded city; M Chinnaswamy Stadium → **Bengaluru**; Dr DY Patil Sports Academy → **Navi Mumbai**; all other cities kept as recorded | same |
| D6 | `season_year` taken from the match date; original season label kept | cleaning script |
| D7 | Super overs kept and flagged; left out of regulation stats by default | cleaning script |
| D8 | Retired hurt = not out, not a bowler wicket; original dismissal fields kept | cleaning script |
| D9 | Seven-legal-ball overs kept as recorded and flagged | cleaning script |
| D10 | Original team, venue and city values kept in `*_original` columns | cleaning script |

## Phase 2 — Data Cleaning & Preparation (completed 2026-11-08)

### Files created or updated

| Path | Type | Purpose |
|---|---|---|
| `python/ipl_config.py` | code (updated) | Added reference/processed paths, bowler-wicket kinds, phase definitions |
| `python/02a_build_reference_mappings.py` | code | Builds the approved franchise and venue/city mapping tables and checks they cover every value |
| `python/02b_clean_data.py` | code | Row-preserving cleaning and feature engineering, plus the transformation log |
| `python/02c_validate_cleaned.py` | code | 60 independent before/after checks; exits with code 1 if any fail |
| `data/reference/franchise_mapping.csv` | reference | 19 original names → 15 franchises |
| `data/reference/venue_mapping.csv` | reference | 58 original venues → 36 grounds, with reason, verification, source, approval and city rule |
| `data/processed/matches_clean.csv` | data | 1,095 × 44 |
| `data/processed/deliveries_clean.csv` | data | 260,920 × 48 |
| `reports/validation/phase2_transformation_log.csv` | report | 27 logged transformation steps with rows affected |
| `reports/validation/phase2_validation_checks.csv` | report | 60 checks (all PASS) |
| `reports/validation/phase2_before_after_validation_report.md` | report | Before/after table and all checks |
| `reports/validation/figures/standardisation_before_after.png` | figure | Standardisation counts |
| `reports/validation/figures/run_rate_by_over_phase_check.png` | figure | Phase-assignment sanity check |
| `notebooks/02_data_cleaning.ipynb` | notebook (executed) | Runs 02a → 02b → 02c with explanations |
| `documentation/transformation_log.md` | doc | Transformations, cricket definitions, cleaned data dictionary, investigations |
| `documentation/project_log.md` | doc (updated) | Decisions and file register |

### Investigations
- 6 D/L matches recorded as won "by runs" by the chasing team. Verified as legitimate (ahead of par when rain stopped play). Data unchanged and validation rule refined (V53/V53b).

---

## Phase 3 — Exploratory Data Analysis (completed and approved 2026-11-08)

**Status:** complete. 28 questions answered across 5 sections. 46/46 validation checks pass. Raw and cleaned datasets were only read, never modified (raw SHA-256 rechecked).

### Files created

| Path | Type | Purpose |
|---|---|---|
| `python/03_eda.py` | code | Reproducible EDA: base tables, one function per question, 46 validation checks, report writers |
| `python/03b_build_eda_notebook.py` | code | Builds the EDA notebook from the script's question list so the two can't drift apart |
| `notebooks/03_exploratory_data_analysis.ipynb` | notebook (executed, 0 errors) | Question-by-question walkthrough plus a separate super-over section |
| `reports/eda_report.md` | report | Written findings: question, why, metric definition, finding, chart, table, limitation |
| `reports/eda_validation_report.md` | report | 46 checks with expected vs actual values |
| `reports/eda_validation_checks.csv` | report | Same checks as CSV |
| `reports/eda_summary.csv` | report | Long-format summary (section, table, rank, entity, metric, value) of the season, team, batting, bowling and venue tables |
| `reports/eda_tables/*.csv` | report | Every question's result table plus season, team, venue, batter-career and bowler-career tables |
| `reports/charts/*.png` | figures | 18 charts at 200 dpi |

### Analysis decisions
- **Full match** = not a no-result and `target_overs = 20` (1,061 matches). Used for all score averages.
- Ranking thresholds: batting average/consistency ≥ 50 innings; strike rate ≥ 500 balls; bowling ≥ 1,000 legal balls; phase batting ≥ 300 balls; phase bowling ≥ 600 balls; venues ≥ 20 matches; team batting-first/chasing ≥ 20 matches.
- Era adjustment (value minus that season's league average) used for team bowling (B6), team first-innings scores (B5) and venues (E3/E6), because scoring rose sharply in 2023–24.

### Issues found and fixed during Phase 3
- Narrative claims I wrote before seeing the results were checked against the data. Six were corrected and now come from computed values:
  - A2: step-change wording.
  - C3: number of recent players.
  - D2: number of pre-2018 careers.
  - D4: phase economy gap.
  - E4: confidence intervals computed per venue.
  - E6: Spearman rho = −0.46, p = 0.08, is "moderate, not significant", not "weak".
- Chart layout fixed: title/subtitle overlap, scatter-label collisions, and the reference line crossing value labels.

### Reproduce (Phase 3)
```
python python/03_eda.py
python python/03b_build_eda_notebook.py
jupyter nbconvert --to notebook --execute --inplace notebooks/03_exploratory_data_analysis.ipynb
```

### Reproduce
```
python python/02a_build_reference_mappings.py
python python/02b_clean_data.py
python python/02c_validate_cleaned.py
```

---

## Phase 4 — MySQL Database & SQL Analysis (completed and approved 2026-11-08)

**Status:** complete, **executed on the live local MySQL server**. Not simulated, and no SQLite, DuckDB or temporary server was used.

| Item | Result |
|---|---|
| Server | MySQL **8.0.40** (Windows service `MySQL80`, localhost:3306) |
| Connected user | `ipl_analyst@localhost`, granted ALL on `ipl_cricket_analytics.*` only |
| Credentials | Read from user environment variables `MYSQL_USER` / `MYSQL_PASSWORD`; never printed, logged or committed |
| Loaded | 1,095 matches, 260,920 deliveries, 741 players, 15 teams (+19 aliases), 36 venues (+58 aliases) |
| Constraints | 18 foreign keys, 6 CHECK constraints, 32 indexes (23 automatic PK/UK/FK + 9 composite), 8 views |
| Data-quality checks (`sql/05`) | **34 / 34 PASS** |
| Business queries (`sql/06`) | **27 questions + 1 separate super-over query**, all executed; outputs saved |
| SQL vs Python reconciliation | **9,014 entity-metric comparisons, 0 FAIL** (max ratio difference 2.8e-14). **6/6 top-10 rankings identical in order** |
| Rerun safety | Loader rerun gave identical row counts and the 9 indexes were skipped as existing; checks still 34/34 |

### Issues met during execution and how they were handled
1. **No credentials visible to the session.** The variables had been set in a separate terminal window, which this session can't see. The owner set them with `setx` and the scripts read them from the user environment.
2. **Error 1044 (Access denied) on CREATE DATABASE.** The new user only had `USAGE`. The owner ran `GRANT ALL PRIVILEGES ON ipl_cricket_analytics.* TO 'ipl_analyst'@'localhost'` as root, and the grant was confirmed with `SHOW GRANTS` before loading.
3. **MySQL division precision.** `/` and `AVG()` keep only 4 extra decimal places by default (`div_precision_increment = 4`), so sessions now set it to 30 and SQL matches Python exactly instead of within a rounding tolerance.
4. **One check expectation corrected before execution.** The foreign-key count is 16 on the two fact tables, not 15.
5. **Two generated insight sentences corrected after the first run.** The Q01 wording was garbled, and years displayed as `2024.0` (a pandas type-promotion artefact).

### Files created
| Path | Purpose |
|---|---|
| `.gitignore`, `config/mysql_config.example.ini` | Keep credentials out of version control; config template |
| `sql/01_create_database.sql` … `sql/06_business_analysis.sql` | Database, tables, indexes, views, 34 checks, 28 queries |
| `python/mysql_utils.py` | Config/env credential handling, strict session, SQL file runner |
| `python/04_load_mysql.py` | Transactional, rerun-safe loader with pre-commit verification |
| `python/04b_validate_mysql.py` | Runs the checks and records the server inventory |
| `python/04c_run_sql_analysis.py` | Executes the business queries and builds the report |
| `python/04d_reconcile_sql_python.py` | Full SQL vs Python reconciliation |
| `reports/sql_validation_report.md`, `reports/sql_validation_checks.csv` | Check results and server inventory |
| `reports/sql_business_analysis_report.md`, `reports/sql_query_results/Q01-Q28.csv` | Query, explanation, actual output and insight for each question |
| `reports/sql_python_reconciliation.csv`, `reports/sql_python_reconciliation_summary.md` | Reconciliation detail and summary |
| `documentation/mysql_setup_guide.md`, `database_schema.md`, `database_relationships.md` | Setup guide, schema, ER diagram (Mermaid) |

### Reproduce (Phase 4)
```
python python/04_load_mysql.py
python python/04b_validate_mysql.py
python python/04c_run_sql_analysis.py
python python/04d_reconcile_sql_python.py
```

---

## Phase 5 — Advanced Cricket Analytics (completed and approved 2026-11-08)

**Status:** complete. **32 advanced questions** across batting (7), bowling (7), match pressure (7), team contribution (6), venue (4) and an ML assessment (1). **30/30 validation checks pass**, including 4 cross-checks against the live MySQL database. Raw and cleaned data were read only (raw SHA-256 unchanged).

### Methods introduced in this phase
- **Season- and phase-adjusted metrics:** each legal ball × the league rate for that season *and* phase gives expected runs or wickets. Validation P07/P08 confirms the expectations sum exactly to the actual totals, so the adjustment has no bias.
- **Chase-state table:** runs needed, balls left and wickets in hand at the end of every over. It covers 1,047 full, non-D/L, decided chases (18,817 live states). P15 confirms a chase was won exactly when its target was reached.
- **Statistics:**
  - 95% Wilson intervals for proportions.
  - Spearman correlation.
  - Wilcoxon signed-rank tests for paired player comparisons, Mann-Whitney U for independent groups, and chi-square tests (with expected counts reported).
  - Logistic regression with a bootstrap CI for the par score and for its change.
  - Individual players are not tested one by one, to avoid false positives from multiple comparisons.
- **ML decision:**
  - Pre-match winner prediction was **rejected**: the signals are near coin-flip and there is no squad or availability data.
  - In-chase win probability was **justified and tested**: trained on 2008–21, tested on 2022–24, and compared against a base-rate model and a lookup table.

### Issues found and fixed during Phase 5
1. **Chart crash (C2).** One wickets-in-hand band had no cells with 10 or more chases; it is now skipped.
2. **Validation check M04** read the top-12 display table instead of the full table of qualifying batters. Fixed.
3. **Narrative claims checked against the computed results.** Nine were corrected:
   - **A4 and B2:** the relationships were not statistically significant, but the text described them as real.
   - **C6:** the direction was wrong; close matches score *faster* at the death.
   - **D4:** the text claimed every franchise's SD exceeded chance; only 4 of 8 do.
   - **E4:** the text said the intervals didn't overlap, but they do. Replaced with a bootstrap CI on the *difference* (+13 runs, CI +1 to +26).
   - **C4 and D5:** hard-coded "p < 0.001" replaced with the computed p-values.
   - **A6 and B6:** standard errors are now computed; B6's had been understated.
   - **C7 and E1:** wording corrected.

### Files created
| Path | Purpose |
|---|---|
| `python/05_advanced_analytics.py` | All Phase 5 analyses, 30 validation checks and the report writers |
| `python/eda_helpers_phase5.py` | Finding record, Wilson interval, chart saver, diverging colour map |
| `python/05b_build_advanced_notebook.py` | Builds the notebook from the script's list of findings |
| `notebooks/05_advanced_cricket_analytics.ipynb` | Run with 0 errors |
| `reports/advanced_analytics_report.md` | 32 findings in the 7-part format |
| `reports/advanced_analytics_validation_report.md`, `reports/advanced_analytics_validation_checks.csv` | 30 checks |
| `reports/advanced_analytics_summary.csv` | One row per finding |
| `reports/advanced_analytics_tables/` | 66 result tables |
| `reports/charts/phase5/` | 20 charts at 200 dpi |

### Reproduce (Phase 5)
```
python python/05_advanced_analytics.py
python python/05b_build_advanced_notebook.py
jupyter nbconvert --to notebook --execute --inplace notebooks/05_advanced_cricket_analytics.ipynb
```

---

## Phase 6 — Power BI Dashboard (completed 2026-11-08, awaiting owner review)

**Status:** complete and validated against the live Power BI model. **Remaining manual step:** save the `.pbix` from Desktop (File → Save as). Power BI Desktop has no scriptable save, so the deliverable is the `.pbip` project plus a one-step save.

### Approach
- **Win-probability model audit (`python/06a_audit_win_probability.py`): NOT APPROVED, excluded.**
  - Passed: features available at prediction time (300/300 states rebuilt), no leakage, unseen seasons.
  - Failed: calibration on held-out matches. It under-predicts chase success by −3.5, −3.3 and −8.5 percentage points in 2022, 2023 and 2024. The upper 95% bound of calibration error is 0.098, above the 0.07 limit, and 2 of 10 deciles fall outside their match-clustered CI.
  - **This supersedes the Phase 5 summary wording** that called the model "calibrated".
- **Data:** star-schema CSV extracts (`python/06b_export_powerbi_model.py`). 13/13 checks pass, including reconciliation with MySQL. No live MySQL connection: no Power BI MySQL driver is installed, and credentials must stay out of the report.
- **Dashboard:** generated as a Power BI Project (TMDL model + PBIR report) by `python/06c_build_pbip.py`.
  - 4 fact tables, 5 dimensions, 2 disconnected comparison tables, 16 single-direction one-to-many relationships (2 inactive, for the bowling roles), 111 DAX measures.
  - 3 pages plus a hidden drill-through page; custom theme using the owner's mandatory six-colour palette.
- **Validation (`python/06e_validate_dashboard.py`):** DAX queries run against the model open in Desktop, after a refresh through its local engine. **35/35 PASS**: KPIs, every batter, bowler, season, franchise and venue, rankings, thresholds, filter behaviour, relationships, duplicates and missing values.

### Issues found and fixed
1. `report.json` was missing the required `layoutOptimization` property (found through the prototype).
2. **DAX bug:** four measures referenced `FactMatch[result_for]` after the column was renamed to "Result for", so batting-first/chasing measures and the venue table errored. Caught visually; validation check B00 now evaluates all 111 measures.
3. The `Titles` measure returned blank instead of 0 for the 4 franchises that never reached a final. Fixed with `COALESCE`.
4. A validation tolerance was too strict for a reference table stored at 3 dp (T04). It was documented and adjusted; values agree to within the rounding.
5. Layout: header overlap, total rows and subtotals, abbreviated numbers, continuous season axes, unreadable diverging matrix text, a truncated venue table. All fixed in the generator.

### Files created
| Path | Purpose |
|---|---|
| `python/06a_audit_win_probability.py` | Model publication audit |
| `python/06b_export_powerbi_model.py` | Star-schema extracts plus 13 checks |
| `python/06c_build_pbip.py` | Generates the whole Power BI project |
| `python/06d_open_refresh_capture.ps1`, `pbi_local.ps1`, `pbi_dax_json.ps1`, `pbi_screenshot.ps1`, `pbi_select_page.ps1` | Open, refresh, DAX bridge, screen capture |
| `python/06e_validate_dashboard.py` | 35 DAX validation checks |
| `python/06f_crop_screenshots.py`, `python/06g_write_powerbi_docs.py` | Screenshot cropping; generated docs |
| `data/final/powerbi/*.csv` | 9 model tables |
| `dashboard/IPL_Cricket_Analytics/` | `.pbip` project (model + report + theme) |
| `dashboard/screenshots/01-03_*.png` | Page screenshots |
| `dashboard/docs/power_bi_setup_guide.md`, `power_bi_dax_measures.md`, `power_bi_data_model.md` | Documentation |
| `reports/powerbi/win_probability_audit.md`, `export_validation_checks.csv`, `dashboard_validation_report.md` | Audit and validation |

### Reproduce
```
python python/06b_export_powerbi_model.py
python python/06c_build_pbip.py
powershell -ExecutionPolicy Bypass -File python/06d_open_refresh_capture.ps1
python python/06e_validate_dashboard.py
python python/06f_crop_screenshots.py
```
