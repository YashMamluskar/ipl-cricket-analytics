-- =============================================================================
-- 01_create_database.sql
-- IPL Cricket Analytics - create the database (safe to rerun).
-- MySQL 8.0+
-- =============================================================================

CREATE DATABASE IF NOT EXISTS ipl_cricket_analytics
    CHARACTER SET utf8mb4
    -- Accent- and case-SENSITIVE collation: player/team/venue names are identifiers,
    -- so 'Arshad Khan' and similar names must never be merged by a lenient collation.
    COLLATE utf8mb4_0900_as_cs;

USE ipl_cricket_analytics;
