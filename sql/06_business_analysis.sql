-- =============================================================================
-- 06_business_analysis.sql
-- IPL Cricket Analytics - SQL business analysis (27 questions + super-over view)
--
-- Each query starts with a tag line:   -- @Qnn | <section> | <title>
-- python/04c_run_sql_analysis.py executes every tagged query, saves the output to
-- reports/sql_query_results/Qnn.csv and builds reports/sql_business_analysis_report.md.
-- Every query also runs as-is in MySQL Workbench (USE ipl_cricket_analytics first).
--
-- Conventions (see sql/04_create_views.sql):
--   regulation only (super overs excluded) | bowler wickets = is_bowler_wicket |
--   batting order & outcome from batting_first_team_id / chasing_team_id / result_for |
--   thresholds identical to Python EDA: 50 innings, 500 balls, 1000 legal balls,
--   300 phase balls (batting), 600 phase balls (bowling), 20 venue matches, 20 team matches.
-- =============================================================================

USE ipl_cricket_analytics;

-- =============================================================================
-- A. IPL OVERVIEW
-- =============================================================================

-- @Q01 | A. IPL overview | Matches played per season
SELECT season_year,
       COUNT(*)            AS matches,
       SUM(is_playoff)     AS playoff_matches,
       SUM(is_super_over)  AS tied_super_over,
       SUM(is_no_result)   AS no_results,
       SUM(is_dls)         AS dls_matches
FROM matches
GROUP BY season_year
ORDER BY season_year;

-- @Q02 | A. IPL overview | Runs and bowler-credited wickets per season
SELECT season_year,
       SUM(total_runs)                                   AS total_runs,
       SUM(is_bowler_wicket)                             AS bowler_wickets,
       SUM(is_player_out)                                AS all_dismissals,
       SUM(SUM(total_runs)) OVER (ORDER BY season_year)  AS cumulative_runs
FROM v_reg_deliveries
GROUP BY season_year
ORDER BY season_year;

-- @Q03 | A. IPL overview | Seasons ranked by average first-innings score
SELECT season_year,
       COUNT(*)                                       AS full_matches,
       ROUND(AVG(inn1_runs), 2)                       AS avg_first_innings,
       RANK() OVER (ORDER BY AVG(inn1_runs) DESC)     AS rank_high_to_low
FROM v_full_matches
GROUP BY season_year
ORDER BY rank_high_to_low;

-- @Q04 | A. IPL overview | Scoring rate by season and phase, with change vs previous season
WITH season_rates AS (
    SELECT season_year,
           SUM(total_runs) * 6 / SUM(is_legal_delivery) AS run_rate,
           SUM(CASE WHEN phase = 'Powerplay' THEN total_runs END) * 6
             / SUM(CASE WHEN phase = 'Powerplay' THEN is_legal_delivery END) AS rr_powerplay,
           SUM(CASE WHEN phase = 'Middle' THEN total_runs END) * 6
             / SUM(CASE WHEN phase = 'Middle' THEN is_legal_delivery END)    AS rr_middle,
           SUM(CASE WHEN phase = 'Death' THEN total_runs END) * 6
             / SUM(CASE WHEN phase = 'Death' THEN is_legal_delivery END)     AS rr_death
    FROM v_reg_deliveries
    GROUP BY season_year
)
SELECT season_year,
       ROUND(run_rate, 2)                                       AS run_rate,
       ROUND(run_rate - LAG(run_rate) OVER (ORDER BY season_year), 2) AS change_vs_prev,
       ROUND(rr_powerplay, 2) AS rr_powerplay,
       ROUND(rr_middle, 2)    AS rr_middle,
       ROUND(rr_death, 2)     AS rr_death
FROM season_rates
ORDER BY season_year;

-- @Q05 | A. IPL overview | Seasons ranked by average runs per match
SELECT season_year,
       matches,
       ROUND(runs_per_match, 1)        AS runs_per_match_all,
       full_matches,
       ROUND(runs_per_full_match, 1)   AS runs_per_full_match,
       RANK() OVER (ORDER BY runs_per_full_match DESC) AS rank_full_match
FROM v_season_summary
ORDER BY rank_full_match;

-- =============================================================================
-- B. TEAM PERFORMANCE
-- =============================================================================

