-- =============================================================================
-- 02_create_tables.sql
-- IPL Cricket Analytics - table definitions (safe to rerun: CREATE ... IF NOT EXISTS).
--
-- Design: star-like hybrid.
--   * Dimensions: team, team_name_alias, venue, venue_alias, player
--   * Facts:      matches (1 row per match), deliveries (1 row per ball bowled)
--   * Team, venue and player NAMES are stored once (dimension tables); facts
--     store integer surrogate keys. Original source spellings are kept in the
--     alias tables and in *_original audit columns on the fact tables.
--   * Approved Phase 2 derived columns (flags, innings totals, result_for ...)
--     are stored as loaded, so SQL uses exactly the same validated definitions
--     as Python.
-- Source: data/processed/matches_clean.csv, deliveries_clean.csv,
--         data/reference/franchise_mapping.csv, venue_mapping.csv
-- =============================================================================

USE ipl_cricket_analytics;

-- -----------------------------------------------------------------------------
-- Dimension: team (one row per standardized franchise)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS team (
    team_id          SMALLINT UNSIGNED NOT NULL,
    franchise_name   VARCHAR(40)  NOT NULL,
    franchise_short  VARCHAR(10)  NOT NULL,
    CONSTRAINT pk_team PRIMARY KEY (team_id),
    CONSTRAINT uq_team_name UNIQUE (franchise_name)
) ENGINE = InnoDB COMMENT = 'Standardized franchises (Phase 2 approved mapping)';

-- Original team-name spellings -> franchise (audit / lineage)
CREATE TABLE IF NOT EXISTS team_name_alias (
    team_name_original VARCHAR(40) NOT NULL,
    team_id            SMALLINT UNSIGNED NOT NULL,
    mapping_type       VARCHAR(30) NOT NULL,
    decision_status    VARCHAR(40) NOT NULL,
    first_year         SMALLINT    NOT NULL,
    last_year          SMALLINT    NOT NULL,
    CONSTRAINT pk_team_name_alias PRIMARY KEY (team_name_original),
    CONSTRAINT fk_alias_team FOREIGN KEY (team_id) REFERENCES team (team_id)
) ENGINE = InnoDB COMMENT = 'franchise_mapping.csv';

-- -----------------------------------------------------------------------------
-- Dimension: venue (one row per standardized ground)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS venue (
    venue_id     SMALLINT UNSIGNED NOT NULL,
    venue_name   VARCHAR(80) NOT NULL,
    city         VARCHAR(40) NOT NULL,
    CONSTRAINT pk_venue PRIMARY KEY (venue_id),
    CONSTRAINT uq_venue_name UNIQUE (venue_name)
) ENGINE = InnoDB COMMENT = 'Standardized grounds (Phase 2 approved mapping)';

CREATE TABLE IF NOT EXISTS venue_alias (
    venue_original       VARCHAR(80)  NOT NULL,
    venue_id             SMALLINT UNSIGNED NOT NULL,
    mapping_type         VARCHAR(40)  NOT NULL,
    reason               VARCHAR(255) NOT NULL,
    verification_status  VARCHAR(80)  NOT NULL,
    owner_approval       VARCHAR(40)  NOT NULL,
    city_values_raw      VARCHAR(80)  NOT NULL,
    matches              SMALLINT     NOT NULL,
    CONSTRAINT pk_venue_alias PRIMARY KEY (venue_original),
    CONSTRAINT fk_venue_alias_venue FOREIGN KEY (venue_id) REFERENCES venue (venue_id)
) ENGINE = InnoDB COMMENT = 'venue_mapping.csv';

-- -----------------------------------------------------------------------------
-- Dimension: player (every name appearing as batter, non-striker, bowler,
-- dismissed player, fielder or player of the match)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS player (
    player_id    SMALLINT UNSIGNED NOT NULL,
    player_name  VARCHAR(60) NOT NULL,
    CONSTRAINT pk_player PRIMARY KEY (player_id),
    CONSTRAINT uq_player_name UNIQUE (player_name)
) ENGINE = InnoDB COMMENT = 'Cricsheet-style names; no external player ID exists in source';

