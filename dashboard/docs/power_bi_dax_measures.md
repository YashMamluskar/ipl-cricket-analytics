# DAX Measures - IPL Cricket Analytics Dashboard

_Generated from `python/06c_build_pbip.py` (the single source of the model). 111 measures, all in the hidden `_Measures` table, grouped by display folder._

## Shared rules

- **Regulation only:** every ball-level measure filters `FactDelivery[is_super_over] = 0`.
- **Wickets:** `Bowler Wickets` / `Bowl Wickets` sum `is_bowler_wicket` (bowled, caught, c&b, lbw, stumped, hit wicket). `Dismissals` / `Outs` use `is_player_out` (retired hurt is not out). Raw `is_wicket` is never used.
- **Denominators:** run rate and economy use **legal balls** (not wides/no-balls); strike rate uses **balls faced** (all except wides); averages use **dismissals**; win % uses **decided** matches.
- **Bowling role:** bowling measures call `USERELATIONSHIP` on the inactive `bowler_key` and `bowling_team_key` relationships, so a player or franchise filter means 'as bowler / bowling side'.
- **Thresholds** (Phase 3/5): `Q ...` measures return BLANK below 50 innings, 500 balls faced or 1,000 legal balls; venue measures below 20 matches; close-match win % below 20 close matches.
- **Season-adjusted:** `exp_runs` / `exp_bowler_wkts` on each legal ball = league rate for that season and phase (computed in Python, validated to sum exactly to actual totals).


## Overview