-- @Q06 | B. Team performance | Franchises with the most wins (and titles)
WITH titles AS (
    SELECT winner_id AS team_id, COUNT(*) AS titles
    FROM matches
    WHERE match_type = 'Final'
    GROUP BY winner_id
)
SELECT t.franchise_name,
       COUNT(DISTINCT tm.season_year) AS seasons,
       COUNT(*)                       AS matches,
       SUM(tm.won)                    AS wins,
       SUM(tm.decided) - SUM(tm.won)  AS losses,
       SUM(tm.is_no_result)           AS no_results,
       COALESCE(ti.titles, 0)         AS titles
FROM v_team_match tm
JOIN team t        ON t.team_id = tm.team_id
LEFT JOIN titles ti ON ti.team_id = tm.team_id
GROUP BY t.team_id, t.franchise_name, ti.titles
ORDER BY wins DESC, titles DESC;

-- @Q07 | B. Team performance | Win percentage by franchise
SELECT t.franchise_name,
       COUNT(DISTINCT tm.season_year)              AS seasons,
       SUM(tm.decided)                             AS decided_matches,
       SUM(tm.won)                                 AS wins,
       ROUND(SUM(tm.won) * 100 / SUM(tm.decided), 2) AS win_pct,
       CASE WHEN COUNT(DISTINCT tm.season_year) >= 10 THEN 'established (10+ seasons)'
            ELSE 'short-lived / small sample' END  AS sample_note
FROM v_team_match tm
JOIN team t ON t.team_id = tm.team_id
GROUP BY t.team_id, t.franchise_name
ORDER BY win_pct DESC;

-- @Q08 | B. Team performance | Best records batting first (min 20 matches)
SELECT t.franchise_name,
       COUNT(*)                          AS bat_first_matches,
       SUM(tm.won)                       AS bat_first_wins,
       ROUND(SUM(tm.won) * 100 / COUNT(*), 2) AS bat_first_win_pct
FROM v_team_match tm
JOIN team t ON t.team_id = tm.team_id
WHERE tm.batted_first = 1
  AND tm.result_for IN ('batting first', 'chasing')   -- excludes super-over ties and no-results
GROUP BY t.team_id, t.franchise_name
HAVING COUNT(*) >= 20
ORDER BY bat_first_win_pct DESC;

-- @Q09 | B. Team performance | Best records chasing (min 20 matches)
SELECT t.franchise_name,
       COUNT(*)                          AS chase_matches,
       SUM(tm.won)                       AS chase_wins,
       ROUND(SUM(tm.won) * 100 / COUNT(*), 2) AS chase_win_pct
FROM v_team_match tm
JOIN team t ON t.team_id = tm.team_id
WHERE tm.batted_first = 0
  AND tm.result_for IN ('batting first', 'chasing')
GROUP BY t.team_id, t.franchise_name
HAVING COUNT(*) >= 20
ORDER BY chase_win_pct DESC;

-- @Q10 | B. Team performance | Season-adjusted first-innings scoring by team
-- Adjustment: each first-innings score minus that season's average first-innings score
-- (window function over full matches). Same 20-innings rule as Python (both roles).
WITH f AS (
    SELECT batting_first_team_id, chasing_team_id, season_year, inn1_runs, inn2_runs,
           inn1_runs - AVG(inn1_runs) OVER (PARTITION BY season_year) AS inn1_vs_season
    FROM v_full_matches
),
first_inn AS (
    SELECT batting_first_team_id AS team_id, COUNT(*) AS inn1_innings,
           AVG(inn1_runs) AS avg_inn1, AVG(inn1_vs_season) AS avg_inn1_vs_season
    FROM f GROUP BY batting_first_team_id
),
second_inn AS (
    SELECT chasing_team_id AS team_id, COUNT(*) AS inn2_innings, AVG(inn2_runs) AS avg_inn2
    FROM f GROUP BY chasing_team_id
)
SELECT t.franchise_name,
       fi.inn1_innings,
       ROUND(fi.avg_inn1, 2)            AS avg_first_innings,
       ROUND(fi.avg_inn1_vs_season, 2)  AS vs_season_avg,
       si.inn2_innings,
       ROUND(si.avg_inn2, 2)            AS avg_second_innings
FROM first_inn fi
JOIN second_inn si ON si.team_id = fi.team_id
JOIN team t        ON t.team_id  = fi.team_id
WHERE fi.inn1_innings >= 20 AND si.inn2_innings >= 20
ORDER BY fi.avg_inn1_vs_season DESC;

