# Database Schema — `ipl_cricket_analytics` (MySQL 8.0)

Source DDL: `sql/02_create_tables.sql` (tables), `sql/03_create_indexes.sql` (indexes) and `sql/04_create_views.sql` (views). ER diagram: [database_relationships.md](database_relationships.md).

## 1. Design choice: hybrid star schema

| Option | Verdict |
|---|---|
| Two flat tables (matches + deliveries as CSV) | Rejected. Team, venue and player names would repeat across 260,920 rows, and nothing would enforce referential integrity. |
| Fully normalised (separate `innings`, `over` and `season` tables) | Rejected. It adds joins without analytical benefit: a season is just an attribute of a match, and innings totals are already validated columns. |
| **Hybrid star (chosen)** | **Dimensions** (`team`, `venue`, `player` and two alias tables) store each name once. **Facts** (`matches`, `deliveries`) store integer keys plus the approved Phase 2 flags and derived columns. This avoids duplicate names and preserves lineage, and SQL uses exactly the same validated definitions as Python. It is also a natural shape for Power BI later. |

Other decisions:
- **Surrogate keys** are assigned alphabetically, so they are stable across reloads. `match_id` keeps the **original source ID**, and `delivery_id` equals the raw CSV row number.
- **Audit columns:** every standardised value keeps its original in an `*_original` column (`team1_original`, `venue_original`, `city_original`, `batting_team_original`, …), and the alias tables record why each mapping was made.
- **Derived columns are stored, not recomputed** (`is_legal_delivery`, `bowler_runs_conceded`, `is_bowler_wicket`, `result_for`, `inn1_runs`, …). They were validated in Phase 2 (60 checks) and recomputing them in SQL could introduce drift. Check Q16 confirms the innings totals still equal the sum of their deliveries.
- **Collation is `utf8mb4_0900_as_cs`** (accent- and case-sensitive). Names are identifiers, so a lenient collation must never merge two different players.
- **`over_raw`** stores the source `over` column, because `OVER` is a reserved word in MySQL 8 (window functions).
- **Strict SQL mode** in every session, so malformed values raise an error instead of being silently coerced.

## 2. Tables

| Table | Rows | Primary key | Purpose |
|---|---:|---|---|
| `team` | 15 | `team_id` | Standardised franchises (`franchise_name` UNIQUE) |
| `team_name_alias` | 19 | `team_name_original` | Original name → franchise, mapping type, approval |
| `venue` | 36 | `venue_id` | Standardised grounds with their single standardised city |
| `venue_alias` | 58 | `venue_original` | Original venue → ground, reason, verification, approval |
| `player` | 741 | `player_id` | Every person in any role (`player_name` UNIQUE) |
| `matches` | 1,095 | `match_id` (source ID) | One row per match: 44 columns from `matches_clean.csv`, with names replaced by keys |
| `deliveries` | 260,920 | `delivery_id` | One row per ball, including wides, no-balls and super overs. UNIQUE `(match_id, inning, over_raw, ball)` |

### Key `matches` columns
`season_year`, `match_date` (DATE), `venue_id`, `team1_id`, `team2_id`, `toss_winner_id`, `toss_decision` (ENUM), **`batting_first_team_id`**, **`chasing_team_id`**, `winner_id` (NULL = no result), `result` and `win_type` (ENUM), **`result_for`** (ENUM: batting first / chasing / super over / no result), `is_super_over`, `is_no_result`, `is_dls`, `target_runs`, `target_overs` (DECIMAL(4,1), cricket notation), `target_balls`, `inn1_*` and `inn2_*` (regulation innings totals), `player_of_match_id`.

### Key `deliveries` columns
`inning`, `is_super_over`, `over_raw` (0-based), `over_number` (1-based), `ball`, `phase` (ENUM), the five player keys (`batter_id`, `non_striker_id`, `bowler_id`, `player_dismissed_id`, `fielder_id`), the raw runs (`batsman_runs`, `extra_runs`, `total_runs`, `extras_type` ENUM), the per-type extras columns, `bowler_runs_conceded`, `is_legal_delivery`, `is_ball_faced`, `is_dot_ball`, `is_four`, `is_six`, the raw `is_wicket` and `dismissal_kind`, and the derived **`is_player_out`** and **`is_bowler_wicket`**.

Data types: flags are `TINYINT(1)`, small counts are `TINYINT`/`SMALLINT UNSIGNED`, categories are `ENUM` (MySQL rejects invalid values), and names are `VARCHAR` sized from the profiled maximum lengths.

## 3. Constraints (live server: 18 foreign keys, 6 CHECK constraints)

| Constraint | Rule |
|---|---|
| `ck_d_runs` | `total_runs = batsman_runs + extra_runs` |
| `ck_d_teams` | batting team ≠ bowling team |
| `ck_d_over` | `over_number = over_raw + 1`, between 1 and 20 |
| `ck_m_teams_differ` / `ck_m_order_differ` | team1 ≠ team2; batting-first team ≠ chasing team |
| `ck_m_winner_nr` | `winner_id IS NULL` exactly when `is_no_result = 1` |

## 4. Indexes

InnoDB automatically indexes every primary key, unique key and foreign key, giving 23 indexes. `sql/03_create_indexes.sql` adds 9 composite indexes for the analysis access paths, for 32 in total on the live server:

| Index | Supports |
|---|---|
| `ix_matches_season (season_year, match_id)` | Season filters and trends |
| `ix_matches_result_for (result_for, season_year)` | Batting-first / chasing analysis |
| `ix_deliv_batter_reg (batter_id, is_super_over)` | Batter careers (regulation only) |
| `ix_deliv_bowler_reg (bowler_id, is_super_over)` | Bowler careers |
| `ix_deliv_dismissed_reg (player_dismissed_id, is_super_over)` | Dismissal counts |
| `ix_deliv_match_inning (match_id, inning, is_super_over)` | Innings totals, batting innings |
| `ix_deliv_phase (phase, is_super_over)` | Phase analysis |
| `ix_deliv_bowl_team` / `ix_deliv_bat_team (team_id, match_id)` | Team bowling and batting by season |

## 5. Views (business rules defined once)

| View | Definition |
|---|---|
| `v_reg_deliveries` | Deliveries with `is_super_over = 0`, plus `season_year` and `venue_id` |
| `v_full_matches` | Matches with `is_no_result = 0 AND target_overs = 20` (base for score averages) |
| `v_match_summary` | Matches with every key resolved to a readable name |
| `v_team_match` | Two rows per match (batting-first and chasing team): `won`, `decided`, `result_for` |
| `v_batting_innings` | One row per (match, innings, player who batted), using the same appearance rule as Python |
| `v_batter_career` | Innings, runs, balls, outs, average, strike rate, 4s, 6s, 50s, 100s, % of innings with 30+ |
| `v_bowler_career` | Legal balls, runs conceded, bowler wickets, economy, average, strike rate, dot % |
| `v_season_summary` | Season matches, runs, wickets, run rate and full-match averages |

Ratios in the views are left **unrounded**, and presentation queries round them. Sessions set `div_precision_increment = 30` (MySQL's default of 4 would round division results).
