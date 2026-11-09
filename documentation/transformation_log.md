# Phase 2 — Transformation Documentation

This file explains **what** was changed, **why** it was changed and **how it was checked**. Row-level counts for each step come from the script and are in [`reports/validation/phase2_transformation_log.csv`](../reports/validation/phase2_transformation_log.csv). Nothing in this document was edited by hand from results that weren't produced by code.

## 1. Pipeline

```
data/raw/matches.csv, deliveries.csv   (read-only, SHA-256 verified on every run)
        │
        ├─ python/02a_build_reference_mappings.py → data/reference/franchise_mapping.csv
        │                                           data/reference/venue_mapping.csv
        ├─ python/02b_clean_data.py               → data/processed/matches_clean.csv     (1,095 × 44)
        │                                           data/processed/deliveries_clean.csv  (260,920 × 48)
        │                                           reports/validation/phase2_transformation_log.csv
        └─ python/02c_validate_cleaned.py         → reports/validation/phase2_validation_checks.csv
                                                    reports/validation/phase2_before_after_validation_report.md
```

To reproduce, run from the project root:

```
python python/02a_build_reference_mappings.py
python python/02b_clean_data.py
python python/02c_validate_cleaned.py
```

`02c` exits with code 1 if any check fails. Current result: **60 PASS, 0 FAIL**.

## 2. Guiding rules

1. **No rows are dropped.** Match and delivery counts are asserted to be equal before and after.
2. **Nothing is overwritten.** Every standardised field keeps the raw value next to it (`*_original`), and every raw column can be traced (checks V09, V10).
3. **Unusual but valid records are flagged, not removed.** This covers super overs, retired hurt, 7-legal-ball overs, no-results, DLS matches and imputed cities.
4. **Mappings come only from the approved reference tables.** If a value isn't in the mapping, the script fails with an error instead of guessing.

## 3. Transformations

| # | Table | Field(s) | Transformation | Rows affected |
|---|---|---|---|---|
| T1 | matches | `season_year` | Year taken from `match_date`. The original label is kept in `season_label_original`. | 1,095 (178 labels differ: `2007/08`, `2009/10`, `2020/21`) |
| T2 | matches | `venue` | Mapped through `venue_mapping.csv`, giving 36 grounds from 58 strings. The original is kept in `venue_original`. | 506 |
| T3 | matches | `city` | Missing city filled from the same venue's recorded city. Flagged by `is_city_imputed`. | 51 (Dubai 33, Sharjah 18) |
| T4 | matches | `city` | Approved spelling unification per ground. The original is kept in `city_original`. | 93 (Bangalore→Bengaluru 65; Mumbai→Navi Mumbai 28) |
| T5 | both | `team1`, `team2`, `toss_winner`, `winner`, `batting_team`, `bowling_team` | Mapped through `franchise_mapping.csv`, giving 15 franchises from 19 names. Originals kept in `*_original`. | 319 / 288 / 284 / 281 matches; 71,537 / 71,494 deliveries |
| T6 | matches | `win_type`, `result_for`, `is_no_result`, `is_dls`, `is_super_over`, `is_playoff` | Result and stage flags derived (see definitions below). | 1,095 |
| T7 | matches | `target_balls` | Cricket overs notation converted to balls (`9.2` → 56 balls). | 1,092 |
| T8 | matches | `batting_first_team`, `chasing_team`, `toss_winner_batted_first`, `toss_winner_won` | Batting order taken from the innings-1 batting team, not from `team1`. | 1,095 |
| T9 | matches | `inn1_*`, `inn2_*` | Runs, wickets (excluding retired hurt) and legal balls for each **regulation** innings. | 1,095 (3 have no 2nd innings) |
| T10 | deliveries | `delivery_id` | Surrogate key equal to the 1-based raw row number, for traceability. | 260,920 |
| T11 | deliveries | `is_super_over`, `super_over_number` | `inning ≥ 3` flagged. Rows kept. | 161 |
| T12 | deliveries | `over_number` | `over + 1` (1-based). Raw 0-based `over` kept. | 260,920 |
| T13 | deliveries | `is_wide`, `is_noball`, `is_bye`, `is_legbye`, `is_penalty` and the matching `*_runs` | Extras split into one flag and one runs column per type. | 260,920 |
| T14 | deliveries | `is_legal_delivery`, `legal_ball_in_over`, `over_legal_balls` | Legal = not a wide and not a no-ball. | 251,471 legal |
| T15 | deliveries | `is_seven_ball_over` | Overs with more than 6 legal balls flagged and kept as recorded. | 29 overs / 225 rows |
| T16 | deliveries | `phase` | Powerplay (overs 1–6), Middle (7–15), Death (16–20), Super Over. | 260,920 |
| T17 | deliveries | `bowler_runs_conceded` | Batter runs + wide runs + no-ball runs. | 260,920 |
| T18 | deliveries | `is_ball_faced` | Every delivery except wides. | 252,540 |
| T19 | deliveries | `is_dot_ball`, `is_four`, `is_six` | See definitions below. | 42,901 boundaries |
| T20 | deliveries | `is_player_out`, `is_bowler_wicket`, `is_retired_hurt`, `is_run_out` | Dismissal logic. The original `is_wicket`, `player_dismissed`, `dismissal_kind` and `fielder` are kept unchanged. | 12,935 outs; 11,815 bowler wickets; 15 retired hurt |

