# Power BI Data Model - IPL Cricket Analytics

_Generated from `python/06c_build_pbip.py`. Source: validated CSV extracts in `data/final/powerbi/` (`python/06b_export_powerbi_model.py`, 13/13 export checks incl. MySQL reconciliation)._

## Design: star schema

- **Four fact tables at different grains** (ball, batting innings, team-match, match). They never relate to each other, so there are no fact-to-fact joins or ambiguous filter paths.
- **Shared conformed dimensions** (Season, Venue, Team, Player, Phase) filter every fact they apply to, so one slicer behaves consistently across all visuals.
- **Role-playing dimensions without many-to-many:** `DimTeam` and `DimPlayer` each have one ACTIVE relationship to the batting role and one INACTIVE relationship to the bowling role; bowling measures switch with `USERELATIONSHIP`.
- **All relationships are one-to-many, single direction** (dimension filters fact). No bi-directional filters.
- **Disconnected `Player A` / `Player B`** tables drive the comparison via `TREATAS`, so they never filter other visuals.
- **Why CSV extracts instead of a live MySQL connection:** no MySQL ODBC/Connector-NET is installed for Power BI and a live connection would require storing credentials in the report. The extracts are generated from the same validated pipeline and reconciled with MySQL (check X13).

Diagram generated from the 16 model relationships (solid = active, dotted = inactive bowling role):

```mermaid
flowchart LR
    DimSeason -->|Season| FactDelivery
    DimSeason -->|Season| FactBattingInnings
    DimSeason -->|Season| FactTeamMatch
    DimSeason -->|Season| FactMatch
    DimVenue -->|venue_key| FactDelivery
    DimVenue -->|venue_key| FactBattingInnings
    DimVenue -->|venue_key| FactTeamMatch
    DimVenue -->|venue_key| FactMatch
    DimTeam -->|team_key| FactTeamMatch
    DimTeam -->|team_key| FactBattingInnings
    DimTeam -->|team_key| FactDelivery
    DimTeam -.->|team_key (bowling)| FactDelivery
    DimPlayer -->|player_key| FactDelivery
    DimPlayer -.->|player_key (bowling)| FactDelivery
    DimPlayer -->|player_key| FactBattingInnings
    DimPhase -->|Phase| FactDelivery
    PlayerA[Player A] -. TREATAS .-> DimPlayer
    PlayerB[Player B] -. TREATAS .-> DimPlayer
```

## Tables

| table | type | rows | columns | grain / description |
|---|---|---|---|---|
| FactDelivery | Fact | 260,920 | 34 | One row per ball bowled (260,920), incl. 161 super-over balls flagged by is_super_over. Measures exclude super overs. |
| FactBattingInnings | Fact | 16,842 | 15 | One row per player per batting innings (appeared as striker, non-striker or was dismissed). Regulation only. |
| FactTeamMatch | Fact | 2,190 | 18 | Two rows per match: the batting-first team and the chasing team (derived from deliveries, not team1/team2). |
| FactMatch | Fact | 1,095 | 30 | One row per match with approved result_for, D/L, full-match and chase-base flags. |
| DimSeason | Dimension | 17 | 4 | Seasons 2008-2024 (year of play). |
| DimTeam | Dimension | 15 | 7 | 15 standardized franchises (Phase 2 approved mapping). |
| DimVenue | Dimension | 36 | 6 | 36 standardized grounds. |
| DimPlayer | Dimension | 741 | 2 | 741 players (Cricsheet names). |
| DimPhase | Dimension | 4 | 3 | Powerplay 1-6, Middle 7-15, Death 16-20, Super Over. |
| Player A / Player B | Disconnected | 741 | 1 | Disconnected copy of player names for the comparison visual. |
| _Measures | Measures | 0 | 1 | 111 DAX measures |

## Relationships

| from (many) | to (one) | cardinality | cross-filter | active |
|---|---|---|---|---|
| FactDelivery[season_year] | DimSeason[Season] | many-to-one | single (dimension -> fact) | yes |
| FactBattingInnings[season_year] | DimSeason[Season] | many-to-one | single (dimension -> fact) | yes |
| FactTeamMatch[season_year] | DimSeason[Season] | many-to-one | single (dimension -> fact) | yes |
| FactMatch[season_year] | DimSeason[Season] | many-to-one | single (dimension -> fact) | yes |
| FactDelivery[venue_key] | DimVenue[venue_key] | many-to-one | single (dimension -> fact) | yes |
| FactBattingInnings[venue_key] | DimVenue[venue_key] | many-to-one | single (dimension -> fact) | yes |
| FactTeamMatch[venue_key] | DimVenue[venue_key] | many-to-one | single (dimension -> fact) | yes |
| FactMatch[venue_key] | DimVenue[venue_key] | many-to-one | single (dimension -> fact) | yes |
| FactTeamMatch[team_key] | DimTeam[team_key] | many-to-one | single (dimension -> fact) | yes |
| FactBattingInnings[team_key] | DimTeam[team_key] | many-to-one | single (dimension -> fact) | yes |
| FactDelivery[batting_team_key] | DimTeam[team_key] | many-to-one | single (dimension -> fact) | yes |
| FactDelivery[bowling_team_key] | DimTeam[team_key] | many-to-one | single (dimension -> fact) | no (USERELATIONSHIP in bowling measures) |
| FactDelivery[batter_key] | DimPlayer[player_key] | many-to-one | single (dimension -> fact) | yes |
| FactDelivery[bowler_key] | DimPlayer[player_key] | many-to-one | single (dimension -> fact) | no (USERELATIONSHIP in bowling measures) |
| FactBattingInnings[player_key] | DimPlayer[player_key] | many-to-one | single (dimension -> fact) | yes |
| FactDelivery[phase] | DimPhase[Phase] | many-to-one | single (dimension -> fact) | yes |

## Keys

| Table | Primary key | Foreign keys |
|---|---|---|
| FactDelivery | delivery_id | season_year, venue_key, batting_team_key, bowling_team_key, batter_key, bowler_key, phase |
| FactBattingInnings | (match_id, inning, player_key) | season_year, venue_key, team_key, player_key |
| FactTeamMatch | (match_id, team_key) | season_year, venue_key, team_key |
| FactMatch | match_id | season_year, venue_key |
| DimSeason / DimTeam / DimVenue / DimPlayer / DimPhase | Season / team_key / venue_key / player_key / Phase | - |

Key uniqueness and foreign-key resolution are validated in `reports/powerbi/export_validation_checks.csv` (X05, X06) and again inside Power BI (`dashboard_validation_report.md` R01-R03).
