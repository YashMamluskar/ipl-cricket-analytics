# Data Dictionary — Raw IPL Datasets

**Scope:** the two raw files in `data/raw/` exactly as received. Column meanings were confirmed by checking the data (see `reports/validation/phase1_initial_data_quality_report.md`), not assumed from the column names.
Counts come from `python/01_data_profiling.py`. Columns derived in Phase 2 will be documented separately once they exist.

**Missing-value encoding:** most columns use the literal text `NA`. `deliveries.extras_type` instead uses an **empty string**. `pandas.read_csv` turns both into `NaN` by default. The MySQL import in Phase 4 must handle both encodings explicitly.

---

## 1. `matches.csv` — one row per match (1,095 rows × 20 columns)

| # | Column | Raw type | Meaning | Example | Missing | Notes / verified rules |
|---|---|---|---|---|---|---|
| 1 | `id` | int | Unique match identifier (it matches the ESPNcricinfo/Cricsheet match ID) | 335982 | 0 | **Primary key.** Unique for all 1,095 rows. |
| 2 | `season` | text | Season label as the source wrote it | `2007/08`, `2013` | 0 | ⚠ Three labels don't match the year the season was played: `2007/08` = 2008, `2009/10` = 2010, `2020/21` = 2020. Each label covers exactly one calendar year, so the season year can be taken from `date`. |
| 3 | `city` | text | Host city | Mumbai | 51 (4.7%) | All 51 missing values are Dubai International Cricket Stadium (33) or Sharjah Cricket Stadium (18), so the city can be recovered from the venue. `Bangalore` and `Bengaluru` both appear. |
| 4 | `date` | text (ISO `YYYY-MM-DD`) | Match date | 2008-04-18 | 0 | All values parse. Range 2008-04-18 to 2024-05-26. |
| 5 | `match_type` | text | Stage of the tournament | League, Final, Qualifier 1 | 0 | 8 values. Older playoff names (`Semi Final`, `Elimination Final`, `3rd Place Play-Off`) sit next to newer ones (`Qualifier 1/2`, `Eliminator`). |
| 6 | `player_of_match` | text | Player of the match award | BB McCullum | 5 | Missing only in the 5 no-result matches. Every name also appears in the deliveries data. |
| 7 | `venue` | text | Ground name | Wankhede Stadium | 0 | ⚠ 58 strings for fewer real grounds. Some differ only in suffix (`Wankhede Stadium` vs `Wankhede Stadium, Mumbai`); others are renamed grounds (see Phase 2 notes). |
| 8 | `team1` | text | One of the two teams | Royal Challengers Bangalore | 0 | ⚠ **Not** the team batting first (true in only 72.6% of matches). Get batting order from the toss or from the deliveries data. |
| 9 | `team2` | text | The other team | Kolkata Knight Riders | 0 | Same caveat as `team1`. |
| 10 | `toss_winner` | text | Team that won the toss | Royal Challengers Bangalore | 0 | Always one of team1/team2. |
| 11 | `toss_decision` | text | Toss winner's choice | `bat` / `field` | 0 | 2 values. Toss winner + decision correctly gives the innings-1 batting team in all 1,095 matches. |
| 12 | `winner` | text | Match winner, including super-over winners | Kolkata Knight Riders | 5 | Missing only when `result = no result`. Always one of team1/team2. |
| 13 | `result` | text | How the match was decided | `wickets` 578, `runs` 498, `tie` 14, `no result` 5 | 0 | `tie` means the scores were level after 20 overs; all 14 ties were then settled by a super over. |
| 14 | `result_margin` | float | Winning margin in the unit given by `result` | 140 | 19 | Missing for ties (14) and no-results (5). Checked against the deliveries data for all non-DLS decided matches (0 mismatches). |
| 15 | `target_runs` | float | Target set for the team batting second | 223 | 3 | Equals first-innings runs + 1 in all 1,071 non-DLS matches. The 21 DLS matches have a revised target. Missing in 3 no-results where the second innings never started. |
| 16 | `target_overs` | float | Overs available for the chase | 20 | 3 | 20 in 1,062 matches. Shorter in DLS or rain-shortened games (minimum 5). `9.2` means 9 overs and 2 balls, **not** a decimal. |
| 17 | `super_over` | text | Whether a super over was played | `N` / `Y` | 0 | 14 `Y`. Matches exactly the matches with `inning ≥ 3` in deliveries. |
| 18 | `method` | text | Rain rule applied | `D/L` | 1,074 | Present only for the 21 Duckworth-Lewis(-Stern) matches. |
| 19 | `umpire1` | text | On-field umpire | Asad Rauf | 0 | |
| 20 | `umpire2` | text | On-field umpire | RE Koertzen | 0 | 70 distinct umpires across both columns. |

---