## 4. Cricket definitions used

| Metric | Definition in this project | Why |
|---|---|---|
| Legal delivery | `extras_type` is not `wides` or `noballs` | Wides and no-balls have to be bowled again, so they don't count toward the over. |
| Ball faced (batter) | Every delivery except wides | A batter does face a no-ball (and can score off it), but not a wide. |
| Batter runs | `batsman_runs` | Byes, leg-byes and wides are never batter runs (checked: 0 exceptions). |
| Bowler runs conceded | `batsman_runs + wide_runs + noball_runs` | Byes, leg-byes and penalty runs are not charged to the bowler. |
| Economy rate | `bowler_runs_conceded / legal deliveries × 6` | Uses legal deliveries only (applied in Phase 3). |
| Bowler wicket | `dismissal_kind` ∈ {bowled, caught, caught and bowled, lbw, stumped, hit wicket} | Run out, retired hurt, retired out and obstructing the field are not credited to the bowler. |
| Player out (for batting average) | `is_wicket = 1` and not `retired hurt` | A retired-hurt batter is not out. Retired out does count as a dismissal. The player who is out is `player_dismissed`, which can be the non-striker in a run-out. |
| Dot ball | Legal delivery with `total_runs = 0` | Team view. Bowler-only or batter-only versions can be derived from the flags. |
| Four / Six | `batsman_runs` = 4 / 6 | The source has no boundary flag. An all-run 4 can't be told apart from a boundary (rare). |
| Regulation statistics | `is_super_over = 0` | Super overs are left out of career and team totals by default. |
| `result_for` | `batting first` / `chasing` / `super over` / `no result`, based on who **actually** won | See the DLS finding in section 6. |

## 5. Data dictionary — cleaned datasets

### `data/processed/matches_clean.csv` (1,095 × 44, one row per match)

| Column | Description |
|---|---|
| `match_id` | PK (= raw `id`) |
| `season_year` | Year of play, from the date (2008–2024) |
| `season_label_original` | Raw season label |
| `match_date` | ISO date |
| `match_type`, `is_playoff` | Raw stage; 1 if not League |
| `venue`, `venue_original` | Standardised ground; raw name |
| `city`, `city_original`, `is_city_imputed` | Standardised city; raw city; 1 if it was filled in |
| `team1`, `team2` (+ `_original`) | Franchises (not batting order) |
| `toss_winner` (+ `_original`), `toss_decision`, `toss_winner_batted_first` | Toss facts |
| `batting_first_team`, `chasing_team` | Taken from the deliveries data |
| `winner` (+ `_original`) | Includes super-over winners; missing only for no-results |
| `result`, `result_margin` | Raw result type and margin |
| `win_type` | runs / wickets / super over / no result |
| `result_for` | batting first / chasing / super over / no result |
| `toss_winner_won` | 1/0; blank for no-results |
| `is_super_over`, `is_no_result`, `is_dls`, `method` | Flags; raw rain method |
| `target_runs`, `target_overs`, `target_balls` | Raw target, overs, and overs converted to balls |
| `inn1_runs`, `inn1_wickets`, `inn1_legal_balls`, `inn2_*` | Regulation innings totals; `inn2_*` blank when there was no 2nd innings |
| `player_of_match`, `umpire1`, `umpire2` | Raw |

