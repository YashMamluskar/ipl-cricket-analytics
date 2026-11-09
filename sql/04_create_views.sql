-- =============================================================================
-- 04_create_views.sql
-- Reusable analytical views. These encode the approved cricket rules ONCE so
-- every business query uses identical definitions (rerun-safe: CREATE OR REPLACE).
--
-- Rules implemented here
--   * Regulation statistics exclude super overs        (is_super_over = 0)
--   * Bowler wickets = is_bowler_wicket                  (never raw is_wicket)
--   * Batter dismissals = is_player_out                  (retired hurt = not out)
--   * Batting order / outcome = batting_first_team_id, chasing_team_id, result_for
--   * "Full match" = not a no-result AND target_overs = 20 (used for score averages)
-- Ratios are left unrounded; round only in presentation queries.
-- =============================================================================

USE ipl_cricket_analytics;

-- -----------------------------------------------------------------------------
-- Regulation deliveries with match context (season, venue)
-- -----------------------------------------------------------------------------
CREATE OR REPLACE VIEW v_reg_deliveries AS
SELECT d.*,
       m.season_year,
       m.venue_id
FROM deliveries AS d
JOIN matches    AS m ON m.match_id = d.match_id
WHERE d.is_super_over = 0;

-- -----------------------------------------------------------------------------
-- Full 20-over matches (base for all score averages)
-- -----------------------------------------------------------------------------
CREATE OR REPLACE VIEW v_full_matches AS
SELECT *
FROM matches
WHERE is_no_result = 0
  AND target_overs = 20;

-- -----------------------------------------------------------------------------
-- Match summary with names resolved (readable / BI-friendly)
-- -----------------------------------------------------------------------------
CREATE OR REPLACE VIEW v_match_summary AS
SELECT m.match_id, m.season_year, m.match_date, m.match_type, m.is_playoff,
       v.venue_name, m.city,
       bf.franchise_name  AS batting_first_team,
       ch.franchise_name  AS chasing_team,
       tw.franchise_name  AS toss_winner,
       m.toss_decision,
       w.franchise_name   AS winner,
       m.result, m.result_margin, m.win_type, m.result_for,
       m.is_super_over, m.is_no_result, m.is_dls,
       m.target_runs, m.target_overs,
       m.inn1_runs, m.inn1_wickets, m.inn2_runs, m.inn2_wickets,
       p.player_name      AS player_of_match
FROM matches m
JOIN venue  v  ON v.venue_id  = m.venue_id
JOIN team   bf ON bf.team_id  = m.batting_first_team_id
JOIN team   ch ON ch.team_id  = m.chasing_team_id
JOIN team   tw ON tw.team_id  = m.toss_winner_id
LEFT JOIN team   w ON w.team_id   = m.winner_id
LEFT JOIN player p ON p.player_id = m.player_of_match_id;

-- -----------------------------------------------------------------------------
-- Team-match long table: exactly 2 rows per match (one per team).
-- Batting order comes from delivery-derived columns, never from team1/team2.
-- -----------------------------------------------------------------------------
CREATE OR REPLACE VIEW v_team_match AS
SELECT m.match_id, m.season_year, m.venue_id, m.match_type, m.is_dls, m.is_super_over,
       m.is_no_result, m.result_for, m.winner_id, m.toss_winner_id,
       m.batting_first_team_id AS team_id,
       m.chasing_team_id       AS opponent_id,
       1                       AS batted_first,
       1 - m.is_no_result      AS decided,
       CASE WHEN m.winner_id = m.batting_first_team_id THEN 1 ELSE 0 END AS won
FROM matches m
UNION ALL
SELECT m.match_id, m.season_year, m.venue_id, m.match_type, m.is_dls, m.is_super_over,
       m.is_no_result, m.result_for, m.winner_id, m.toss_winner_id,
       m.chasing_team_id, m.batting_first_team_id, 0, 1 - m.is_no_result,
       CASE WHEN m.winner_id = m.chasing_team_id THEN 1 ELSE 0 END
FROM matches m;

-- -----------------------------------------------------------------------------
-- Batting innings: one row per (match, innings, player) who batted, i.e. appeared
-- as striker, non-striker or was dismissed (same definition as Python EDA).
-- -----------------------------------------------------------------------------
CREATE OR REPLACE VIEW v_batting_innings AS
WITH appearances AS (
    SELECT match_id, inning, batter_id AS player_id FROM deliveries WHERE is_super_over = 0
    UNION
    SELECT match_id, inning, non_striker_id         FROM deliveries WHERE is_super_over = 0
    UNION
    SELECT match_id, inning, player_dismissed_id    FROM deliveries
    WHERE is_super_over = 0 AND player_dismissed_id IS NOT NULL
),
batting AS (
    SELECT match_id, inning, batter_id AS player_id,
           SUM(batsman_runs)  AS runs,
           SUM(is_ball_faced) AS balls,
           SUM(is_four)       AS fours,
           SUM(is_six)        AS sixes
    FROM deliveries
    WHERE is_super_over = 0
    GROUP BY match_id, inning, batter_id
),
dismissals AS (
    SELECT match_id, inning, player_dismissed_id AS player_id, SUM(is_player_out) AS outs
    FROM deliveries
    WHERE is_super_over = 0 AND is_player_out = 1
    GROUP BY match_id, inning, player_dismissed_id
)
SELECT a.match_id, a.inning, a.player_id,
       m.season_year,
       COALESCE(b.runs, 0)  AS runs,
       COALESCE(b.balls, 0) AS balls,
       COALESCE(b.fours, 0) AS fours,
       COALESCE(b.sixes, 0) AS sixes,
       COALESCE(o.outs, 0)  AS is_out
