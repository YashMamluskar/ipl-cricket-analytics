-- =============================================================================
-- 03_create_indexes.sql
-- Secondary indexes for frequent filters / joins.
-- InnoDB already indexes every PK, UNIQUE and FOREIGN KEY column; the indexes
-- below are COMPOSITE ones designed for the analysis queries (season, player,
-- phase and regulation-vs-super-over filters).
-- Rerun-safe: the loader drops an index before re-creating it (MySQL 8 has no
-- CREATE INDEX IF NOT EXISTS); this file is executed through python/04_load_mysql.py.
-- =============================================================================

USE ipl_cricket_analytics;

-- Season-level match filtering
CREATE INDEX ix_matches_season        ON matches (season_year, match_id);
CREATE INDEX ix_matches_result_for    ON matches (result_for, season_year);

-- Player aggregations always filter regulation balls first
CREATE INDEX ix_deliv_batter_reg      ON deliveries (batter_id, is_super_over);
CREATE INDEX ix_deliv_bowler_reg      ON deliveries (bowler_id, is_super_over);
CREATE INDEX ix_deliv_dismissed_reg   ON deliveries (player_dismissed_id, is_super_over);

-- Innings totals and phase analysis
CREATE INDEX ix_deliv_match_inning    ON deliveries (match_id, inning, is_super_over);
CREATE INDEX ix_deliv_phase           ON deliveries (phase, is_super_over);

-- Team-level bowling / batting by season (joined via match_id)
CREATE INDEX ix_deliv_bowl_team       ON deliveries (bowling_team_id, match_id);
CREATE INDEX ix_deliv_bat_team        ON deliveries (batting_team_id, match_id);