-- -----------------------------------------------------------------------------
-- Fact: matches (1 row per match; match_id = original source id)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS matches (
    match_id                  INT UNSIGNED      NOT NULL COMMENT 'Original source id (ESPNcricinfo/Cricsheet)',
    season_year               SMALLINT UNSIGNED NOT NULL COMMENT 'Derived from match_date',
    season_label_original     VARCHAR(10)       NOT NULL,
    match_date                DATE              NOT NULL,
    match_type                VARCHAR(25)       NOT NULL,
    is_playoff                TINYINT(1)        NOT NULL,
    venue_id                  SMALLINT UNSIGNED NOT NULL,
    venue_original            VARCHAR(80)       NOT NULL,
    city                      VARCHAR(40)       NOT NULL,
    city_original             VARCHAR(40)       NULL,
    is_city_imputed           TINYINT(1)        NOT NULL,
    team1_id                  SMALLINT UNSIGNED NOT NULL COMMENT 'NOT batting order',
    team1_original            VARCHAR(40)       NOT NULL,
    team2_id                  SMALLINT UNSIGNED NOT NULL,
    team2_original            VARCHAR(40)       NOT NULL,
    toss_winner_id            SMALLINT UNSIGNED NOT NULL,
    toss_winner_original      VARCHAR(40)       NOT NULL,
    toss_decision             ENUM('bat','field') NOT NULL,
    toss_winner_batted_first  TINYINT(1)        NOT NULL,
    batting_first_team_id     SMALLINT UNSIGNED NOT NULL COMMENT 'From innings-1 deliveries',
    chasing_team_id           SMALLINT UNSIGNED NOT NULL,
    winner_id                 SMALLINT UNSIGNED NULL COMMENT 'NULL only for no result',
    winner_original           VARCHAR(40)       NULL,
    result                    ENUM('runs','wickets','tie','no result') NOT NULL,
    result_margin             SMALLINT UNSIGNED NULL,
    win_type                  ENUM('runs','wickets','super over','no result') NOT NULL,
    result_for                ENUM('batting first','chasing','super over','no result') NOT NULL
                              COMMENT 'Approved batting-first/chasing outcome (handles D/L)',
    toss_winner_won           TINYINT(1)        NULL,
    is_super_over             TINYINT(1)        NOT NULL,
    is_no_result              TINYINT(1)        NOT NULL,
    is_dls                    TINYINT(1)        NOT NULL,
    method                    VARCHAR(10)       NULL,
    target_runs               SMALLINT UNSIGNED NULL,
    target_overs              DECIMAL(4,1)      NULL COMMENT 'Cricket notation: 9.2 = 9 overs 2 balls',
    target_balls              SMALLINT UNSIGNED NULL,
    inn1_runs                 SMALLINT UNSIGNED NOT NULL,
    inn1_wickets              TINYINT UNSIGNED  NOT NULL,
    inn1_legal_balls          SMALLINT UNSIGNED NOT NULL,
    inn2_runs                 SMALLINT UNSIGNED NULL,
    inn2_wickets              TINYINT UNSIGNED  NULL,
    inn2_legal_balls          SMALLINT UNSIGNED NULL,
    player_of_match_id        SMALLINT UNSIGNED NULL,
    umpire1                   VARCHAR(40)       NOT NULL,
    umpire2                   VARCHAR(40)       NOT NULL,
    CONSTRAINT pk_matches PRIMARY KEY (match_id),
    CONSTRAINT fk_m_venue      FOREIGN KEY (venue_id)              REFERENCES venue (venue_id),
    CONSTRAINT fk_m_team1      FOREIGN KEY (team1_id)              REFERENCES team (team_id),
    CONSTRAINT fk_m_team2      FOREIGN KEY (team2_id)              REFERENCES team (team_id),
    CONSTRAINT fk_m_toss       FOREIGN KEY (toss_winner_id)        REFERENCES team (team_id),
    CONSTRAINT fk_m_bat_first  FOREIGN KEY (batting_first_team_id) REFERENCES team (team_id),
    CONSTRAINT fk_m_chasing    FOREIGN KEY (chasing_team_id)       REFERENCES team (team_id),
    CONSTRAINT fk_m_winner     FOREIGN KEY (winner_id)             REFERENCES team (team_id),
    CONSTRAINT fk_m_pom        FOREIGN KEY (player_of_match_id)    REFERENCES player (player_id),
    CONSTRAINT ck_m_teams_differ  CHECK (team1_id <> team2_id),
    CONSTRAINT ck_m_order_differ  CHECK (batting_first_team_id <> chasing_team_id),
    CONSTRAINT ck_m_winner_nr     CHECK ((winner_id IS NULL) = (is_no_result = 1))
) ENGINE = InnoDB COMMENT = 'matches_clean.csv';

