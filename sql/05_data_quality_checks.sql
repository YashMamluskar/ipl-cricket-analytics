-- =============================================================================
-- 05_data_quality_checks.sql
-- Post-load validation. Every statement returns ONE row:
--   check_id | area | check_name | expected | actual | status
-- Expected values come from the Phase 2 validated CSVs (see
-- reports/validation/phase2_before_after_validation_report.md).
-- Executed by python/04b_validate_mysql.py; can also be run in MySQL Workbench.
-- =============================================================================

USE ipl_cricket_analytics;

-- ---------------------------------------------------------------- row counts
SELECT 'Q01' AS check_id, 'Counts' AS area, 'Match rows loaded' AS check_name,
       1095 AS expected, COUNT(*) AS actual, IF(COUNT(*) = 1095, 'PASS', 'FAIL') AS status
FROM matches;

SELECT 'Q02', 'Counts', 'Delivery rows loaded', 260920, COUNT(*), IF(COUNT(*) = 260920, 'PASS', 'FAIL')
FROM deliveries;

SELECT 'Q03', 'Counts', 'Franchises / original team names', '15 / 19',
       CONCAT((SELECT COUNT(*) FROM team), ' / ', (SELECT COUNT(*) FROM team_name_alias)),
       IF((SELECT COUNT(*) FROM team) = 15 AND (SELECT COUNT(*) FROM team_name_alias) = 19, 'PASS', 'FAIL');

SELECT 'Q04', 'Counts', 'Venues / original venue strings', '36 / 58',
       CONCAT((SELECT COUNT(*) FROM venue), ' / ', (SELECT COUNT(*) FROM venue_alias)),
       IF((SELECT COUNT(*) FROM venue) = 36 AND (SELECT COUNT(*) FROM venue_alias) = 58, 'PASS', 'FAIL');

SELECT 'Q05', 'Counts', 'Distinct players', 741, COUNT(*), IF(COUNT(*) = 741, 'PASS', 'FAIL') FROM player;

-- ---------------------------------------------------------------- keys & relationships
SELECT 'Q06', 'Keys', 'Duplicate natural delivery keys (match, inning, over, ball)', 0, COUNT(*),
       IF(COUNT(*) = 0, 'PASS', 'FAIL')
FROM (SELECT match_id, inning, over_raw, ball FROM deliveries
      GROUP BY match_id, inning, over_raw, ball HAVING COUNT(*) > 1) x;

SELECT 'Q07', 'Keys', 'Orphan deliveries (match_id not in matches)', 0, COUNT(*), IF(COUNT(*) = 0, 'PASS', 'FAIL')
FROM deliveries d LEFT JOIN matches m ON m.match_id = d.match_id WHERE m.match_id IS NULL;

SELECT 'Q08', 'Keys', 'Matches without deliveries', 0, COUNT(*), IF(COUNT(*) = 0, 'PASS', 'FAIL')
FROM matches m WHERE NOT EXISTS (SELECT 1 FROM deliveries d WHERE d.match_id = m.match_id);

SELECT 'Q09', 'Keys', 'Foreign keys enforced on deliveries (8) and matches (8)', 16, COUNT(*),
       IF(COUNT(*) = 16, 'PASS', 'FAIL')
FROM information_schema.referential_constraints
WHERE constraint_schema = DATABASE() AND table_name IN ('deliveries', 'matches');

SELECT 'Q10', 'Keys', 'Delivery teams consistent with match teams', 0, COUNT(*), IF(COUNT(*) = 0, 'PASS', 'FAIL')
FROM deliveries d JOIN matches m ON m.match_id = d.match_id
WHERE NOT ((d.batting_team_id = m.team1_id AND d.bowling_team_id = m.team2_id)
        OR (d.batting_team_id = m.team2_id AND d.bowling_team_id = m.team1_id));

-- ---------------------------------------------------------------- runs & extras
SELECT 'Q11', 'Runs', 'Total runs (all deliveries)', 347756, SUM(total_runs),
       IF(SUM(total_runs) = 347756, 'PASS', 'FAIL') FROM deliveries;

SELECT 'Q12', 'Runs', 'Total runs (regulation)', 347470, SUM(total_runs),
       IF(SUM(total_runs) = 347470, 'PASS', 'FAIL') FROM deliveries WHERE is_super_over = 0;

SELECT 'Q13', 'Runs', 'Extras total / batter runs total', '17692 / 330064',
       CONCAT(SUM(extra_runs), ' / ', SUM(batsman_runs)),
       IF(SUM(extra_runs) = 17692 AND SUM(batsman_runs) = 330064, 'PASS', 'FAIL') FROM deliveries;