## 2. `deliveries.csv` — one row per ball bowled (260,920 rows × 17 columns)

Each row is one delivery, **including** wides and no-balls (which have to be bowled again) and super-over deliveries.

| # | Column | Raw type | Meaning | Example | Missing | Notes / verified rules |
|---|---|---|---|---|---|---|
| 1 | `match_id` | int | Match the ball belongs to | 335982 | 0 | **Foreign key → `matches.id`.** No orphan rows. |
| 2 | `inning` | int | Innings number | 1 | 0 | 1–2 = normal innings. 3–4 = super over. 5–6 = second super over (one match, 2020). |
| 3 | `batting_team` | text | Team batting | Kolkata Knight Riders | 0 | Always one of the match's team1/team2, and never equal to `bowling_team`. |
| 4 | `bowling_team` | text | Team bowling | Royal Challengers Bangalore | 0 | |
| 5 | `over` | int | Over number, **counting from 0** | 0 | 0 | Range 0–19. Over 0 is the 1st over, so cricket over = `over + 1`. No missing overs in any innings. |
| 6 | `ball` | int | Order of the delivery within the over, **including extras** | 1 | 0 | Range 1–11. Values above 6 happen because wides/no-balls are bowled again. **Not** the legal-ball count. Numbering is continuous (1..n) in every over. |
| 7 | `batter` | text | Striker (player facing) | SC Ganguly | 0 | 673 distinct. Names in Cricsheet style (initials + surname). |
| 8 | `bowler` | text | Bowler | P Kumar | 0 | 530 distinct. |
| 9 | `non_striker` | text | Batter at the bowler's end | BB McCullum | 0 | |
| 10 | `batsman_runs` | int | Runs credited to the batter off the bat | 4 | 0 | Values 0–6. Always 0 on wides, byes and leg-byes. Can be > 0 on no-balls. `5` (65 rows) = runs plus overthrows. |
| 11 | `extra_runs` | int | Runs added as extras | 1 | 0 | Values 0–7. > 0 exactly when `extras_type` is filled. |
| 12 | `total_runs` | int | Runs added to the team total | 1 | 0 | Equals `batsman_runs + extra_runs` on every row. |
| 13 | `extras_type` | text | Type of extra | wides, legbyes, noballs, byes, penalty | 246,795 (blank) | Missing means a normal ball. Only **one** type per ball, so a no-ball that also produced byes is recorded only as `noballs`. |
| 14 | `is_wicket` | int (0/1) | A player was out (or retired) on this ball | 0 | 0 | ⚠ Includes run-outs, `retired hurt`, `retired out` and `obstructing the field`. **Not** the same as bowler wickets. Counting only `is_wicket = 1` rows **also** includes `retired hurt`, which is not a dismissal. |
| 15 | `player_dismissed` | text | Player who was out | V Kohli | 247,970 | Filled exactly when `is_wicket = 1`. Always the striker or the non-striker. |
| 16 | `dismissal_kind` | text | How the player was out | caught 8,063, bowled 2,212, run out 1,114, lbw 800, caught and bowled 367, stumped 358, retired hurt 15, hit wicket 15, obstructing the field 3, retired out 3 | 247,970 | Filled exactly when `is_wicket = 1`. |
| 17 | `fielder` | text | Fielder involved (catcher, stumper, run-out thrower) | MS Dhoni | 251,566 | Filled for all caught/stumped dismissals and 933 of 1,114 run-outs. Not filled for `caught and bowled` (the bowler is the catcher). 9 names never bat or bowl; they are substitute fielders. |

---

## 3. Cricket scoring rules confirmed in this data

| Rule | How it shows in the data | Verified |
|---|---|---|
| Wides and no-balls are not legal balls | `extras_type ∈ {wides, noballs}` → do not count in balls faced or overs bowled | Structure confirmed (41,543 overs have exactly 6 legal balls) |
| Byes / leg-byes are not batter runs | `batsman_runs = 0` on every bye/leg-bye row | ✅ 0 exceptions |
| Wide runs are not batter runs | `batsman_runs = 0` on every wide | ✅ 0 exceptions |
| Runs off the bat on a no-ball count for the batter | 623 no-balls have `batsman_runs > 0` | ✅ kept as recorded |
| Byes and leg-byes are not charged to the bowler | must be removed when calculating bowler runs conceded | rule for Phase 2 |
| Penalty runs go to the team only | 2 `penalty` rows | rule for Phase 2 |
| Run out, retired hurt/out and obstructing the field are not bowler wickets | `dismissal_kind` must be filtered | rule for Phase 2 |
| Retired hurt is not out | 15 rows have `is_wicket = 1` but the batter is not out | rule for Phase 2 |
| Team total = sum of `total_runs` | target = innings-1 total + 1 in 1,071/1,071 non-DLS matches | ✅ |