-- @Q11 | B. Team performance | Season-adjusted team bowling economy
-- expected runs = legal balls bowled x league runs-per-ball in the same season
WITH league AS (
    SELECT season_year, SUM(total_runs) / SUM(is_legal_delivery) AS runs_per_ball
    FROM v_reg_deliveries GROUP BY season_year
),
team_season AS (
    SELECT bowling_team_id AS team_id, season_year,
           SUM(total_runs) AS runs, SUM(is_legal_delivery) AS balls, SUM(is_player_out) AS dismissals
    FROM v_reg_deliveries GROUP BY bowling_team_id, season_year
)
SELECT t.franchise_name,
       COUNT(*)                                                      AS seasons,
       SUM(ts.balls)                                                 AS legal_balls,
       ROUND(SUM(ts.runs) * 6 / SUM(ts.balls), 2)                    AS economy,
       ROUND((SUM(ts.runs) - SUM(ts.balls * l.runs_per_ball)) * 6 / SUM(ts.balls), 3) AS economy_vs_league,
       ROUND(SUM(ts.balls) / SUM(ts.dismissals), 2)                  AS balls_per_dismissal,
       RANK() OVER (ORDER BY (SUM(ts.runs) - SUM(ts.balls * l.runs_per_ball)) / SUM(ts.balls)) AS era_adjusted_rank
FROM team_season ts
JOIN league l ON l.season_year = ts.season_year
JOIN team t   ON t.team_id = ts.team_id
GROUP BY t.team_id, t.franchise_name
ORDER BY era_adjusted_rank;

-- =============================================================================
-- C. BATTING
-- =============================================================================

-- @Q12 | C. Batting | Top 10 run scorers
SELECT player_name, innings, runs, balls, outs,
       ROUND(batting_average, 2) AS batting_average,
       ROUND(strike_rate, 2)     AS strike_rate,
       highest, fifties, hundreds
FROM v_batter_career
ORDER BY runs DESC
LIMIT 10;

-- @Q13 | C. Batting | Highest batting averages (min 50 innings)
SELECT player_name, innings, runs, outs, not_outs,
       ROUND(batting_average, 2) AS batting_average,
       ROUND(strike_rate, 2)     AS strike_rate
FROM v_batter_career
WHERE innings >= 50
ORDER BY batting_average DESC
LIMIT 10;

-- @Q14 | C. Batting | Highest strike rates (min 500 balls faced)
SELECT player_name, innings, runs, balls,
       ROUND(strike_rate, 2)     AS strike_rate,
       ROUND(batting_average, 2) AS batting_average
FROM v_batter_career
WHERE balls >= 500
ORDER BY strike_rate DESC
LIMIT 10;

-- @Q15 | C. Batting | Most sixes and fours (run-based proxy)
WITH ranked AS (
    SELECT player_name, balls, sixes, fours,
           RANK() OVER (ORDER BY sixes DESC) AS six_rank,
           RANK() OVER (ORDER BY fours DESC) AS four_rank,
           (4 * fours + 6 * sixes) * 100 / NULLIF(runs, 0) AS boundary_run_pct
    FROM v_batter_career
)
SELECT player_name, sixes, six_rank, fours, four_rank,
       ROUND(balls / NULLIF(sixes, 0), 1) AS balls_per_six,
       ROUND(boundary_run_pct, 1)         AS boundary_run_pct
FROM ranked
WHERE six_rank <= 10 OR four_rank <= 10
ORDER BY six_rank, four_rank;

-- @Q16 | C. Batting | Most consistent batters (min 50 innings): share of innings with 30+
SELECT player_name, innings,
       ROUND(runs / innings, 2)  AS mean_score,
       ROUND(pct_30_plus, 2)     AS pct_30_plus,
       ROUND(pct_under_10, 2)    AS pct_under_10,
       ROUND(batting_average, 2) AS batting_average
FROM v_batter_career
WHERE innings >= 50
ORDER BY pct_30_plus DESC
LIMIT 10;

-- @Q17 | C. Batting | Fastest scorers in each phase (min 300 balls in that phase), top 5 per phase
WITH phase_batting AS (
    SELECT phase, batter_id,
           SUM(batsman_runs) AS runs, SUM(is_ball_faced) AS balls, SUM(is_six) AS sixes
    FROM v_reg_deliveries
    GROUP BY phase, batter_id
    HAVING SUM(is_ball_faced) >= 300
),
ranked AS (
    SELECT pb.*, runs * 100 / balls AS strike_rate,
           ROW_NUMBER() OVER (PARTITION BY phase ORDER BY runs / balls DESC) AS rn
    FROM phase_batting pb
)
SELECT r.phase, r.rn AS phase_rank, p.player_name, r.balls, r.runs, r.sixes, ROUND(r.strike_rate, 2) AS strike_rate
FROM ranked r
JOIN player p ON p.player_id = r.batter_id
WHERE r.rn <= 5
ORDER BY FIELD(r.phase, 'Powerplay', 'Middle', 'Death'), r.rn;

