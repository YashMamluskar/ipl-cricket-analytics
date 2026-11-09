# Database Relationships & ER Diagram — `ipl_cricket_analytics`

The diagram below is Mermaid; GitHub and VS Code render it automatically. Column lists are abbreviated to keys and the most important attributes. The full definitions are in [database_schema.md](database_schema.md) and `sql/02_create_tables.sql`.

```mermaid
erDiagram
    TEAM ||--o{ TEAM_NAME_ALIAS : "original spellings"
    VENUE ||--o{ VENUE_ALIAS    : "original spellings"

    VENUE  ||--o{ MATCHES : "hosted at"
    TEAM   ||--o{ MATCHES : "team1 / team2"
    TEAM   ||--o{ MATCHES : "toss_winner"
    TEAM   ||--o{ MATCHES : "batting_first / chasing"
    TEAM   |o--o{ MATCHES : "winner (NULL = no result)"
    PLAYER |o--o{ MATCHES : "player_of_match"

    MATCHES ||--|{ DELIVERIES : "1 match : 51-269 balls"
    TEAM    ||--o{ DELIVERIES : "batting_team / bowling_team"
    PLAYER  ||--o{ DELIVERIES : "batter"
    PLAYER  ||--o{ DELIVERIES : "non_striker"
    PLAYER  ||--o{ DELIVERIES : "bowler"
    PLAYER  |o--o{ DELIVERIES : "player_dismissed"
    PLAYER  |o--o{ DELIVERIES : "fielder"

    TEAM {
        smallint team_id PK
        varchar franchise_name UK
        varchar franchise_short
    }
    TEAM_NAME_ALIAS {
        varchar team_name_original PK
        smallint team_id FK
        varchar mapping_type
        varchar decision_status
    }
    VENUE {
        smallint venue_id PK
        varchar venue_name UK
        varchar city
    }
    VENUE_ALIAS {
        varchar venue_original PK
        smallint venue_id FK
        varchar mapping_type
        varchar verification_status
    }
    PLAYER {
        smallint player_id PK
        varchar player_name UK
    }
    MATCHES {
        int match_id PK "source id"
        smallint season_year
        date match_date
        smallint venue_id FK
        smallint team1_id FK
        smallint team2_id FK
        smallint toss_winner_id FK
        smallint batting_first_team_id FK
        smallint chasing_team_id FK
        smallint winner_id FK "nullable"
        enum result_for
        tinyint is_dls
        smallint inn1_runs
        smallint inn2_runs
        smallint player_of_match_id FK
    }
    DELIVERIES {
        int delivery_id PK "raw row no."
        int match_id FK
        tinyint inning
        tinyint over_raw
        tinyint ball
        tinyint is_super_over
        enum phase
        smallint batting_team_id FK
        smallint bowling_team_id FK
        smallint batter_id FK
        smallint non_striker_id FK
        smallint bowler_id FK
        smallint player_dismissed_id FK
        smallint fielder_id FK
        tinyint total_runs
        tinyint bowler_runs_conceded
        tinyint is_legal_delivery
        tinyint is_bowler_wicket
        tinyint is_player_out
    }
```

## Relationship rules

| Relationship | Cardinality | Enforced by |
|---|---|---|
| `matches` → `deliveries` | 1 : many. Every match has 51–269 deliveries; there are no orphans in either direction. | `fk_d_match`; checks Q07/Q08 |
| `team` → `matches` (6 roles) | 1 : many per role | 6 FKs. `winner_id` is NULL only for no-results (`ck_m_winner_nr`). |
| `team` → `deliveries` (batting, bowling) | 1 : many | 2 FKs; `ck_d_teams` (batting ≠ bowling) |
| `player` → `deliveries` (5 roles) | 1 : many per role | 5 FKs. A player can be batter, non-striker, bowler, dismissed player or fielder, so one `player` table serves every role. |
| `venue` → `matches` | 1 : many | `fk_m_venue` |
| `team`/`venue` → alias tables | 1 : many | Keeps all 19 original team names and 58 original venue strings |

**Batting order** comes from `batting_first_team_id` / `chasing_team_id`, which Phase 2 derived from innings-1 deliveries. `team1`/`team2` are kept only for lineage, because `team1` bats first in just 72.6% of matches.

**Natural key.** Besides the surrogate primary key `delivery_id`, `deliveries` has a UNIQUE `(match_id, inning, over_raw, ball)` constraint, so the same ball can never be loaded twice.