FROM appearances a
JOIN matches m          ON m.match_id = a.match_id
LEFT JOIN batting b     ON b.match_id = a.match_id AND b.inning = a.inning AND b.player_id = a.player_id
LEFT JOIN dismissals o  ON o.match_id = a.match_id AND o.inning = a.inning AND o.player_id = a.player_id;

-- -----------------------------------------------------------------------------
-- Batter career totals (regulation only)
-- -----------------------------------------------------------------------------
CREATE OR REPLACE VIEW v_batter_career AS
SELECT p.player_id, p.player_name,
       COUNT(*)                                   AS innings,
       SUM(bi.runs)                               AS runs,
       SUM(bi.balls)                              AS balls,
       SUM(bi.is_out)                             AS outs,
       COUNT(*) - SUM(bi.is_out)                  AS not_outs,
       SUM(bi.runs) / NULLIF(SUM(bi.is_out), 0)   AS batting_average,
       SUM(bi.runs) * 100 / NULLIF(SUM(bi.balls), 0) AS strike_rate,
       SUM(bi.fours)                              AS fours,
       SUM(bi.sixes)                              AS sixes,
       MAX(bi.runs)                               AS highest,
       SUM(bi.runs BETWEEN 50 AND 99)             AS fifties,
       SUM(bi.runs >= 100)                        AS hundreds,
       SUM(bi.runs >= 30) * 100 / COUNT(*)        AS pct_30_plus,
       SUM(bi.runs < 10)  * 100 / COUNT(*)        AS pct_under_10
FROM v_batting_innings bi
JOIN player p ON p.player_id = bi.player_id
GROUP BY p.player_id, p.player_name;

-- -----------------------------------------------------------------------------
-- Bowler career totals (regulation only)
-- -----------------------------------------------------------------------------
CREATE OR REPLACE VIEW v_bowler_career AS
SELECT p.player_id, p.player_name,
       COUNT(DISTINCT d.match_id, d.inning)                  AS innings,
       SUM(d.is_legal_delivery)                              AS legal_balls,
       SUM(d.bowler_runs_conceded)                           AS runs_conceded,
       SUM(d.is_bowler_wicket)                               AS wickets,
       SUM(d.is_dot_ball)                                    AS dots,
       SUM(d.bowler_runs_conceded) * 6 / SUM(d.is_legal_delivery)        AS economy,
       SUM(d.bowler_runs_conceded) / NULLIF(SUM(d.is_bowler_wicket), 0)  AS bowling_average,
       SUM(d.is_legal_delivery)    / NULLIF(SUM(d.is_bowler_wicket), 0)  AS bowling_strike_rate,
       SUM(d.is_dot_ball) * 100 / SUM(d.is_legal_delivery)               AS dot_pct
FROM deliveries d
JOIN player p ON p.player_id = d.bowler_id
WHERE d.is_super_over = 0
GROUP BY p.player_id, p.player_name;

-- -----------------------------------------------------------------------------
-- Season summary (regulation deliveries + match counts + full-match averages)
-- -----------------------------------------------------------------------------
CREATE OR REPLACE VIEW v_season_summary AS
WITH m AS (
    SELECT season_year, COUNT(*) AS matches, SUM(is_no_result) AS no_results,
           SUM(is_dls) AS dls_matches, SUM(is_super_over) AS ties
    FROM matches GROUP BY season_year
),
d AS (
    SELECT season_year,
           SUM(total_runs) AS runs, SUM(is_legal_delivery) AS legal_balls,
           SUM(is_player_out) AS player_outs, SUM(is_bowler_wicket) AS bowler_wickets,
           SUM(is_four) AS fours, SUM(is_six) AS sixes, SUM(is_dot_ball) AS dots
    FROM v_reg_deliveries GROUP BY season_year
),
f AS (
    SELECT season_year, COUNT(*) AS full_matches,
           AVG(inn1_runs) AS avg_inn1, AVG(inn2_runs) AS avg_inn2,
           AVG(inn1_runs + inn2_runs) AS runs_per_full_match
    FROM v_full_matches GROUP BY season_year
)
SELECT m.season_year, m.matches, m.no_results, m.dls_matches, m.ties,
       d.runs, d.legal_balls, d.player_outs, d.bowler_wickets, d.fours, d.sixes, d.dots,
       d.runs / m.matches             AS runs_per_match,
       d.runs * 6 / d.legal_balls     AS run_rate,
       d.bowler_wickets / m.matches   AS bowler_wkts_per_match,
       d.dots * 100 / d.legal_balls   AS dot_pct,
       f.full_matches, f.avg_inn1, f.avg_inn2, f.runs_per_full_match
FROM m
JOIN d ON d.season_year = m.season_year
JOIN f ON f.season_year = m.season_year;