-- =============================================================================
-- D. BOWLING
-- =============================================================================

-- @Q18 | D. Bowling | Top 10 bowler-credited wicket takers
SELECT player_name, innings, legal_balls, wickets, runs_conceded,
       ROUND(economy, 2)             AS economy,
       ROUND(bowling_average, 2)     AS bowling_average,
       ROUND(bowling_strike_rate, 2) AS bowling_strike_rate
FROM v_bowler_career
ORDER BY wickets DESC
LIMIT 10;

-- @Q19 | D. Bowling | Best economy (min 1,000 legal deliveries)
SELECT player_name, legal_balls, runs_conceded, wickets,
       ROUND(economy, 2) AS economy,
       ROUND(dot_pct, 1) AS dot_pct
FROM v_bowler_career
WHERE legal_balls >= 1000
ORDER BY economy
LIMIT 10;

-- @Q20 | D. Bowling | Best bowling averages and strike rates (min 1,000 legal deliveries)
SELECT player_name, legal_balls, wickets,
       ROUND(bowling_average, 2)                       AS bowling_average,
       RANK() OVER (ORDER BY bowling_average)          AS average_rank,
       ROUND(bowling_strike_rate, 2)                   AS bowling_strike_rate,
       RANK() OVER (ORDER BY bowling_strike_rate)      AS strike_rate_rank
FROM v_bowler_career
WHERE legal_balls >= 1000
ORDER BY average_rank
LIMIT 10;

-- @Q21 | D. Bowling | Most economical bowlers by phase (min 600 legal balls in phase), top 5 per phase
WITH phase_bowling AS (
    SELECT phase, bowler_id,
           SUM(is_legal_delivery) AS legal_balls, SUM(bowler_runs_conceded) AS runs_conceded,
           SUM(is_bowler_wicket) AS wickets
    FROM v_reg_deliveries
    GROUP BY phase, bowler_id
    HAVING SUM(is_legal_delivery) >= 600
),
ranked AS (
    SELECT pb.*, runs_conceded * 6 / legal_balls AS economy,
           ROW_NUMBER() OVER (PARTITION BY phase ORDER BY runs_conceded / legal_balls) AS rn
    FROM phase_bowling pb
)
SELECT r.phase, r.rn AS phase_rank, p.player_name, r.legal_balls, r.wickets,
       ROUND(r.economy, 2) AS economy,
       ROUND(r.legal_balls / NULLIF(r.wickets, 0), 1) AS bowling_strike_rate
FROM ranked r
JOIN player p ON p.player_id = r.bowler_id
WHERE r.rn <= 5
ORDER BY FIELD(r.phase, 'Powerplay', 'Middle', 'Death'), r.rn;

-- @Q22 | D. Bowling | League economy and wicket-taking rate by season
WITH s AS (
    SELECT season_year,
           SUM(total_runs) * 6 / SUM(is_legal_delivery)        AS economy,
           SUM(is_legal_delivery) / SUM(is_bowler_wicket)      AS balls_per_bowler_wicket,
           SUM(is_dot_ball) * 100 / SUM(is_legal_delivery)     AS dot_pct
    FROM v_reg_deliveries
    GROUP BY season_year
)
SELECT season_year,
       ROUND(economy, 2)                                            AS economy,
       ROUND(economy - LAG(economy) OVER (ORDER BY season_year), 2) AS economy_change,
       ROUND(balls_per_bowler_wicket, 2)                            AS balls_per_bowler_wicket,
       ROUND(dot_pct, 2)                                            AS dot_pct
FROM s
ORDER BY season_year;

-- =============================================================================
-- E. MATCH & VENUE
-- =============================================================================

-- @Q23 | E. Match & venue | Toss winner vs match winner
SELECT 'All decided matches'     AS segment, COUNT(*) AS matches, SUM(toss_winner_won) AS toss_winner_won,
       ROUND(AVG(toss_winner_won) * 100, 2) AS toss_winner_win_pct