| Measure | DAX | Format | Definition |
|---|---|---|---|
| **Matches** | `COUNTROWS(FactMatch)` | `#,0` | Matches with play (abandoned-without-a-ball matches are not in the source). |
| **Seasons** | `DISTINCTCOUNT(FactMatch[season_year])` | `0` | Distinct seasons in the current filter. |
| **Total Runs** | `CALCULATE(SUM(FactDelivery[total_runs]), FactDelivery[is_super_over] = 0)` | `#,0` | All runs incl. extras, regulation balls only (super overs excluded). |
| **Legal Balls** | `CALCULATE(SUM(FactDelivery[is_legal_delivery]), FactDelivery[is_super_over] = 0)` | `#,0` | Balls that are not wides or no-balls, regulation only. |
| **Bowler Wickets** | `CALCULATE(SUM(FactDelivery[is_bowler_wicket]), FactDelivery[is_super_over] = 0)` | `#,0` | Bowler-credited wickets: bowled, caught, caught and bowled, lbw, stumped, hit wicket. Excludes run outs, retired hurt/out, obstructing. |
| **Dismissals** | `CALCULATE(SUM(FactDelivery[is_player_out]), FactDelivery[is_super_over] = 0)` | `#,0` | All batter dismissals (incl. run outs); retired hurt is not out. |
| **Run Rate** | `DIVIDE([Total Runs] * 6, [Legal Balls])` | `0.00` | Runs per over = runs x 6 / legal balls. |
| **Run Rate Powerplay** | `CALCULATE([Run Rate], FactDelivery[phase] = "Powerplay")` | `0.00` | Run rate in overs 1-6. |
| **Run Rate Middle** | `CALCULATE([Run Rate], FactDelivery[phase] = "Middle")` | `0.00` | Run rate in overs 7-15. |
| **Run Rate Death** | `CALCULATE([Run Rate], FactDelivery[phase] = "Death")` | `0.00` | Run rate in overs 16-20. |
| **Share of Runs** | `DIVIDE([Total Runs], CALCULATE([Total Runs], REMOVEFILTERS(DimPhase)))` | `0.0%` | Share of runs scored in the phase in context. |
| **Full Matches** | `CALCULATE(COUNTROWS(FactMatch), FactMatch[is_full_match] = 1)` | `#,0` | Not a no-result and target_overs = 20. |
| **Avg First Innings** | `CALCULATE(AVERAGE(FactMatch[inn1_runs]), FactMatch[is_full_match] = 1)` | `0.0` | Average first-innings score over full 20-over matches (D/L, rain-shortened and no-result matches excluded). |
| **Runs per Match** | `DIVIDE([Total Runs], [Matches])` | `0.0` | Regulation runs per match with play. |
| **Fours** | `CALCULATE(SUM(FactDelivery[is_four]), FactDelivery[is_super_over] = 0)` | `#,0` | batsman_runs = 4 (documented proxy). |
| **Sixes** | `CALCULATE(SUM(FactDelivery[is_six]), FactDelivery[is_super_over] = 0)` | `#,0` | batsman_runs = 6 (documented proxy). |
| **Sixes per Match** | `DIVIDE([Sixes], [Matches])` | `0.0` |  |
| **Batting First Wins** | `CALCULATE(COUNTROWS(FactMatch), FactMatch[Result for] = "batting first")` | `#,0` | Uses approved result_for. |
| **Chasing Wins** | `CALCULATE(COUNTROWS(FactMatch), FactMatch[Result for] = "chasing")` | `#,0` | Uses approved result_for (includes 6 D/L chases won 'by runs'). |
| **Decided Matches** | `CALCULATE(COUNTROWS(FactMatch), FactMatch[is_decided_bf_chase] = 1)` | `#,0` | Matches decided by runs or wickets (super-over ties and no-results excluded). |
| **Batting First Win %** | `DIVIDE([Batting First Wins], [Decided Matches])` | `0.0%` |  |
| **Chasing Win %** | `DIVIDE([Chasing Wins], [Decided Matches])` | `0.0%` |  |
| **Toss Winner Win %** | `CALCULATE(AVERAGE(FactMatch[toss_winner_won]), FactMatch[is_no_result] = 0)` | `0.0%` | Share of decided matches won by the toss winner. Association only. |
| **Toss Winner Win % (chose field)** | `CALCULATE([Toss Winner Win %], FactMatch[Toss decision] = "field")` | `0.0%` | Toss winners who chose to field: share who won. |
| **Toss Winner Win % (chose bat)** | `CALCULATE([Toss Winner Win %], FactMatch[Toss decision] = "bat")` | `0.0%` | Toss winners who chose to bat: share who won. |
| **Close Matches** | `CALCULATE(COUNTROWS(FactMatch), FactMatch[is_close_match] = 1)` | `#,0` | Won by <= 10 runs, chase completed with <= 6 balls left (both non-D/L), or a tie. |
| **Close Match %** | `DIVIDE([Close Matches], CALCULATE(COUNTROWS(FactMatch), FactMatch[is_no_result] = 0))` | `0.0%` |  |
| **Run Rate vs Previous Season** | `VAR y = SELECTEDVALUE(DimSeason[Season]) VAR prev = CALCULATE([Run Rate], REMOVEFILTERS(DimSeason), DimSeason[Season] = y - 1) RETURN IF(NOT ISBLANK(y) && NOT ISBLANK(prev), [Run Rate] - prev)` | `+0.00;-0.00;0.00` | Change in run rate vs the previous season. |
| **Avg First Innings vs Previous Season** | `VAR y = SELECTEDVALUE(DimSeason[Season]) VAR prev = CALCULATE([Avg First Innings], REMOVEFILTERS(DimSeason), DimSeason[Season] = y - 1) RETURN IF(NOT ISBLANK(y) && NOT ISBLANK(prev), [Avg First Innings] - prev)` | `+0.0;-0.0;0.0` |  |

## Teams