SELECT 'Q14', 'Runs', 'Extras by type (wd/nb/b/lb/pen)', '10064/1104/1270/5242/12',
       CONCAT(SUM(wide_runs), '/', SUM(noball_runs), '/', SUM(bye_runs), '/', SUM(legbye_runs), '/', SUM(penalty_runs)),
       IF(SUM(wide_runs) = 10064 AND SUM(noball_runs) = 1104 AND SUM(bye_runs) = 1270
          AND SUM(legbye_runs) = 5242 AND SUM(penalty_runs) = 12, 'PASS', 'FAIL') FROM deliveries;

SELECT 'Q15', 'Runs', 'Rows where bowler runs + byes + leg-byes + penalty <> total runs', 0, COUNT(*),
       IF(COUNT(*) = 0, 'PASS', 'FAIL')
FROM deliveries WHERE bowler_runs_conceded + bye_runs + legbye_runs + penalty_runs <> total_runs;

SELECT 'Q16', 'Runs', 'Innings totals in matches = sum of regulation deliveries (mismatching matches)', 0, COUNT(*),
       IF(COUNT(*) = 0, 'PASS', 'FAIL')
FROM matches m
JOIN (SELECT match_id,
             SUM(CASE WHEN inning = 1 THEN total_runs ELSE 0 END) AS r1,
             SUM(CASE WHEN inning = 2 THEN total_runs END)       AS r2
      FROM deliveries WHERE is_super_over = 0 GROUP BY match_id) d ON d.match_id = m.match_id
WHERE m.inn1_runs <> d.r1 OR NOT (m.inn2_runs <=> d.r2);

-- ---------------------------------------------------------------- legal deliveries & overs
SELECT 'Q17', 'Legal balls', 'Legal deliveries (all / regulation)', '251471 / 251319',
       CONCAT(SUM(is_legal_delivery), ' / ', SUM(CASE WHEN is_super_over = 0 THEN is_legal_delivery ELSE 0 END)),
       IF(SUM(is_legal_delivery) = 251471
          AND SUM(CASE WHEN is_super_over = 0 THEN is_legal_delivery ELSE 0 END) = 251319, 'PASS', 'FAIL')
FROM deliveries;

SELECT 'Q18', 'Legal balls', 'is_legal_delivery consistent with wides/no-balls', 0, COUNT(*),
       IF(COUNT(*) = 0, 'PASS', 'FAIL')
FROM deliveries WHERE is_legal_delivery <> (1 - is_wide - is_noball);

SELECT 'Q19', 'Overs', 'Seven-legal-ball overs retained and flagged', 29, COUNT(*), IF(COUNT(*) = 29, 'PASS', 'FAIL')
FROM (SELECT match_id, inning, over_raw FROM deliveries
      GROUP BY match_id, inning, over_raw HAVING SUM(is_legal_delivery) > 6 AND MAX(is_seven_ball_over) = 1) x;

-- ---------------------------------------------------------------- super overs
SELECT 'Q20', 'Super overs', 'Super-over deliveries retained', 161, SUM(is_super_over),
       IF(SUM(is_super_over) = 161 AND SUM(is_super_over) = SUM(inning >= 3), 'PASS', 'FAIL') FROM deliveries;

SELECT 'Q21', 'Super overs', 'Super-over matches: matches flag = deliveries', 14,
       (SELECT COUNT(DISTINCT match_id) FROM deliveries WHERE is_super_over = 1),
       IF((SELECT COUNT(DISTINCT match_id) FROM deliveries WHERE is_super_over = 1) = 14
          AND (SELECT SUM(is_super_over) FROM matches) = 14, 'PASS', 'FAIL');

SELECT 'Q22', 'Super overs', 'Regulation view contains no super-over balls', 0, COUNT(*),
       IF(COUNT(*) = 0, 'PASS', 'FAIL') FROM v_reg_deliveries WHERE is_super_over = 1 OR phase = 'Super Over';

-- ---------------------------------------------------------------- wickets
SELECT 'Q23', 'Wickets', 'Bowler-credited wickets (all / regulation)', '11815 / 11795',
       CONCAT(SUM(is_bowler_wicket), ' / ', SUM(CASE WHEN is_super_over = 0 THEN is_bowler_wicket ELSE 0 END)),
       IF(SUM(is_bowler_wicket) = 11815
          AND SUM(CASE WHEN is_super_over = 0 THEN is_bowler_wicket ELSE 0 END) = 11795, 'PASS', 'FAIL')
FROM deliveries;