FROM matches WHERE is_no_result = 0
UNION ALL
SELECT CONCAT('Toss winner chose to ', toss_decision), COUNT(*), SUM(toss_winner_won),
       ROUND(AVG(toss_winner_won) * 100, 2)
FROM matches WHERE is_no_result = 0
GROUP BY toss_decision;

-- @Q24 | E. Match & venue | Win share batting first vs chasing (all decided, and excluding D/L)
SELECT 'All decided matches' AS segment,
       COUNT(*) AS matches,
       ROUND(SUM(result_for = 'batting first') * 100 / COUNT(*), 2) AS batting_first_win_pct,
       ROUND(SUM(result_for = 'chasing') * 100 / COUNT(*), 2)       AS chasing_win_pct
FROM matches WHERE result_for IN ('batting first', 'chasing')
UNION ALL
SELECT 'Excluding D/L matches', COUNT(*),
       ROUND(SUM(result_for = 'batting first') * 100 / COUNT(*), 2),
       ROUND(SUM(result_for = 'chasing') * 100 / COUNT(*), 2)
FROM matches WHERE result_for IN ('batting first', 'chasing') AND is_dls = 0;

-- @Q25 | E. Match & venue | Venues ranked by season-adjusted first-innings score (min 20 full matches)
WITH f AS (
    SELECT venue_id, season_year, inn1_runs,
           inn1_runs - AVG(inn1_runs) OVER (PARTITION BY season_year) AS inn1_vs_season
    FROM v_full_matches
)
SELECT v.venue_name, v.city,
       COUNT(*)                         AS full_matches,
       MIN(f.season_year)               AS first_season,
       MAX(f.season_year)               AS last_season,
       ROUND(AVG(f.inn1_runs), 2)       AS avg_first_innings,
       ROUND(AVG(f.inn1_vs_season), 2)  AS vs_season_avg
FROM f
JOIN venue v ON v.venue_id = f.venue_id
GROUP BY v.venue_id, v.venue_name, v.city
HAVING COUNT(*) >= 20
ORDER BY vs_season_avg DESC;

-- @Q26 | E. Match & venue | Venues ranked by chasing success (min 20 decided matches)
SELECT v.venue_name, v.city,
       COUNT(*)                                             AS decided_matches,
       SUM(m.result_for = 'chasing')                        AS chase_wins,
       ROUND(SUM(m.result_for = 'chasing') * 100 / COUNT(*), 2) AS chase_win_pct
FROM matches m
JOIN venue v ON v.venue_id = m.venue_id
WHERE m.result_for IN ('batting first', 'chasing')
GROUP BY v.venue_id, v.venue_name, v.city
HAVING COUNT(*) >= 20
ORDER BY chase_win_pct DESC;

-- @Q27 | E. Match & venue | Most common winning margins (non-D/L)
WITH margins AS (
    SELECT 'Batting first (runs)' AS margin_type,
           CASE WHEN result_margin <= 10 THEN '1-10 runs'
                WHEN result_margin <= 20 THEN '11-20 runs'
                WHEN result_margin <= 30 THEN '21-30 runs'
                WHEN result_margin <= 50 THEN '31-50 runs'
                ELSE '51+ runs' END AS margin_band
    FROM matches WHERE is_dls = 0 AND result_for = 'batting first'
    UNION ALL
    SELECT 'Chasing (wickets)', CONCAT(LPAD(result_margin, 2, '0'), ' wickets')
    FROM matches WHERE is_dls = 0 AND result_for = 'chasing'
)
SELECT margin_type, margin_band,
       COUNT(*) AS matches,
       ROUND(COUNT(*) * 100 / SUM(COUNT(*)) OVER (PARTITION BY margin_type), 2) AS pct_of_type,
       RANK() OVER (PARTITION BY margin_type ORDER BY COUNT(*) DESC)          AS frequency_rank
FROM margins
GROUP BY margin_type, margin_band
ORDER BY margin_type, margin_band;

-- =============================================================================
-- SUPER OVERS (kept separate from all statistics above)
-- =============================================================================

-- @Q28 | F. Super overs (separate) | Super-over record by franchise
SELECT t.franchise_name,
       COUNT(*)      AS super_over_matches,
       SUM(tm.won)   AS super_over_wins,
       COUNT(*) - SUM(tm.won) AS super_over_losses
FROM v_team_match tm
JOIN team t ON t.team_id = tm.team_id
WHERE tm.is_super_over = 1
GROUP BY t.team_id, t.franchise_name
ORDER BY super_over_matches DESC, super_over_wins DESC;