| Measure | DAX | Format | Definition |
|---|---|---|---|
| **Team Matches** | `COUNTROWS(FactTeamMatch)` | `#,0` | Team appearances (2 per match). |
| **Wins** | `SUM(FactTeamMatch[won])` | `#,0` | Includes super-over wins. |
| **Losses** | `SUM(FactTeamMatch[lost])` | `#,0` |  |
| **Decided** | `SUM(FactTeamMatch[decided])` | `#,0` | Team matches excluding no-results. |
| **Win %** | `DIVIDE([Wins], [Decided])` | `0.0%` | Wins / decided matches. |
| **Titles** | `COALESCE(CALCULATE([Wins], FactTeamMatch[is_final] = 1), 0)` | `0` | Finals won (0 for franchises that never won or reached a final). |
| **Team Seasons** | `DISTINCTCOUNT(FactTeamMatch[season_year])` | `0` |  |
| **Bat First Win % (Team)** | `DIVIDE(CALCULATE([Wins], FactTeamMatch[batted_first] = 1, FactTeamMatch[is_decided_bf_chase] = 1), CALCULATE(COUNTROWS(FactTeamMatch), FactTeamMatch[batted_first] = 1, FactTeamMatch[is_decided_bf_chase] = 1))` | `0.0%` |  |
| **Chase Win % (Team)** | `DIVIDE(CALCULATE([Wins], FactTeamMatch[batted_first] = 0, FactTeamMatch[is_decided_bf_chase] = 1), CALCULATE(COUNTROWS(FactTeamMatch), FactTeamMatch[batted_first] = 0, FactTeamMatch[is_decided_bf_chase] = 1))` | `0.0%` |  |
| **Close Matches (Team)** | `CALCULATE([Decided], FactTeamMatch[is_close_match] = 1)` | `#,0` |  |
| **Close Match Win % (min 20)** | `VAR n = [Close Matches (Team)] RETURN IF(n >= 20, DIVIDE(CALCULATE([Wins], FactTeamMatch[is_close_match] = 1), n))` | `0.0%` | Close-match win %; blank for teams with fewer than 20 close matches (Phase 5 threshold). |
| **Team Batting vs League** | `CALCULATE(DIVIDE((SUM(FactDelivery[total_runs]) - SUM(FactDelivery[exp_runs])) * 6, SUM(FactDelivery[is_legal_delivery])), FactDelivery[is_super_over] = 0)` | `+0.00;-0.00;0.00` | Runs per over scored above the league rate for the same seasons and phases. |
| **Team Bowling vs League** | `CALCULATE(DIVIDE((SUM(FactDelivery[total_runs]) - SUM(FactDelivery[exp_runs])) * 6, SUM(FactDelivery[is_legal_delivery])), FactDelivery[is_super_over] = 0, USERELATIONSHIP(FactDelivery[bowling_team_key], DimTeam[team_key]))` | `+0.00;-0.00;0.00` | Runs per over conceded above the league rate (negative = better). |
| **Team Runs Saved vs League** | `-[Team Bowling vs League]` | `+0.00;-0.00;0.00` | Runs per over saved vs league (positive = better). |
| **Team Net vs League** | `[Team Batting vs League] - [Team Bowling vs League]` | `+0.00;-0.00;0.00` | Season- and phase-adjusted run-rate differential (Phase 5 D3). |
| **Team Wickets vs League per 120** | `CALCULATE(DIVIDE((SUM(FactDelivery[is_bowler_wicket]) - SUM(FactDelivery[exp_bowler_wkts])) * 120, SUM(FactDelivery[is_legal_delivery])), FactDelivery[is_super_over] = 0, USERELATIONSHIP(FactDelivery[bowling_team_key], DimTeam[team_key]))` | `+0.00;-0.00;0.00` |  |

## Batting