-- -----------------------------------------------------------------------------
-- Fact: deliveries (1 row per ball bowled, incl. wides/no-balls and super overs)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS deliveries (
    delivery_id            INT UNSIGNED      NOT NULL COMMENT '= 1-based row number of raw deliveries.csv',
    match_id               INT UNSIGNED      NOT NULL,
    inning                 TINYINT UNSIGNED  NOT NULL COMMENT '1-2 regulation; 3-6 super overs',
    is_super_over          TINYINT(1)        NOT NULL,
    super_over_number      TINYINT UNSIGNED  NOT NULL,
    batting_team_id        SMALLINT UNSIGNED NOT NULL,
    bowling_team_id        SMALLINT UNSIGNED NOT NULL,
    batting_team_original  VARCHAR(40)       NOT NULL,
    bowling_team_original  VARCHAR(40)       NOT NULL,
    over_raw               TINYINT UNSIGNED  NOT NULL COMMENT 'Source over, 0-based (OVER is reserved in MySQL)',
    over_number            TINYINT UNSIGNED  NOT NULL COMMENT '1-based',
    ball                   TINYINT UNSIGNED  NOT NULL COMMENT 'Delivery sequence in over incl. extras',
    is_wide                TINYINT(1)        NOT NULL,
    is_noball              TINYINT(1)        NOT NULL,
    is_bye                 TINYINT(1)        NOT NULL,
    is_legbye              TINYINT(1)        NOT NULL,
    is_penalty             TINYINT(1)        NOT NULL,
    is_legal_delivery      TINYINT(1)        NOT NULL,
    legal_ball_in_over     TINYINT UNSIGNED  NOT NULL,
    over_legal_balls       TINYINT UNSIGNED  NOT NULL,
    is_seven_ball_over     TINYINT(1)        NOT NULL,
    phase                  ENUM('Powerplay','Middle','Death','Super Over') NOT NULL,
    batter_id              SMALLINT UNSIGNED NOT NULL,
    non_striker_id         SMALLINT UNSIGNED NOT NULL,
    bowler_id              SMALLINT UNSIGNED NOT NULL,
    batsman_runs           TINYINT UNSIGNED  NOT NULL,
    extra_runs             TINYINT UNSIGNED  NOT NULL,
    total_runs             TINYINT UNSIGNED  NOT NULL,
    extras_type            ENUM('wides','noballs','byes','legbyes','penalty') NULL,
    wide_runs              TINYINT UNSIGNED  NOT NULL,
    noball_runs            TINYINT UNSIGNED  NOT NULL,
    bye_runs               TINYINT UNSIGNED  NOT NULL,
    legbye_runs            TINYINT UNSIGNED  NOT NULL,
    penalty_runs           TINYINT UNSIGNED  NOT NULL,
    bowler_runs_conceded   TINYINT UNSIGNED  NOT NULL COMMENT 'batter runs + wides + no-balls',
    is_ball_faced          TINYINT(1)        NOT NULL COMMENT 'all except wides',
    is_dot_ball            TINYINT(1)        NOT NULL,
    is_four                TINYINT(1)        NOT NULL COMMENT 'batsman_runs = 4 (proxy)',
    is_six                 TINYINT(1)        NOT NULL COMMENT 'batsman_runs = 6 (proxy)',
    is_wicket              TINYINT(1)        NOT NULL COMMENT 'RAW flag - do not use as bowler wicket',
    player_dismissed_id    SMALLINT UNSIGNED NULL,
    dismissal_kind         VARCHAR(25)       NULL,
    fielder_id             SMALLINT UNSIGNED NULL,
    is_retired_hurt        TINYINT(1)        NOT NULL,
    is_player_out          TINYINT(1)        NOT NULL COMMENT 'is_wicket excl. retired hurt',
    is_bowler_wicket       TINYINT(1)        NOT NULL,
    is_run_out             TINYINT(1)        NOT NULL,
    CONSTRAINT pk_deliveries PRIMARY KEY (delivery_id),
    CONSTRAINT uq_delivery_natural UNIQUE (match_id, inning, over_raw, ball),
    CONSTRAINT fk_d_match       FOREIGN KEY (match_id)            REFERENCES matches (match_id),
    CONSTRAINT fk_d_bat_team    FOREIGN KEY (batting_team_id)     REFERENCES team (team_id),
    CONSTRAINT fk_d_bowl_team   FOREIGN KEY (bowling_team_id)     REFERENCES team (team_id),
    CONSTRAINT fk_d_batter      FOREIGN KEY (batter_id)           REFERENCES player (player_id),
    CONSTRAINT fk_d_non_striker FOREIGN KEY (non_striker_id)      REFERENCES player (player_id),
    CONSTRAINT fk_d_bowler      FOREIGN KEY (bowler_id)           REFERENCES player (player_id),
    CONSTRAINT fk_d_dismissed   FOREIGN KEY (player_dismissed_id) REFERENCES player (player_id),
    CONSTRAINT fk_d_fielder     FOREIGN KEY (fielder_id)          REFERENCES player (player_id),
    CONSTRAINT ck_d_runs        CHECK (total_runs = batsman_runs + extra_runs),
    CONSTRAINT ck_d_teams       CHECK (batting_team_id <> bowling_team_id),
    CONSTRAINT ck_d_over        CHECK (over_number = over_raw + 1 AND over_number BETWEEN 1 AND 20)
) ENGINE = InnoDB COMMENT = 'deliveries_clean.csv';