SELECT 'Q24', 'Wickets', 'Bowler wickets only from bowler-credited dismissal kinds', 0, COUNT(*),
       IF(COUNT(*) = 0, 'PASS', 'FAIL')
FROM deliveries WHERE is_bowler_wicket = 1
  AND dismissal_kind NOT IN ('bowled', 'caught', 'caught and bowled', 'lbw', 'stumped', 'hit wicket');

SELECT 'Q25', 'Wickets', 'Retired hurt: kept (is_wicket=1) but not out and not bowler wicket', '15 / 0',
       CONCAT(COUNT(*), ' / ', SUM(is_player_out + is_bowler_wicket)),
       IF(COUNT(*) = 15 AND SUM(is_player_out + is_bowler_wicket) = 0 AND SUM(is_wicket) = 15, 'PASS', 'FAIL')
FROM deliveries WHERE dismissal_kind = 'retired hurt';

SELECT 'Q26', 'Wickets', 'Raw is_wicket / player outs', '12950 / 12935',
       CONCAT(SUM(is_wicket), ' / ', SUM(is_player_out)),
       IF(SUM(is_wicket) = 12950 AND SUM(is_player_out) = 12935, 'PASS', 'FAIL') FROM deliveries;

-- ---------------------------------------------------------------- results & batting order
SELECT 'Q27', 'Results', 'result_for distribution (bat first / chasing / SO / NR)', '492 / 584 / 14 / 5',
       CONCAT(SUM(result_for = 'batting first'), ' / ', SUM(result_for = 'chasing'), ' / ',
              SUM(result_for = 'super over'), ' / ', SUM(result_for = 'no result')),
       IF(SUM(result_for = 'batting first') = 492 AND SUM(result_for = 'chasing') = 584
          AND SUM(result_for = 'super over') = 14 AND SUM(result_for = 'no result') = 5, 'PASS', 'FAIL')
FROM matches;

SELECT 'Q28', 'Results', 'batting_first_team_id = innings-1 batting team in deliveries (mismatches)', 0, COUNT(*),
       IF(COUNT(*) = 0, 'PASS', 'FAIL')
FROM matches m
JOIN (SELECT match_id, MIN(batting_team_id) AS t, COUNT(DISTINCT batting_team_id) AS n
      FROM deliveries WHERE inning = 1 GROUP BY match_id) d ON d.match_id = m.match_id
WHERE d.n <> 1 OR d.t <> m.batting_first_team_id;

SELECT 'Q29', 'Results', 'D/L matches preserved / D/L chases won by runs', '21 / 6',
       CONCAT(SUM(is_dls), ' / ', SUM(is_dls = 1 AND win_type = 'runs' AND result_for = 'chasing')),
       IF(SUM(is_dls) = 21 AND SUM(is_dls = 1 AND win_type = 'runs' AND result_for = 'chasing') = 6, 'PASS', 'FAIL')
FROM matches;

SELECT 'Q30', 'Results', 'Non-D/L targets = inn1_runs + 1 (mismatches)', 0, COUNT(*), IF(COUNT(*) = 0, 'PASS', 'FAIL')
FROM matches WHERE is_dls = 0 AND target_runs IS NOT NULL AND target_runs <> inn1_runs + 1;

-- ---------------------------------------------------------------- mappings & audit columns
SELECT 'Q31', 'Mappings', 'Every original team name maps to its franchise (mismatches)', 0, COUNT(*),
       IF(COUNT(*) = 0, 'PASS', 'FAIL')
FROM matches m JOIN team_name_alias a ON a.team_name_original = m.team1_original
WHERE a.team_id <> m.team1_id;

SELECT 'Q32', 'Mappings', 'Every original venue maps to its standardized venue (mismatches)', 0, COUNT(*),
       IF(COUNT(*) = 0, 'PASS', 'FAIL')
FROM matches m JOIN venue_alias a ON a.venue_original = m.venue_original
WHERE a.venue_id <> m.venue_id;

SELECT 'Q33', 'Mappings', 'Imputed cities (Dubai + Sharjah)', 51, SUM(is_city_imputed),
       IF(SUM(is_city_imputed) = 51 AND SUM(city_original IS NULL) = 51, 'PASS', 'FAIL') FROM matches;

SELECT 'Q34', 'Mappings', 'Seasons 2008-2024 (17 distinct)', 17, COUNT(DISTINCT season_year),
       IF(COUNT(DISTINCT season_year) = 17 AND MIN(season_year) = 2008 AND MAX(season_year) = 2024, 'PASS', 'FAIL')
FROM matches;