| Measure | DAX | Format | Definition |
|---|---|---|---|
| **Innings** | `COUNTROWS(FactBattingInnings)` | `#,0` | Batting innings (appeared as striker, non-striker or dismissed). |
| **Bat Runs** | `SUM(FactBattingInnings[runs])` | `#,0` | Runs off the bat (byes, leg-byes and wides excluded). |
| **Balls Faced** | `SUM(FactBattingInnings[balls])` | `#,0` | All balls except wides. |
| **Outs** | `SUM(FactBattingInnings[is_out])` | `#,0` | Dismissals (retired hurt is not out). |
| **Not Outs** | `[Innings] - [Outs]` | `#,0` |  |
| **Batting Average** | `DIVIDE([Bat Runs], [Outs])` | `0.00` | Runs / dismissals. |
| **Strike Rate** | `DIVIDE([Bat Runs] * 100, [Balls Faced])` | `0.00` | Runs per 100 balls faced. |
| **Bat Fours** | `SUM(FactBattingInnings[fours])` | `#,0` |  |
| **Bat Sixes** | `SUM(FactBattingInnings[sixes])` | `#,0` |  |
| **Boundary %** | `DIVIDE([Bat Fours] + [Bat Sixes], [Balls Faced])` | `0.0%` | Fours + sixes per ball faced. |
| **Boundary Run %** | `DIVIDE(4 * [Bat Fours] + 6 * [Bat Sixes], [Bat Runs])` | `0.0%` | Share of runs from boundaries. |
| **30+ Rate** | `DIVIDE(SUM(FactBattingInnings[is_30_plus]), [Innings])` | `0.0%` | Share of innings with 30+ runs. |
| **Fifties Plus** | `SUM(FactBattingInnings[is_50_plus])` | `0` | Innings of 50 or more (incl. hundreds). |
| **Hundreds** | `SUM(FactBattingInnings[is_100_plus])` | `0` |  |
| **Highest Score** | `MAX(FactBattingInnings[runs])` | `0` |  |
| **Q Innings** | `IF([Innings] >= 50, [Innings])` | `#,0` | Innings for batters with 50+ innings (ranking threshold). |
| **Q Batting Average** | `IF([Innings] >= 50, [Batting Average])` | `0.00` | Average shown only with 50+ innings. |
| **Q Strike Rate** | `IF([Balls Faced] >= 500, [Strike Rate])` | `0.00` | Strike rate shown only with 500+ balls faced. |
| **Q 30+ Rate** | `IF([Innings] >= 50, [30+ Rate])` | `0.0%` |  |
| **Top 10 Run Scorers** | `VAR r = [Bat Runs] RETURN IF(NOT ISBLANK(r) && RANKX(ALLSELECTED(DimPlayer), [Bat Runs], , DESC) <= 10, r)` | `#,0` | Batter runs, shown only for the 10 highest scorers in the current filters. |
| **Batter SR (balls)** | `CALCULATE(DIVIDE(SUM(FactDelivery[batsman_runs]) * 100, SUM(FactDelivery[is_ball_faced])), FactDelivery[is_super_over] = 0)` | `0.0` | Strike rate from ball-level data (used by phase visuals). |
| **Batter Runs (balls)** | `CALCULATE(SUM(FactDelivery[batsman_runs]), FactDelivery[is_super_over] = 0)` | `#,0` |  |

## Bowling

| Measure | DAX | Format | Definition |
|---|---|---|---|
| **Bowl Legal Balls** | `CALCULATE(SUM(FactDelivery[is_legal_delivery]), FactDelivery[is_super_over] = 0, USERELATIONSHIP(FactDelivery[bowler_key], DimPlayer[player_key]), USERELATIONSHIP(FactDelivery[bowling_team_key], DimTeam[team_key]))` | `#,0` | Legal balls bowled. |
| **Bowl Runs Conceded** | `CALCULATE(SUM(FactDelivery[bowler_runs_conceded]), FactDelivery[is_super_over] = 0, USERELATIONSHIP(FactDelivery[bowler_key], DimPlayer[player_key]), USERELATIONSHIP(FactDelivery[bowling_team_key], DimTeam[team_key]))` | `#,0` | Batter runs + wides + no-balls (byes, leg-byes, penalties not charged). |
| **Bowl Wickets** | `CALCULATE(SUM(FactDelivery[is_bowler_wicket]), FactDelivery[is_super_over] = 0, USERELATIONSHIP(FactDelivery[bowler_key], DimPlayer[player_key]), USERELATIONSHIP(FactDelivery[bowling_team_key], DimTeam[team_key]))` | `#,0` | Bowler-credited wickets only. |
| **Bowl Dots** | `CALCULATE(SUM(FactDelivery[is_dot_ball]), FactDelivery[is_super_over] = 0, USERELATIONSHIP(FactDelivery[bowler_key], DimPlayer[player_key]), USERELATIONSHIP(FactDelivery[bowling_team_key], DimTeam[team_key]))` | `#,0` |  |
| **Economy** | `DIVIDE([Bowl Runs Conceded] * 6, [Bowl Legal Balls])` | `0.00` | Runs conceded per over (legal balls). |
| **Bowling Average** | `DIVIDE([Bowl Runs Conceded], [Bowl Wickets])` | `0.00` |  |
| **Bowling Strike Rate** | `DIVIDE([Bowl Legal Balls], [Bowl Wickets])` | `0.0` | Legal balls per bowler wicket. |
| **Dot %** | `DIVIDE([Bowl Dots], [Bowl Legal Balls])` | `0.0%` |  |
| **Q Legal Balls** | `IF([Bowl Legal Balls] >= 1000, [Bowl Legal Balls])` | `#,0` | Shown only with 1,000+ legal balls. |
| **Q Economy** | `IF([Bowl Legal Balls] >= 1000, [Economy])` | `0.00` |  |
| **Q Bowling Average** | `IF([Bowl Legal Balls] >= 1000, [Bowling Average])` | `0.00` |  |
| **Q Bowling Strike Rate** | `IF([Bowl Legal Balls] >= 1000, [Bowling Strike Rate])` | `0.0` |  |
| **Q Dot %** | `IF([Bowl Legal Balls] >= 1000, [Dot %])` | `0.0%` |  |
| **Q Wickets** | `IF([Bowl Legal Balls] >= 1000, [Bowl Wickets])` | `#,0` |  |
| **Top 10 Wicket Takers** | `VAR w = [Bowl Wickets] RETURN IF(NOT ISBLANK(w) && RANKX(ALLSELECTED(DimPlayer), [Bowl Wickets], , DESC) <= 10, w)` | `#,0` |  |