### `data/processed/deliveries_clean.csv` (260,920 × 48, one row per delivery)

| Column group | Columns |
|---|---|
| Keys | `delivery_id` (PK), `match_id` (FK), `season_year` |
| Innings | `inning`, `is_super_over`, `super_over_number` |
| Teams | `batting_team`, `bowling_team` (+ `_original`) |
| Over / ball | `over` (raw, 0-based), `over_number` (1-based), `ball` (raw delivery sequence), `legal_ball_in_over`, `over_legal_balls`, `is_seven_ball_over`, `phase` |
| Players | `batter`, `non_striker`, `bowler` |
| Runs (raw) | `batsman_runs`, `extra_runs`, `total_runs`, `extras_type` |
| Extras split | `is_wide`, `is_noball`, `is_bye`, `is_legbye`, `is_penalty`, `wide_runs`, `noball_runs`, `bye_runs`, `legbye_runs`, `penalty_runs` |
| Derived run metrics | `is_legal_delivery`, `is_ball_faced`, `bowler_runs_conceded`, `is_dot_ball`, `is_four`, `is_six` |
| Wickets (raw) | `is_wicket`, `player_dismissed`, `dismissal_kind`, `fielder` |
| Wickets (derived) | `is_player_out`, `is_bowler_wicket`, `is_retired_hurt`, `is_run_out` |

All `is_*` flags are 0/1 integers, which works directly in MySQL and Power BI.

## 6. Findings investigated during Phase 2

**DLS chases won "by runs" (6 matches: 336022, 336025, 392186, 501245, 980943, 980997).** A first draft of check V53 assumed "won by runs ⇒ the team batting first won", and it failed for these 6 matches. When I looked into it, every one was a D/L match where rain stopped the chase while the chasing team was **ahead of the revised par score**. Under D/L that is recorded as a win by runs for the chasing team. In all 6 cases, margin = second-innings runs − par (par = `target_runs − 1`); for example, match 336022: 94 − 88 = 6. The data is correct and was not changed. The check was rewritten as V53 (non-DLS rule) plus V53b (D/L margin rule), and both pass.
**Impact on later phases:** "batting first vs chasing" analysis must use `result_for`, not `win_type`.

## 7. Comparison with published figures

These are informational, not part of the pass/fail checks. They are computed from `deliveries_clean.csv` with super overs excluded.

| Statistic | Computed | Published figure | Status |
|---|---|---|---|
| V Kohli career IPL runs, 2008–2024 | 8,004 | 8,004 (widely reported total after IPL 2024; e.g. cricketaddictor.com) | ✅ matches |
| YS Chahal career IPL wickets, 2008–2024 | 205 | Widely reported as 205 after IPL 2024 | ⚠ consistent, but not confirmed by a source in this session |

## 8. Limitations added in Phase 2

| # | Limitation |
|---|---|
| L10 | The phase boundaries (1–6 / 7–15 / 16–20) are the standard for 20-over innings. Reduced-overs matches (DLS or rain-shortened) had shorter real powerplays, but their overs are still labelled by number. This affects a small number of matches (see `is_dls` and `target_overs`). |
| L11 | `is_four` / `is_six` come from runs, not from a boundary flag (see section 4). |
| L12 | No-ball rows that also had byes are recorded by the source as `noballs` only, so all their extras count as bowler runs conceded (limitation L5 from Phase 1). |