## Comparison

| Measure | DAX | Format | Definition |
|---|---|---|---|
| **Player A Name** | `SELECTEDVALUE('Player A'[Player A], "Select player A")` | `` |  |
| **Player B Name** | `SELECTEDVALUE('Player B'[Player B], "Select player B")` | `` |  |
| **Player A Innings** | `IF(HASONEVALUE('Player A'[Player A]), CALCULATE([Innings], TREATAS(VALUES('Player A'[Player A]), DimPlayer[Player])))` | `#,0` |  |
| **Player A Runs** | `IF(HASONEVALUE('Player A'[Player A]), CALCULATE([Bat Runs], TREATAS(VALUES('Player A'[Player A]), DimPlayer[Player])))` | `#,0` |  |
| **Player A Average** | `IF(HASONEVALUE('Player A'[Player A]), CALCULATE([Batting Average], TREATAS(VALUES('Player A'[Player A]), DimPlayer[Player])))` | `0.00` |  |
| **Player A Strike Rate** | `IF(HASONEVALUE('Player A'[Player A]), CALCULATE([Strike Rate], TREATAS(VALUES('Player A'[Player A]), DimPlayer[Player])))` | `0.00` |  |
| **Player A Boundary %** | `IF(HASONEVALUE('Player A'[Player A]), CALCULATE([Boundary %], TREATAS(VALUES('Player A'[Player A]), DimPlayer[Player])))` | `0.0%` |  |
| **Player A Wickets** | `IF(HASONEVALUE('Player A'[Player A]), CALCULATE([Bowl Wickets], TREATAS(VALUES('Player A'[Player A]), DimPlayer[Player])))` | `#,0` |  |
| **Player A Economy** | `IF(HASONEVALUE('Player A'[Player A]), CALCULATE([Economy], TREATAS(VALUES('Player A'[Player A]), DimPlayer[Player])))` | `0.00` |  |
| **Player A Phase SR** | `IF(HASONEVALUE('Player A'[Player A]), CALCULATE([Batter SR (balls)], TREATAS(VALUES('Player A'[Player A]), DimPlayer[Player])))` | `0.0` |  |
| **Player B Innings** | `IF(HASONEVALUE('Player B'[Player B]), CALCULATE([Innings], TREATAS(VALUES('Player B'[Player B]), DimPlayer[Player])))` | `#,0` |  |
| **Player B Runs** | `IF(HASONEVALUE('Player B'[Player B]), CALCULATE([Bat Runs], TREATAS(VALUES('Player B'[Player B]), DimPlayer[Player])))` | `#,0` |  |
| **Player B Average** | `IF(HASONEVALUE('Player B'[Player B]), CALCULATE([Batting Average], TREATAS(VALUES('Player B'[Player B]), DimPlayer[Player])))` | `0.00` |  |
| **Player B Strike Rate** | `IF(HASONEVALUE('Player B'[Player B]), CALCULATE([Strike Rate], TREATAS(VALUES('Player B'[Player B]), DimPlayer[Player])))` | `0.00` |  |
| **Player B Boundary %** | `IF(HASONEVALUE('Player B'[Player B]), CALCULATE([Boundary %], TREATAS(VALUES('Player B'[Player B]), DimPlayer[Player])))` | `0.0%` |  |
| **Player B Wickets** | `IF(HASONEVALUE('Player B'[Player B]), CALCULATE([Bowl Wickets], TREATAS(VALUES('Player B'[Player B]), DimPlayer[Player])))` | `#,0` |  |
| **Player B Economy** | `IF(HASONEVALUE('Player B'[Player B]), CALCULATE([Economy], TREATAS(VALUES('Player B'[Player B]), DimPlayer[Player])))` | `0.00` |  |
| **Player B Phase SR** | `IF(HASONEVALUE('Player B'[Player B]), CALCULATE([Batter SR (balls)], TREATAS(VALUES('Player B'[Player B]), DimPlayer[Player])))` | `0.0` |  |

## Match

| Measure | DAX | Format | Definition |
|---|---|---|---|
| **Chases** | `CALCULATE(COUNTROWS(FactMatch), FactMatch[is_chase_base] = 1)` | `#,0` | Full 20-over, non-D/L chases decided by runs or wickets. |
| **Chase Success %** | `DIVIDE(CALCULATE(SUM(FactMatch[chase_won]), FactMatch[is_chase_base] = 1), [Chases])` | `0.0%` |  |
| **Chase Success CI Low** | `VAR n = [Chases] VAR p = DIVIDE(CALCULATE(SUM(FactMatch[chase_won]), FactMatch[is_chase_base] = 1), n) VAR z = 1.959964 VAR den = 1 + z * z / n VAR c = (p + z * z / (2 * n)) / den VAR h = z * SQRT(p * (1 - p) / n + z * z / (4 * n * n)) / den RETURN IF(n > 0, MAX(0, c - h))` | `0.0%` | 95% Wilson interval lower bound. |
| **Chase Success CI High** | `VAR n = [Chases] VAR p = DIVIDE(CALCULATE(SUM(FactMatch[chase_won]), FactMatch[is_chase_base] = 1), n) VAR z = 1.959964 VAR den = 1 + z * z / n VAR c = (p + z * z / (2 * n)) / den VAR h = z * SQRT(p * (1 - p) / n + z * z / (4 * n * n)) / den RETURN IF(n > 0, MIN(1, c + h))` | `0.0%` |  |
| **Avg First Innings vs Season** | `AVERAGEX(FILTER(FactMatch, FactMatch[is_full_match] = 1), FactMatch[inn1_runs] - CALCULATE(AVERAGE(FactMatch[inn1_runs]), ALLEXCEPT(FactMatch, FactMatch[season_year]), FactMatch[is_full_match] = 1))` | `+0.0;-0.0;0.0` | Average of (first-innings score - that season's league average), full matches. |
| **Venue Qualifies** | `IF([Full Matches] >= 20 && [Decided Matches] >= 20, 1)` | `0` | 1 when the venue has 20+ full and 20+ decided matches. |
| **Venue Full Matches (min 20)** | `IF([Venue Qualifies] = 1, [Full Matches])` | `#,0` |  |
| **Venue Avg First Innings (min 20)** | `IF([Venue Qualifies] = 1, [Avg First Innings])` | `0.0` |  |
| **Venue vs Season (min 20)** | `IF([Venue Qualifies] = 1, [Avg First Innings vs Season])` | `+0.0;-0.0;0.0` |  |
| **Venue Chase Win % (min 20)** | `IF([Venue Qualifies] = 1, [Chasing Win %])` | `0.0%` |  |
| **Toss Matches** | `CALCULATE(COUNTROWS(FactMatch), FactMatch[is_no_result] = 0)` | `#,0` |  |
