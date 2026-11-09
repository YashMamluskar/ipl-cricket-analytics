"""
Phase 6c - Generate the Power BI Project (PBIP: TMDL semantic model + PBIR report)
==================================================================================

Writes dashboard/IPL_Cricket_Analytics/ :
    IPL_Cricket_Analytics.pbip
    IPL_Cricket_Analytics.SemanticModel/   (TMDL: tables, relationships, measures)
    IPL_Cricket_Analytics.Report/          (PBIR: theme, 3 pages + hidden drill-through page)

Source data: data/final/powerbi/*.csv (python/06b_export_powerbi_model.py).
Everything (model, DAX, layout, colours) is generated from this file, so the dashboard
is fully reproducible and diff-able. Open the .pbip in Power BI Desktop.

    python python/06c_build_pbip.py
"""
from __future__ import annotations

import json
import shutil
import sys
import uuid
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ipl_config as cfg  # noqa: E402

NAME = "IPL_Cricket_Analytics"
ROOT = cfg.PROJECT_ROOT / "dashboard" / NAME
SM = ROOT / f"{NAME}.SemanticModel"
RP = ROOT / f"{NAME}.Report"
DATA = (cfg.FINAL_DIR / "powerbi").as_posix()
NS = uuid.UUID("6f1c2b6e-1a0f-4e2e-9d3b-3b1b4f7a2e6f")  # deterministic lineage tags -> stable diffs

# ------------------------------------------------------------------ design system
C = {"bg": "#1A0F2E", "card": "#3B1B4F", "purple": "#7A2E6F", "pink": "#D6598F", "text": "#F4D7D4",
     "coral": "#FF6B6B", "muted": "#AA8C9F", "context": "#A56992", "grid": "#573763", "mid": "#E492AE",
     "row_alt": "#432158"}
PHASE_COL = {"Powerplay": C["text"], "Middle": C["mid"], "Death": C["pink"]}


def lt(name):
    return str(uuid.uuid5(NS, name))


def write(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.replace("\r\n", "\n").replace("\n", "\r\n").encode("utf-8"))  # UTF-8 no BOM, CRLF


def wjson(path: Path, obj):
    write(path, json.dumps(obj, indent=2, ensure_ascii=False))


def q(name):  # TMDL object-name quoting
    return f"'{name}'" if any(ch in name for ch in " .=:'+-%()/#&,") or name[0].isdigit() else name


# ================================================================== SEMANTIC MODEL
# table -> {source_column: (display_name, dataType, hidden, formatString)}
INT_NULLABLE = {"winner_team_key", "wkts_before", "inn2_runs", "result_margin", "toss_winner_won"}
DISPLAY = {
    "DimSeason": {"season_year": "Season", "season_label": "Season label", "era": "Era", "period": "Period"},
    "DimTeam": {"team_key": "team_key", "franchise": "Franchise", "franchise_short": "Short name",
                "first_season": "First season", "last_season": "Last season", "seasons": "Seasons played",
                "is_established": "Established (10+ seasons)"},
    "DimVenue": {"venue_key": "venue_key", "venue": "Venue", "city": "City", "full_matches": "Full matches (all seasons)",
                 "decided": "Decided matches (all seasons)", "qualifies_20": "Qualifies (20+ matches)"},
    "DimPlayer": {"player_key": "player_key", "player": "Player"},
    "DimPhase": {"phase": "Phase", "phase_sort": "Phase order", "overs": "Overs"},
    "FactMatch": {"first_innings_band": "First-innings band", "toss_decision": "Toss decision", "result_for": "Result for",
                  "match_type": "Match type", "win_type": "Win type"},
    "FactDelivery": {"wkts_lost_band": "Wickets lost before ball", "phase": "phase"},
}
VISIBLE = {  # columns left visible in the field list; everything else hidden (measures are the interface)
    "DimSeason": {"season_year", "era", "period"}, "DimTeam": {"franchise", "franchise_short", "seasons", "is_established"},
    "DimVenue": {"venue", "city"}, "DimPlayer": {"player"}, "DimPhase": {"phase", "overs"},
    "FactMatch": {"first_innings_band", "toss_decision", "result_for", "match_type", "win_type"},
    "FactDelivery": {"wkts_lost_band"}, "FactTeamMatch": set(), "FactBattingInnings": set(),
}
SORT_BY = {("FactMatch", "first_innings_band"): "first_innings_band_sort", ("DimPhase", "phase"): "phase_sort"}
DESCRIPTIONS = {
    "FactDelivery": "One row per ball bowled (260,920), incl. 161 super-over balls flagged by is_super_over. Measures exclude super overs.",
    "FactBattingInnings": "One row per player per batting innings (appeared as striker, non-striker or was dismissed). Regulation only.",
    "FactTeamMatch": "Two rows per match: the batting-first team and the chasing team (derived from deliveries, not team1/team2).",
    "FactMatch": "One row per match with approved result_for, D/L, full-match and chase-base flags.",
    "DimSeason": "Seasons 2008-2024 (year of play).", "DimTeam": "15 standardized franchises (Phase 2 approved mapping).",
    "DimVenue": "36 standardized grounds.", "DimPlayer": "741 players (Cricsheet names).",
    "DimPhase": "Powerplay 1-6, Middle 7-15, Death 16-20, Super Over.",
    "Player A": "Disconnected copy of player names for the comparison visual.",
    "Player B": "Disconnected copy of player names for the comparison visual.",
}


def tmdl_type(df, col):
    if col in INT_NULLABLE:
        return "int64", "Int64.Type"
    k = df[col].dtype.kind
    if k in "iub":
        return "int64", "Int64.Type"
    if k == "f":
        return "double", "type number"
    return "string", "type text"


def table_tmdl(tname, csv, df, extra_measures="", rename=None, src_override=None):
    rename = rename or DISPLAY.get(tname, {})
    lines = []
    if tname in DESCRIPTIONS:
        lines.append(f"/// {DESCRIPTIONS[tname]}")
    lines += [f"table {q(tname)}", f"\tlineageTag: {lt(tname)}", ""]
    if extra_measures:
        lines.append(extra_measures)
    types = []
    for col in df.columns:
        dt, mt = tmdl_type(df, col)
        disp = rename.get(col, col)
        types.append((col, mt))
        lines.append(f"\tcolumn {q(disp)}")
        lines.append(f"\t\tdataType: {dt}")
        if col not in VISIBLE.get(tname, set(df.columns)):
            lines.append("\t\tisHidden")
        if dt == "int64":
            lines.append("\t\tformatString: 0")
        elif dt == "double":
            lines.append("\t\tformatString: 0.00")
        lines.append(f"\t\tlineageTag: {lt(tname + '.' + col)}")
        lines.append("\t\tsummarizeBy: none")
        lines.append(f"\t\tsourceColumn: {col}")
        if (tname, col) in SORT_BY:
            lines.append(f"\t\tsortByColumn: {q(rename.get(SORT_BY[(tname, col)], SORT_BY[(tname, col)]))}")
        lines.append("")
    tlist = ", ".join('{"%s", %s}' % (c, m) for c, m in types)
    cols = ", ".join(f'"{c}"' for c in df.columns)
    src = src_override or f'DataFolder & "/{csv}"'
    m = [
        "let",
        f"    Source = Csv.Document(File.Contents({src}), [Delimiter = \",\", Encoding = 65001, QuoteStyle = QuoteStyle.Csv]),",
        "    Promoted = Table.PromoteHeaders(Source, [PromoteAllScalars = true]),",
        f"    Selected = Table.SelectColumns(Promoted, {{{cols}}}),",
        "    Blanks = Table.TransformColumns(Selected, List.Transform(Table.ColumnNames(Selected), (c) => {c, each if _ = \"\" then null else _})),",
        f"    Typed = Table.TransformColumnTypes(Blanks, {{{tlist}}}, \"en-US\")",
        "in",
        "    Typed",
    ]
    lines.append(f"\tpartition {q(tname)} = m")
    lines.append("\t\tmode: import")
    lines.append("\t\tsource =")
    lines += ["\t\t\t\t" + x for x in m]
    lines.append("")
    lines.append("\tannotation PBI_ResultType = Table")
    return "\n".join(lines) + "\n"


# ------------------------------------------------------------------ measures
SO = "FactDelivery[is_super_over] = 0"
BOWL = "USERELATIONSHIP(FactDelivery[bowler_key], DimPlayer[player_key]), USERELATIONSHIP(FactDelivery[bowling_team_key], DimTeam[team_key])"
TEAM_BOWL = "USERELATIONSHIP(FactDelivery[bowling_team_key], DimTeam[team_key])"


def wilson(prefix, k, n, sign):
    return (f"VAR n = {n} VAR p = DIVIDE({k}, n) VAR z = 1.959964 VAR den = 1 + z * z / n "
            f"VAR c = (p + z * z / (2 * n)) / den VAR h = z * SQRT(p * (1 - p) / n + z * z / (4 * n * n)) / den "
            f"RETURN IF(n > 0, {'MAX(0, c - h)' if sign < 0 else 'MIN(1, c + h)'})")


def pA(base, who="A"):
    return (f"IF(HASONEVALUE('Player {who}'[Player {who}]), CALCULATE({base}, "
            f"TREATAS(VALUES('Player {who}'[Player {who}]), DimPlayer[Player])))")


MEASURES = [
    # folder, name, expression, format, description
    ("1 Overview", "Matches", "COUNTROWS(FactMatch)", "#,0", "Matches with play (abandoned-without-a-ball matches are not in the source)."),
    ("1 Overview", "Seasons", "DISTINCTCOUNT(FactMatch[season_year])", "0", "Distinct seasons in the current filter."),
    ("1 Overview", "Total Runs", f"CALCULATE(SUM(FactDelivery[total_runs]), {SO})", "#,0", "All runs incl. extras, regulation balls only (super overs excluded)."),
    ("1 Overview", "Legal Balls", f"CALCULATE(SUM(FactDelivery[is_legal_delivery]), {SO})", "#,0", "Balls that are not wides or no-balls, regulation only."),
    ("1 Overview", "Bowler Wickets", f"CALCULATE(SUM(FactDelivery[is_bowler_wicket]), {SO})", "#,0",
     "Bowler-credited wickets: bowled, caught, caught and bowled, lbw, stumped, hit wicket. Excludes run outs, retired hurt/out, obstructing."),
    ("1 Overview", "Dismissals", f"CALCULATE(SUM(FactDelivery[is_player_out]), {SO})", "#,0", "All batter dismissals (incl. run outs); retired hurt is not out."),
    ("1 Overview", "Run Rate", "DIVIDE([Total Runs] * 6, [Legal Balls])", "0.00", "Runs per over = runs x 6 / legal balls."),
    ("1 Overview", "Run Rate Powerplay", "CALCULATE([Run Rate], FactDelivery[phase] = \"Powerplay\")", "0.00", "Run rate in overs 1-6."),
    ("1 Overview", "Run Rate Middle", "CALCULATE([Run Rate], FactDelivery[phase] = \"Middle\")", "0.00", "Run rate in overs 7-15."),
    ("1 Overview", "Run Rate Death", "CALCULATE([Run Rate], FactDelivery[phase] = \"Death\")", "0.00", "Run rate in overs 16-20."),
    ("1 Overview", "Share of Runs", f"DIVIDE([Total Runs], CALCULATE([Total Runs], REMOVEFILTERS(DimPhase)))", "0.0%", "Share of runs scored in the phase in context."),
    ("1 Overview", "Full Matches", "CALCULATE(COUNTROWS(FactMatch), FactMatch[is_full_match] = 1)", "#,0", "Not a no-result and target_overs = 20."),
    ("1 Overview", "Avg First Innings", "CALCULATE(AVERAGE(FactMatch[inn1_runs]), FactMatch[is_full_match] = 1)", "0.0",
     "Average first-innings score over full 20-over matches (D/L, rain-shortened and no-result matches excluded)."),
    ("1 Overview", "Runs per Match", "DIVIDE([Total Runs], [Matches])", "0.0", "Regulation runs per match with play."),
    ("1 Overview", "Fours", f"CALCULATE(SUM(FactDelivery[is_four]), {SO})", "#,0", "batsman_runs = 4 (documented proxy)."),
    ("1 Overview", "Sixes", f"CALCULATE(SUM(FactDelivery[is_six]), {SO})", "#,0", "batsman_runs = 6 (documented proxy)."),
    ("1 Overview", "Sixes per Match", "DIVIDE([Sixes], [Matches])", "0.0", ""),
    ("1 Overview", "Batting First Wins", "CALCULATE(COUNTROWS(FactMatch), FactMatch[Result for] = \"batting first\")", "#,0", "Uses approved result_for."),
    ("1 Overview", "Chasing Wins", "CALCULATE(COUNTROWS(FactMatch), FactMatch[Result for] = \"chasing\")", "#,0",
     "Uses approved result_for (includes 6 D/L chases won 'by runs')."),
    ("1 Overview", "Decided Matches", "CALCULATE(COUNTROWS(FactMatch), FactMatch[is_decided_bf_chase] = 1)", "#,0",
     "Matches decided by runs or wickets (super-over ties and no-results excluded)."),
    ("1 Overview", "Batting First Win %", "DIVIDE([Batting First Wins], [Decided Matches])", "0.0%", ""),
    ("1 Overview", "Chasing Win %", "DIVIDE([Chasing Wins], [Decided Matches])", "0.0%", ""),
    ("1 Overview", "Toss Winner Win %", "CALCULATE(AVERAGE(FactMatch[toss_winner_won]), FactMatch[is_no_result] = 0)", "0.0%",
     "Share of decided matches won by the toss winner. Association only."),
    ("1 Overview", "Toss Winner Win % (chose field)",
     "CALCULATE([Toss Winner Win %], FactMatch[Toss decision] = \"field\")", "0.0%", "Toss winners who chose to field: share who won."),
    ("1 Overview", "Toss Winner Win % (chose bat)",
     "CALCULATE([Toss Winner Win %], FactMatch[Toss decision] = \"bat\")", "0.0%", "Toss winners who chose to bat: share who won."),
    ("1 Overview", "Close Matches","CALCULATE(COUNTROWS(FactMatch), FactMatch[is_close_match] = 1)", "#,0",
     "Won by <= 10 runs, chase completed with <= 6 balls left (both non-D/L), or a tie."),
    ("1 Overview", "Close Match %", "DIVIDE([Close Matches], CALCULATE(COUNTROWS(FactMatch), FactMatch[is_no_result] = 0))", "0.0%", ""),
    ("1 Overview", "Run Rate vs Previous Season",
     "VAR y = SELECTEDVALUE(DimSeason[Season]) VAR prev = CALCULATE([Run Rate], REMOVEFILTERS(DimSeason), DimSeason[Season] = y - 1) "
     "RETURN IF(NOT ISBLANK(y) && NOT ISBLANK(prev), [Run Rate] - prev)", "+0.00;-0.00;0.00", "Change in run rate vs the previous season."),
    ("1 Overview", "Avg First Innings vs Previous Season",
     "VAR y = SELECTEDVALUE(DimSeason[Season]) VAR prev = CALCULATE([Avg First Innings], REMOVEFILTERS(DimSeason), DimSeason[Season] = y - 1) "
     "RETURN IF(NOT ISBLANK(y) && NOT ISBLANK(prev), [Avg First Innings] - prev)", "+0.0;-0.0;0.0", ""),
    # ---------------------------------------------------------- teams
    ("2 Teams", "Team Matches", "COUNTROWS(FactTeamMatch)", "#,0", "Team appearances (2 per match)."),
    ("2 Teams", "Wins", "SUM(FactTeamMatch[won])", "#,0", "Includes super-over wins."),
    ("2 Teams", "Losses", "SUM(FactTeamMatch[lost])", "#,0", ""),
    ("2 Teams", "Decided", "SUM(FactTeamMatch[decided])", "#,0", "Team matches excluding no-results."),
    ("2 Teams", "Win %", "DIVIDE([Wins], [Decided])", "0.0%", "Wins / decided matches."),
    ("2 Teams", "Titles", "COALESCE(CALCULATE([Wins], FactTeamMatch[is_final] = 1), 0)", "0",
     "Finals won (0 for franchises that never won or reached a final)."),
    ("2 Teams", "Team Seasons", "DISTINCTCOUNT(FactTeamMatch[season_year])", "0", ""),
    ("2 Teams", "Bat First Win % (Team)",
     "DIVIDE(CALCULATE([Wins], FactTeamMatch[batted_first] = 1, FactTeamMatch[is_decided_bf_chase] = 1), "
     "CALCULATE(COUNTROWS(FactTeamMatch), FactTeamMatch[batted_first] = 1, FactTeamMatch[is_decided_bf_chase] = 1))", "0.0%", ""),
    ("2 Teams", "Chase Win % (Team)",
     "DIVIDE(CALCULATE([Wins], FactTeamMatch[batted_first] = 0, FactTeamMatch[is_decided_bf_chase] = 1), "
     "CALCULATE(COUNTROWS(FactTeamMatch), FactTeamMatch[batted_first] = 0, FactTeamMatch[is_decided_bf_chase] = 1))", "0.0%", ""),
    ("2 Teams", "Close Matches (Team)", "CALCULATE([Decided], FactTeamMatch[is_close_match] = 1)", "#,0", ""),
    ("2 Teams", "Close Match Win % (min 20)",
     "VAR n = [Close Matches (Team)] RETURN IF(n >= 20, DIVIDE(CALCULATE([Wins], FactTeamMatch[is_close_match] = 1), n))", "0.0%",
     "Close-match win %; blank for teams with fewer than 20 close matches (Phase 5 threshold)."),
    ("2 Teams", "Team Batting vs League",
     f"CALCULATE(DIVIDE((SUM(FactDelivery[total_runs]) - SUM(FactDelivery[exp_runs])) * 6, SUM(FactDelivery[is_legal_delivery])), {SO})",
     "+0.00;-0.00;0.00", "Runs per over scored above the league rate for the same seasons and phases."),
    ("2 Teams", "Team Bowling vs League",
     f"CALCULATE(DIVIDE((SUM(FactDelivery[total_runs]) - SUM(FactDelivery[exp_runs])) * 6, SUM(FactDelivery[is_legal_delivery])), {SO}, {TEAM_BOWL})",
     "+0.00;-0.00;0.00", "Runs per over conceded above the league rate (negative = better)."),
    ("2 Teams", "Team Runs Saved vs League", "-[Team Bowling vs League]", "+0.00;-0.00;0.00", "Runs per over saved vs league (positive = better)."),
    ("2 Teams", "Team Net vs League", "[Team Batting vs League] - [Team Bowling vs League]", "+0.00;-0.00;0.00",
     "Season- and phase-adjusted run-rate differential (Phase 5 D3)."),
    ("2 Teams", "Team Wickets vs League per 120",
     f"CALCULATE(DIVIDE((SUM(FactDelivery[is_bowler_wicket]) - SUM(FactDelivery[exp_bowler_wkts])) * 120, SUM(FactDelivery[is_legal_delivery])), {SO}, {TEAM_BOWL})",
     "+0.00;-0.00;0.00", ""),
    # ---------------------------------------------------------- batting
    ("3 Batting", "Innings", "COUNTROWS(FactBattingInnings)", "#,0", "Batting innings (appeared as striker, non-striker or dismissed)."),
    ("3 Batting", "Bat Runs", "SUM(FactBattingInnings[runs])", "#,0", "Runs off the bat (byes, leg-byes and wides excluded)."),
    ("3 Batting", "Balls Faced", "SUM(FactBattingInnings[balls])", "#,0", "All balls except wides."),
    ("3 Batting", "Outs", "SUM(FactBattingInnings[is_out])", "#,0", "Dismissals (retired hurt is not out)."),
    ("3 Batting", "Not Outs", "[Innings] - [Outs]", "#,0", ""),
    ("3 Batting", "Batting Average", "DIVIDE([Bat Runs], [Outs])", "0.00", "Runs / dismissals."),
    ("3 Batting", "Strike Rate", "DIVIDE([Bat Runs] * 100, [Balls Faced])", "0.00", "Runs per 100 balls faced."),
    ("3 Batting", "Bat Fours", "SUM(FactBattingInnings[fours])", "#,0", ""),
    ("3 Batting", "Bat Sixes", "SUM(FactBattingInnings[sixes])", "#,0", ""),
    ("3 Batting", "Boundary %", "DIVIDE([Bat Fours] + [Bat Sixes], [Balls Faced])", "0.0%", "Fours + sixes per ball faced."),
    ("3 Batting", "Boundary Run %", "DIVIDE(4 * [Bat Fours] + 6 * [Bat Sixes], [Bat Runs])", "0.0%", "Share of runs from boundaries."),
    ("3 Batting", "30+ Rate", "DIVIDE(SUM(FactBattingInnings[is_30_plus]), [Innings])", "0.0%", "Share of innings with 30+ runs."),
    ("3 Batting", "Fifties Plus", "SUM(FactBattingInnings[is_50_plus])", "0", "Innings of 50 or more (incl. hundreds)."),
    ("3 Batting", "Hundreds", "SUM(FactBattingInnings[is_100_plus])", "0", ""),
    ("3 Batting", "Highest Score", "MAX(FactBattingInnings[runs])", "0", ""),
    ("3 Batting", "Q Innings", "IF([Innings] >= 50, [Innings])", "#,0", "Innings for batters with 50+ innings (ranking threshold)."),
    ("3 Batting", "Q Batting Average", "IF([Innings] >= 50, [Batting Average])", "0.00", "Average shown only with 50+ innings."),
    ("3 Batting", "Q Strike Rate", "IF([Balls Faced] >= 500, [Strike Rate])", "0.00", "Strike rate shown only with 500+ balls faced."),
    ("3 Batting", "Q 30+ Rate", "IF([Innings] >= 50, [30+ Rate])", "0.0%", ""),
    ("3 Batting", "Top 10 Run Scorers",
     "VAR r = [Bat Runs] RETURN IF(NOT ISBLANK(r) && RANKX(ALLSELECTED(DimPlayer), [Bat Runs], , DESC) <= 10, r)", "#,0",
     "Batter runs, shown only for the 10 highest scorers in the current filters."),
    ("3 Batting", "Batter SR (balls)",
     f"CALCULATE(DIVIDE(SUM(FactDelivery[batsman_runs]) * 100, SUM(FactDelivery[is_ball_faced])), {SO})", "0.0",
     "Strike rate from ball-level data (used by phase visuals)."),
    ("3 Batting", "Batter Runs (balls)", f"CALCULATE(SUM(FactDelivery[batsman_runs]), {SO})", "#,0", ""),
    # ---------------------------------------------------------- bowling
    ("4 Bowling", "Bowl Legal Balls", f"CALCULATE(SUM(FactDelivery[is_legal_delivery]), {SO}, {BOWL})", "#,0", "Legal balls bowled."),
    ("4 Bowling", "Bowl Runs Conceded", f"CALCULATE(SUM(FactDelivery[bowler_runs_conceded]), {SO}, {BOWL})", "#,0",
     "Batter runs + wides + no-balls (byes, leg-byes, penalties not charged)."),
    ("4 Bowling", "Bowl Wickets", f"CALCULATE(SUM(FactDelivery[is_bowler_wicket]), {SO}, {BOWL})", "#,0", "Bowler-credited wickets only."),
    ("4 Bowling", "Bowl Dots", f"CALCULATE(SUM(FactDelivery[is_dot_ball]), {SO}, {BOWL})", "#,0", ""),
    ("4 Bowling", "Economy", "DIVIDE([Bowl Runs Conceded] * 6, [Bowl Legal Balls])", "0.00", "Runs conceded per over (legal balls)."),
    ("4 Bowling", "Bowling Average", "DIVIDE([Bowl Runs Conceded], [Bowl Wickets])", "0.00", ""),
    ("4 Bowling", "Bowling Strike Rate", "DIVIDE([Bowl Legal Balls], [Bowl Wickets])", "0.0", "Legal balls per bowler wicket."),
    ("4 Bowling", "Dot %", "DIVIDE([Bowl Dots], [Bowl Legal Balls])", "0.0%", ""),
    ("4 Bowling", "Q Legal Balls", "IF([Bowl Legal Balls] >= 1000, [Bowl Legal Balls])", "#,0", "Shown only with 1,000+ legal balls."),
    ("4 Bowling", "Q Economy", "IF([Bowl Legal Balls] >= 1000, [Economy])", "0.00", ""),
    ("4 Bowling", "Q Bowling Average", "IF([Bowl Legal Balls] >= 1000, [Bowling Average])", "0.00", ""),
    ("4 Bowling", "Q Bowling Strike Rate", "IF([Bowl Legal Balls] >= 1000, [Bowling Strike Rate])", "0.0", ""),
    ("4 Bowling", "Q Dot %", "IF([Bowl Legal Balls] >= 1000, [Dot %])", "0.0%", ""),
    ("4 Bowling", "Q Wickets", "IF([Bowl Legal Balls] >= 1000, [Bowl Wickets])", "#,0", ""),
    ("4 Bowling", "Top 10 Wicket Takers",
     "VAR w = [Bowl Wickets] RETURN IF(NOT ISBLANK(w) && RANKX(ALLSELECTED(DimPlayer), [Bowl Wickets], , DESC) <= 10, w)", "#,0", ""),
    # ---------------------------------------------------------- comparison
    ("5 Comparison", "Player A Name", "SELECTEDVALUE('Player A'[Player A], \"Select player A\")", "", ""),
    ("5 Comparison", "Player B Name", "SELECTEDVALUE('Player B'[Player B], \"Select player B\")", "", ""),
] + [("5 Comparison", f"Player {w} {lab}", pA(base, w), fmt, "") for w in "AB" for lab, base, fmt in [
    ("Innings", "[Innings]", "#,0"), ("Runs", "[Bat Runs]", "#,0"), ("Average", "[Batting Average]", "0.00"),
    ("Strike Rate", "[Strike Rate]", "0.00"), ("Boundary %", "[Boundary %]", "0.0%"), ("Wickets", "[Bowl Wickets]", "#,0"),
    ("Economy", "[Economy]", "0.00"), ("Phase SR", "[Batter SR (balls)]", "0.0")]] + [
    # ---------------------------------------------------------- chase / venue
    ("6 Match", "Chases", "CALCULATE(COUNTROWS(FactMatch), FactMatch[is_chase_base] = 1)", "#,0",
     "Full 20-over, non-D/L chases decided by runs or wickets."),
    ("6 Match", "Chase Success %", "DIVIDE(CALCULATE(SUM(FactMatch[chase_won]), FactMatch[is_chase_base] = 1), [Chases])", "0.0%", ""),
    ("6 Match", "Chase Success CI Low", wilson("c", "CALCULATE(SUM(FactMatch[chase_won]), FactMatch[is_chase_base] = 1)", "[Chases]", -1), "0.0%",
     "95% Wilson interval lower bound."),
    ("6 Match", "Chase Success CI High", wilson("c", "CALCULATE(SUM(FactMatch[chase_won]), FactMatch[is_chase_base] = 1)", "[Chases]", 1), "0.0%", ""),
    ("6 Match", "Avg First Innings vs Season",
     "AVERAGEX(FILTER(FactMatch, FactMatch[is_full_match] = 1), FactMatch[inn1_runs] - "
     "CALCULATE(AVERAGE(FactMatch[inn1_runs]), ALLEXCEPT(FactMatch, FactMatch[season_year]), FactMatch[is_full_match] = 1))",
     "+0.0;-0.0;0.0", "Average of (first-innings score - that season's league average), full matches."),
    ("6 Match", "Venue Qualifies", "IF([Full Matches] >= 20 && [Decided Matches] >= 20, 1)", "0", "1 when the venue has 20+ full and 20+ decided matches."),
    ("6 Match", "Venue Full Matches (min 20)", "IF([Venue Qualifies] = 1, [Full Matches])", "#,0", ""),
    ("6 Match", "Venue Avg First Innings (min 20)", "IF([Venue Qualifies] = 1, [Avg First Innings])", "0.0", ""),
    ("6 Match", "Venue vs Season (min 20)", "IF([Venue Qualifies] = 1, [Avg First Innings vs Season])", "+0.0;-0.0;0.0", ""),
    ("6 Match", "Venue Chase Win % (min 20)", "IF([Venue Qualifies] = 1, [Chasing Win %])", "0.0%", ""),
    ("6 Match", "Toss Matches", "CALCULATE(COUNTROWS(FactMatch), FactMatch[is_no_result] = 0)", "#,0", ""),
]


def measures_tmdl():
    out = []
    for folder, name, expr, fmt, desc in MEASURES:
        if desc:
            out.append(f"\t/// {desc}")
        out.append(f"\tmeasure {q(name)} = {expr}")
        if fmt:
            out.append(f"\t\tformatString: {fmt}")
        out.append(f"\t\tdisplayFolder: {folder}")
        out.append(f"\t\tlineageTag: {lt('m.' + name)}")
        out.append("")
    return "\n".join(out)


RELS = [  # (from table, from column display, to table, to column display, active)
    ("FactDelivery", "season_year", "DimSeason", "Season", True), ("FactBattingInnings", "season_year", "DimSeason", "Season", True),
    ("FactTeamMatch", "season_year", "DimSeason", "Season", True), ("FactMatch", "season_year", "DimSeason", "Season", True),
    ("FactDelivery", "venue_key", "DimVenue", "venue_key", True), ("FactBattingInnings", "venue_key", "DimVenue", "venue_key", True),
    ("FactTeamMatch", "venue_key", "DimVenue", "venue_key", True), ("FactMatch", "venue_key", "DimVenue", "venue_key", True),
    ("FactTeamMatch", "team_key", "DimTeam", "team_key", True), ("FactBattingInnings", "team_key", "DimTeam", "team_key", True),
    ("FactDelivery", "batting_team_key", "DimTeam", "team_key", True), ("FactDelivery", "bowling_team_key", "DimTeam", "team_key", False),
    ("FactDelivery", "batter_key", "DimPlayer", "player_key", True), ("FactDelivery", "bowler_key", "DimPlayer", "player_key", False),
    ("FactBattingInnings", "player_key", "DimPlayer", "player_key", True),
    ("FactDelivery", "phase", "DimPhase", "Phase", True),
]


def build_model():
    tables = {}
    for t in ["DimSeason", "DimTeam", "DimVenue", "DimPlayer", "DimPhase", "FactMatch", "FactTeamMatch", "FactBattingInnings", "FactDelivery"]:
        df = pd.read_csv(cfg.FINAL_DIR / "powerbi" / f"{t}.csv", nrows=50000)
        tables[t] = df
    (SM / "definition" / "tables").mkdir(parents=True, exist_ok=True)
    for t, df in tables.items():
        write(SM / "definition" / "tables" / f"{t}.tmdl", table_tmdl(t, f"{t}.csv", df))
    # disconnected player tables for the comparison
    for w in "AB":
        name = f"Player {w}"
        pdf = pd.DataFrame({"player": ["x"]})
        txt = table_tmdl(name, "DimPlayer.csv", pdf, rename={"player": name}).replace(
            "Selected = Table.SelectColumns(Promoted, {\"player\"})", "Selected = Table.SelectColumns(Promoted, {\"player\"})")
        txt = txt.replace("\t\tisHidden\n", "")
        write(SM / "definition" / "tables" / f"{name}.tmdl", txt)
    # measures table
    mt = [f"/// All dashboard measures. Definitions follow documentation/transformation_log.md and Phase 3-5 reports.",
          "table _Measures", f"\tlineageTag: {lt('_Measures')}", "", measures_tmdl(),
          "\tcolumn Placeholder", "\t\tdataType: int64", "\t\tisHidden", f"\t\tlineageTag: {lt('_Measures.Placeholder')}",
          "\t\tsummarizeBy: none", "\t\tsourceColumn: Placeholder", "",
          "\tpartition _Measures = m", "\t\tmode: import", "\t\tsource =", "\t\t\t\tlet",
          "\t\t\t\t    Source = #table(type table [Placeholder = Int64.Type], {})", "\t\t\t\tin", "\t\t\t\t    Source", "",
          "\tannotation PBI_ResultType = Table"]
    write(SM / "definition" / "tables" / "_Measures.tmdl", "\n".join(mt) + "\n")
    disp = lambda t, c: DISPLAY.get(t, {}).get(c, c)  # noqa: E731
    rel = []
    for ft, fc, tt, tc, active in RELS:
        rel.append(f"relationship {lt('rel.' + ft + fc + tt)}")
        if not active:
            rel.append("\tisActive: false")
        rel.append(f"\tfromColumn: {q(ft)}.{q(disp(ft, fc))}")
        rel.append(f"\ttoColumn: {q(tt)}.{q(tc)}")
        rel.append("")
    write(SM / "definition" / "relationships.tmdl", "\n".join(rel))
    refs = "\n".join(f"ref table {q(t)}" for t in ["_Measures"] + list(tables) + ["Player A", "Player B"])
    write(SM / "definition" / "model.tmdl",
          "model Model\n\tculture: en-US\n\tdefaultPowerBIDataSourceVersion: powerBI_V3\n\tdiscourageImplicitMeasures\n"
          "\tsourceQueryCulture: en-US\n\tdataAccessOptions\n\t\tlegacyRedirects\n\t\treturnErrorValuesAsNull\n\n"
          "annotation __PBI_TimeIntelligenceEnabled = 0\n\n" + refs + "\n")
    write(SM / "definition" / "database.tmdl", "database\n\tcompatibilityLevel: 1601\n")
    write(SM / "definition" / "expressions.tmdl",
          f'/// Folder holding the validated CSV extracts (python/06b_export_powerbi_model.py). Change it if the project moves.\n'
          f'expression DataFolder = "{DATA}" meta [IsParameterQuery=true, Type="Text", IsParameterQueryRequired=true]\n'
          f'\tlineageTag: {lt("DataFolder")}\n\n\tannotation PBI_ResultType = Text\n')
    wjson(SM / "definition.pbism", {"version": "4.1", "settings": {}})
    return tables


# ================================================================== REPORT (PBIR)
SCHEMA = "https://developer.microsoft.com/json-schemas/fabric/item/report/definition"


def lit(v):
    return {"expr": {"Literal": {"Value": v}}}


def color(hexv):
    return {"solid": {"color": lit(f"'{hexv}'")}}


def fld(entity, prop, measure=False):
    kind = "Measure" if measure else "Column"
    return {kind: {"Expression": {"SourceRef": {"Entity": entity}}, "Property": prop}}


def M(name):
    return ("_Measures", name, True)


def proj(spec, active=None, display=None):
    ent, prop, is_m = spec[:3]
    display = display or (spec[3] if len(spec) > 3 else None)
    p = {"field": fld(ent, prop, is_m), "queryRef": f"{ent}.{prop}", "nativeQueryRef": prop}
    if display:
        p["displayName"] = display
    if active is not None:
        p["active"] = active
    return p


def MD(name, display):  # measure with a visual-level display name
    return ("_Measures", name, True, display)


NO_UNITS = lit("1D")  # display units: none (show 347,470 not 347K)
NO_TOTALS = {"total": [{"properties": {"totals": lit("false")}}]}
NO_SUBTOTALS = {"subTotals": [{"properties": {"rowSubtotals": lit("false"), "columnSubtotals": lit("false")}}]}


def default_selection(entity, prop, value):
    return {"general": [{"properties": {"filter": {"filter": {
        "Version": 2, "From": [{"Name": "p", "Entity": entity, "Type": 0}],
        "Where": [{"Condition": {"In": {"Expressions": [{"Column": {"Expression": {"SourceRef": {"Source": "p"}}, "Property": prop}}],
                                        "Values": [[{"Literal": {"Value": f"'{value}'"}}]]}}}]}}}}]}


class Page:
    def __init__(self, name, display, hidden=False):
        self.name, self.display, self.hidden, self.visuals, self.z = name, display, hidden, [], 0
        self.filter_config, self.page_binding = None, None

    def add(self, vname, x, y, w, h, visual):
        self.z += 1
        self.visuals.append({"$schema": f"{SCHEMA}/visualContainer/2.0.0/schema.json", "name": vname,
                             "position": {"x": x, "y": y, "z": self.z * 100, "height": h, "width": w, "tabOrder": self.z * 100},
                             "visual": visual})


def container_objects(title=None, show_bg=True, subtitle=None):
    o = {"title": [{"properties": {"show": lit("true" if title else "false")}}]}
    if title:
        o["title"][0]["properties"].update({"text": lit(f"'{title}'"), "fontColor": color(C["text"]), "fontSize": lit("11D")})
    if subtitle:
        o["subTitle"] = [{"properties": {"show": lit("true"), "text": lit(f"'{subtitle}'"), "fontColor": color(C["muted"]),
                                         "fontSize": lit("8D")}}]
    if not show_bg:
        o["background"] = [{"properties": {"show": lit("false")}}]
        o["border"] = [{"properties": {"show": lit("false")}}]
        o["dropShadow"] = [{"properties": {"show": lit("false")}}]
    return o


def textbox(runs):
    paras = []
    for text, size, col, bold in runs:
        style = {"fontSize": f"{size}pt", "color": col, "fontFamily": "Segoe UI Semibold" if bold else "Segoe UI"}
        if bold:
            style["fontWeight"] = "bold"
        paras.append({"textRuns": [{"value": text, "textStyle": style}]})
    return {"visualType": "textbox", "objects": {"general": [{"properties": {"paragraphs": paras}}]},
            "visualContainerObjects": container_objects(show_bg=False)}


def card(measure, label, highlight=False):
    return {"visualType": "card",
            "query": {"queryState": {"Values": {"projections": [proj(M(measure))]}}},
            "objects": {"labels": [{"properties": {"color": color(C["coral"] if highlight else C["text"]), "fontSize": lit("22D"),
                                                   "fontFamily": lit("'Segoe UI Semibold'"), "labelDisplayUnits": NO_UNITS}}],
                        "categoryLabels": [{"properties": {"show": lit("true"), "color": color(C["muted"]), "fontSize": lit("9D")}}]},
            "visualContainerObjects": container_objects(subtitle=None) | {
                "title": [{"properties": {"show": lit("false")}}]},
            "drillFilterOtherVisuals": True} | ({"_label": label} if False else {})


def slicer(spec, title, mode="Dropdown", single=False, default=None):
    v = {"visualType": "slicer",
         "query": {"queryState": {"Values": {"projections": [proj(spec, True)]}}},
         "objects": {"data": [{"properties": {"mode": lit(f"'{mode}'")}}],
                     "header": [{"properties": {"show": lit("true"), "text": lit(f"'{title}'"), "fontColor": color(C["muted"]),
                                                "fontSize": lit("9D")}}],
                     "items": [{"properties": {"fontColor": color(C["text"]), "background": color(C["card"]), "fontSize": lit("10D")}}]},
         "visualContainerObjects": container_objects(),
         "drillFilterOtherVisuals": True}
    if single:
        v["objects"]["selection"] = [{"properties": {"singleSelect": lit("true"), "strictSingleSelect": lit("true")}}]
    if default:
        v["objects"].update(default_selection(spec[0], spec[1], default))
    return v


def chart(vtype, roles, title, sort=None, series_colors=None, subtitle=None, labels=False, extra_objects=None,
          categorical=False, point_labels=False):
    qs = {}
    for role, specs in roles.items():
        qs[role] = {"projections": [proj(s, True if role in ("Category", "Rows") and i == 0 else None) for i, s in enumerate(specs)]}
    v = {"visualType": vtype, "query": {"queryState": qs}, "visualContainerObjects": container_objects(title, subtitle=subtitle),
         "drillFilterOtherVisuals": True}
    if sort:
        spec, direction = sort
        v["query"]["sortDefinition"] = {"sort": [{"field": fld(*spec), "direction": direction}]}
    objs = {}
    if series_colors:
        objs["dataPoint"] = [{"properties": {"fill": color(col)}, "selector": {"metadata": f"{s[0]}.{s[1]}"}} for s, col in series_colors]
    if labels:
        objs["labels"] = [{"properties": {"show": lit("true"), "color": color(C["text"]), "fontSize": lit("8D"),
                                          "labelDisplayUnits": NO_UNITS}}]
    if categorical:
        objs["categoryAxis"] = [{"properties": {"axisType": lit("'Categorical'")}}]
    if point_labels:
        objs["categoryLabels"] = [{"properties": {"show": lit("true"), "color": color(C["text"]), "fontSize": lit("7D")}}]
    if extra_objects:
        objs.update(extra_objects)
    if objs:
        v["objects"] = objs
    return v


def gradient_rule(measure_spec, low, mid, high, prop_name="backColor", two_stop=False):
    ent, prop = measure_spec[0], measure_spec[1]
    if two_stop:
        rule = {"linearGradient2": {"min": {"color": {"Literal": {"Value": f"'{low}'"}}},
                                    "max": {"color": {"Literal": {"Value": f"'{high}'"}}},
                                    "nullColoringStrategy": {"strategy": {"Literal": {"Value": "'noColor'"}}}}}
        return {prop_name: {"solid": {"color": {"expr": {"FillRule": {"Input": fld(ent, prop, True), "FillRule": rule}}}}}}
    return {prop_name: {"solid": {"color": {"expr": {"FillRule": {
        "Input": fld(ent, prop, True),
        "FillRule": {"linearGradient3": {
            "min": {"color": {"Literal": {"Value": f"'{low}'"}}},
            "mid": {"color": {"Literal": {"Value": f"'{mid}'"}}, "value": {"Literal": {"Value": "0D"}}},
            "max": {"color": {"Literal": {"Value": f"'{high}'"}}},
            "nullColoringStrategy": {"strategy": {"Literal": {"Value": "'noColor'"}}}}}}}}}}}


# layout constants (1280 x 720 canvas)
X0, W_FULL, GAP = 24, 1232, 12


def header(page, title, subtitle):
    page.add("title", X0 - 6, 4, 650, 42, textbox([(title, 16, C["text"], True)]))
    page.add("subtitle", X0 - 6, 42, 664, 34, textbox([(subtitle, 8, C["muted"], False)]))


def slicer_row(page, slicers):
    n = len(slicers)
    w = (560 - (n - 1) * 8) / n
    for i, s in enumerate(slicers):
        vname, spec, title, mode, single = s[:5]
        default = s[5] if len(s) > 5 else None
        page.add(vname, 696 + i * (w + 8), 12, w, 60, slicer(spec, title, mode, single, default))


def kpi_row(page, kpis, y=82, h=70):
    n = len(kpis)
    w = (W_FULL - (n - 1) * GAP) / n
    for i, (measure, label, hl) in enumerate(kpis):
        v = card(measure, label, hl)
        v["visualContainerObjects"]["title"] = [{"properties": {"show": lit("true"), "text": lit(f"'{label}'"),
                                                               "fontColor": color(C["muted"]), "fontSize": lit("9D")}}]
        v["objects"]["categoryLabels"] = [{"properties": {"show": lit("false")}}]
        page.add(f"kpi_{i}", X0 + i * (w + GAP), y, w, h, v)


SEASON = ("DimSeason", "Season", False)
TEAM = ("DimTeam", "Franchise", False)
VENUE = ("DimVenue", "Venue", False)
PLAYER = ("DimPlayer", "Player", False)
PHASE = ("DimPhase", "Phase", False)


def page_overview():
    p = Page("overview", "IPL overview")
    header(p, "IPL overview, 2008-2024", "Regulation balls only (super overs excluded). Wickets are bowler-credited. Observed patterns, not causes.")
    slicer_row(p, [("sl_season", SEASON, "Season", "Between", False), ("sl_venue", VENUE, "Venue", "Dropdown", False)])
    kpi_row(p, [("Matches", "Matches", False), ("Seasons", "Seasons", False), ("Total Runs", "Total runs", False),
                ("Bowler Wickets", "Bowler wickets (excl. run outs)", False), ("Avg First Innings", "Avg 1st-innings score", False),
                ("Run Rate", "Runs per over", True)])
    top, h = 164, 264
    p.add("rr_phase", X0, top, 740, h, chart(
        "lineChart", {"Category": [SEASON], "Y": [MD("Run Rate Powerplay", "Powerplay"), MD("Run Rate Middle", "Middle"),
                                                  MD("Run Rate Death", "Death"), MD("Run Rate", "All overs")]},
        "Runs per over by season and phase", sort=(SEASON, "Ascending"), categorical=True,
        series_colors=[(M("Run Rate Powerplay"), PHASE_COL["Powerplay"]), (M("Run Rate Middle"), PHASE_COL["Middle"]),
                       (M("Run Rate Death"), PHASE_COL["Death"]), (M("Run Rate"), C["coral"])],
        subtitle="Powerplay overs 1-6, middle 7-15, death 16-20; all overs in coral"))
    p.add("first_inn", X0 + 752, top, 480, h, chart(
        "clusteredColumnChart", {"Category": [SEASON], "Y": [MD("Avg First Innings", "Avg 1st-innings score")],
                                 "Tooltips": [M("Full Matches"), M("Avg First Innings vs Previous Season")]},
        "Average first-innings score by season", sort=(SEASON, "Ascending"), categorical=True,
        subtitle="Full 20-over matches only; hover for change vs previous season"))
    top2 = top + h + GAP
    h2 = 720 - top2 - 14
    p.add("wins", X0, top2, 740, h2, chart(
        "clusteredBarChart", {"Category": [TEAM], "Y": [M("Wins")], "Tooltips": [M("Win %"), M("Team Seasons"), M("Titles")]},
        "Wins by franchise", sort=(M("Wins"), "Descending"), labels=True,
        subtitle="Totals favour long-serving franchises; hover for win %, seasons and titles"))
    p.add("bf_chase", X0 + 752, top2, 480, h2, chart(
        "clusteredColumnChart", {"Category": [SEASON], "Y": [MD("Chasing Win %", "Chasing"), MD("Batting First Win %", "Batting first")]},
        "Batting first vs chasing: win % by season", sort=(SEASON, "Ascending"), categorical=True,
        series_colors=[(M("Chasing Win %"), C["pink"]), (M("Batting First Win %"), C["text"])],
        subtitle="Decided matches; uses approved result_for"))
    return p


def page_players():
    p = Page("players", "Player performance")
    header(p, "Player performance", "Thresholds: average 50+ innings, strike rate 500+ balls, bowling 1,000+ balls. Right-click a player to drill through.")
    slicer_row(p, [("sl_season", SEASON, "Season", "Dropdown", False), ("sl_team", TEAM, "Franchise", "Dropdown", False),
                   ("sl_pa", ("Player A", "Player A", False), "Player A", "Dropdown", True, "V Kohli"),
                   ("sl_pb", ("Player B", "Player B", False), "Player B", "Dropdown", True, "RG Sharma")])
    top, h, w4 = 84, 296, (W_FULL - 3 * GAP) / 4
    p.add("top_runs", X0, top, w4, h, chart("clusteredBarChart", {"Category": [PLAYER], "Y": [MD("Top 10 Run Scorers", "Runs")],
                                                                  "Tooltips": [M("Innings"), M("Batting Average"), M("Strike Rate")]},
                                            "Top 10 run scorers", sort=(M("Top 10 Run Scorers"), "Descending"), labels=True,
                                            subtitle="Runs off the bat"))
    p.add("top_wkts", X0 + (w4 + GAP), top, w4, h, chart("clusteredBarChart", {"Category": [PLAYER], "Y": [MD("Top 10 Wicket Takers", "Wickets")],
                                                                              "Tooltips": [M("Economy"), M("Bowling Average")]},
                                                        "Top 10 wicket takers", sort=(M("Top 10 Wicket Takers"), "Descending"), labels=True,
                                                        subtitle="Bowler-credited wickets"))
    for i, who in enumerate("AB"):
        p.add(f"card_{who}", X0 + 2 * (w4 + GAP), top + i * (h / 2 + 4), w4, h / 2 - 4, {
            "visualType": "multiRowCard",
            "query": {"queryState": {"Values": {"projections": [proj(MD(f"Player {who} {k}", lab)) for k, lab in
                                                                [("Name", "Player"), ("Runs", "Runs"), ("Average", "Average"),
                                                                 ("Strike Rate", "Strike rate"), ("Wickets", "Wickets"), ("Economy", "Economy")]]}}},
            "objects": {"dataLabels": [{"properties": {"color": color(C["pink"] if who == "A" else C["text"]), "fontSize": lit("11D")}}],
                        "categoryLabels": [{"properties": {"color": color(C["muted"]), "fontSize": lit("8D")}}],
                        "card": [{"properties": {"outline": lit("'None'"), "barShow": lit("true"),
                                                 "barColor": color(C["pink"] if who == "A" else C["text"])}}]},
            "visualContainerObjects": container_objects(f"Player {who}"), "drillFilterOtherVisuals": True})
    p.add("cmp_phase", X0 + 3 * (w4 + GAP), top, w4, h, chart(
        "clusteredBarChart", {"Category": [PHASE], "Y": [MD("Player A Phase SR", "Player A"), MD("Player B Phase SR", "Player B")]},
        "Strike rate by phase: A vs B", series_colors=[(M("Player A Phase SR"), C["pink"]), (M("Player B Phase SR"), C["text"])],
        sort=(PHASE, "Ascending"), labels=True, subtitle="Ball-level strike rate, regulation balls"))
    top2 = top + h + GAP
    h2 = 720 - top2 - 14
    wt = 478
    bat_cols = [("Q Innings", "Innings"), ("Bat Runs", "Runs"), ("Q Batting Average", "Average"), ("Q Strike Rate", "Strike rate"),
                ("Q 30+ Rate", "30+ %"), ("Bat Sixes", "Sixes")]
    p.add("bat_table", X0, top2, wt, h2, {
        "visualType": "tableEx",
        "query": {"queryState": {"Values": {"projections": [proj(PLAYER)] + [proj(MD(m, d)) for m, d in bat_cols]}},
                  "sortDefinition": {"sort": [{"field": fld("_Measures", "Q Batting Average", True), "direction": "Descending"}]}},
        "objects": dict(NO_TOTALS),
        "visualContainerObjects": container_objects("Batting leaders (50+ innings)", subtitle="Sorted by average; strike rate blank below 500 balls"),
        "drillFilterOtherVisuals": True})
    bowl_cols = [("Q Legal Balls", "Legal balls"), ("Q Wickets", "Wickets"), ("Q Economy", "Economy"), ("Q Bowling Average", "Average"),
                 ("Q Bowling Strike Rate", "Strike rate"), ("Q Dot %", "Dot %")]
    p.add("bowl_table", X0 + wt + GAP, top2, wt, h2, {
        "visualType": "tableEx",
        "query": {"queryState": {"Values": {"projections": [proj(PLAYER)] + [proj(MD(m, d)) for m, d in bowl_cols]}},
                  "sortDefinition": {"sort": [{"field": fld("_Measures", "Q Economy", True), "direction": "Ascending"}]}},
        "objects": dict(NO_TOTALS),
        "visualContainerObjects": container_objects("Bowling leaders (1,000+ legal balls)", subtitle="Sorted by economy"),
        "drillFilterOtherVisuals": True})
    p.add("avg_sr", X0 + 2 * (wt + GAP), top2, W_FULL - 2 * (wt + GAP), h2, chart(
        "scatterChart", {"Category": [PLAYER], "X": [MD("Q Batting Average", "Average")], "Y": [MD("Q Strike Rate", "Strike rate")]},
        "Average vs strike rate", subtitle="Batters meeting both thresholds"))
    return p


def page_match():
    p = Page("match", "Match and team insights")
    header(p, "Match and team insights", "Associations, not causes. Adjusted = vs league in the same seasons and phases. Chases: full 20-over, non-D/L.")
    slicer_row(p, [("sl_season", SEASON, "Season", "Between", False), ("sl_venue", VENUE, "Venue", "Dropdown", False)])
    kpi_row(p, [("Toss Winner Win %", "Toss winner won", False), ("Toss Winner Win % (chose field)", "Won after choosing to field", False),
                ("Toss Winner Win % (chose bat)", "Won after choosing to bat", False), ("Chasing Win %", "Chasing side won", True),
                ("Close Match %", "Close matches", False)])
    top, h, w3 = 164, 264, (W_FULL - 2 * GAP) / 3
    p.add("strength", X0, top, w3, h, chart(
        "scatterChart", {"Category": [TEAM], "X": [MD("Team Batting vs League", "Batting vs league")],
                         "Y": [MD("Team Runs Saved vs League", "Bowling: runs saved vs league")],
                         "Tooltips": [M("Win %"), M("Team Net vs League")]},
        "Team batting vs bowling strength", point_labels=True,
        subtitle="Runs/over vs league, same seasons and phases; top-right = better at both"))
    p.add("chase_target", X0 + w3 + GAP, top, w3, h, chart(
        "clusteredColumnChart", {"Category": [("FactMatch", "First-innings band", False)], "Y": [MD("Chase Success %", "Chase success")],
                                 "Tooltips": [M("Chases"), M("Chase Success CI Low"), M("Chase Success CI High")]},
        "Chase success by first-innings score", sort=(("FactMatch", "First-innings band", False), "Ascending"), labels=True,
        subtitle="Hover for number of chases and 95% interval"))
    p.add("wkts_rr", X0 + 2 * (w3 + GAP), top, w3, h, {
        "visualType": "pivotTable",
        "query": {"queryState": {"Rows": {"projections": [proj(("FactDelivery", "Wickets lost before ball", False), True, "Wickets lost")]},
                                 "Columns": {"projections": [proj(PHASE, True)]},
                                 "Values": {"projections": [proj(MD("Run Rate", "Runs per over"))]}}},
        "objects": {**NO_SUBTOTALS,
                    "values": [{"properties": gradient_rule(M("Run Rate"), C["card"], None, C["purple"], two_stop=True),
                                "selector": {"data": [{"dataViewWildcard": {"matchingOption": 1}}], "metadata": "_Measures.Run Rate"}}]},
        "visualContainerObjects": container_objects("Runs per over by wickets already lost", subtitle="Compare within each phase column"),
        "drillFilterOtherVisuals": True})
    top2 = top + h + GAP
    h2 = 720 - top2 - 14
    wtp, wv = 360, 500
    p.add("team_phase", X0, top2, wtp, h2, {
        "visualType": "pivotTable",
        "query": {"queryState": {"Rows": {"projections": [proj(TEAM, True)]}, "Columns": {"projections": [proj(PHASE, True)]},
                                 "Values": {"projections": [proj(MD("Team Batting vs League", "vs league"))]}}},
        "objects": {**NO_SUBTOTALS,
                    "values": [{"properties": gradient_rule(M("Team Batting vs League"), C["coral"], C["muted"], C["text"], prop_name="fontColor"),
                                "selector": {"data": [{"dataViewWildcard": {"matchingOption": 1}}],
                                             "metadata": "_Measures.Team Batting vs League"}}]},
        "visualContainerObjects": container_objects("Team batting by phase vs league", subtitle="Runs/over above (+, light) or below (-, coral) league"),
        "drillFilterOtherVisuals": True})
    venue_cols = [("Venue Full Matches (min 20)", "Matches"), ("Venue Avg First Innings (min 20)", "Avg 1st inns"),
                  ("Venue vs Season (min 20)", "vs season"), ("Venue Chase Win % (min 20)", "Chase win %")]
    p.add("venues", X0 + wtp + GAP, top2, wv, h2, {
        "visualType": "tableEx",
        "query": {"queryState": {"Values": {"projections": [proj(VENUE)] + [proj(MD(m, d)) for m, d in venue_cols]}},
                  "sortDefinition": {"sort": [{"field": fld("_Measures", "Venue vs Season (min 20)", True), "direction": "Descending"}]}},
        "objects": dict(NO_TOTALS),
        "visualContainerObjects": container_objects("Venues (20+ matches)", subtitle="vs season = first-innings score vs that season average"),
        "drillFilterOtherVisuals": True})
    p.add("close", X0 + wtp + wv + 2 * GAP, top2, W_FULL - wtp - wv - 2 * GAP, h2, chart(
        "clusteredBarChart", {"Category": [TEAM], "Y": [MD("Close Match Win % (min 20)", "Close-match win %")],
                              "Tooltips": [M("Close Matches (Team)")]},
        "Close-match win % by franchise", sort=(M("Close Match Win % (min 20)"), "Descending"), labels=True,
        subtitle="Teams with 20+ close matches; Phase 5 found no significant difference between teams"))
    return p


def page_player_detail():
    p = Page("player_detail", "Player detail", hidden=True)
    header(p, "Player detail", "Drill-through page: right-click a player on 'Player performance' and choose Drill through. "
                               "All other filters are kept.")
    kpi_row(p, [("Innings", "Innings", False), ("Bat Runs", "Runs", True), ("Batting Average", "Average", False),
                ("Strike Rate", "Strike rate", False), ("Bowl Wickets", "Wickets", False), ("Economy", "Economy", False)])
    top, h = 162, 540
    w2 = (W_FULL - GAP) / 2
    p.add("runs_season", X0, top, w2, h / 2 - 6, chart("clusteredColumnChart", {"Category": [SEASON], "Y": [M("Bat Runs")]},
                                                      "Runs by season", sort=(SEASON, "Ascending"), labels=True))
    p.add("sr_phase", X0 + w2 + GAP, top, w2, h / 2 - 6, chart("clusteredBarChart", {"Category": [PHASE], "Y": [M("Batter SR (balls)")]},
                                                             "Strike rate by phase", sort=(PHASE, "Ascending"), labels=True))
    p.add("wkts_season", X0, top + h / 2 + 6, w2, h / 2 - 6, chart("clusteredColumnChart", {"Category": [SEASON], "Y": [M("Bowl Wickets")]},
                                                                  "Bowler wickets by season", sort=(SEASON, "Ascending"), labels=True))
    p.add("econ_season", X0 + w2 + GAP, top + h / 2 + 6, w2, h / 2 - 6, chart("lineChart", {"Category": [SEASON], "Y": [M("Economy")]},
                                                                            "Economy by season", sort=(SEASON, "Ascending")))
    flt = {"name": "PlayerDrill", "field": fld("DimPlayer", "Player"), "type": "Categorical", "howCreated": "Drillthrough"}
    p.filter_config = {"filters": [flt]}
    p.page_binding = {"name": "PlayerDrillBinding", "type": "Drillthrough", "parameters": [
        {"name": "Param_PlayerDrill", "boundFilter": "PlayerDrill", "fieldExpr": fld("DimPlayer", "Player")}]}
    return p


THEME = {
    "name": "IPL Dark (project palette)",
    "dataColors": [C["pink"], C["text"], C["mid"], C["context"], C["coral"], C["purple"], C["muted"], "#C24A82"],
    "background": C["bg"], "foreground": C["text"], "tableAccent": C["pink"],
    "good": C["text"], "neutral": C["muted"], "bad": C["coral"], "maximum": C["pink"], "center": C["card"], "minimum": C["coral"],
    "textClasses": {
        "callout": {"fontFace": "Segoe UI Semibold", "fontSize": 22, "color": C["text"]},
        "title": {"fontFace": "Segoe UI Semibold", "fontSize": 11, "color": C["text"]},
        "header": {"fontFace": "Segoe UI Semibold", "fontSize": 12, "color": C["text"]},
        "label": {"fontFace": "Segoe UI", "fontSize": 9, "color": C["text"]},
        "largeTitle": {"fontFace": "Segoe UI Semibold", "fontSize": 20, "color": C["text"]},
    },
    "visualStyles": {
        "*": {"*": {
            "background": [{"show": True, "color": {"solid": {"color": C["card"]}}, "transparency": 0}],
            "border": [{"show": True, "color": {"solid": {"color": C["purple"]}}, "radius": 10}],
            "dropShadow": [{"show": True, "color": {"solid": {"color": "#000000"}}, "position": "Outer", "preset": "Custom",
                            "shadowSpread": 0, "shadowBlur": 6, "shadowDistance": 2, "transparency": 75}],
            "title": [{"show": True, "fontColor": {"solid": {"color": C["text"]}}, "fontSize": 11, "fontFamily": "Segoe UI Semibold"}],
            "subTitle": [{"fontColor": {"solid": {"color": C["muted"]}}, "fontSize": 8}],
            "visualHeader": [{"show": True, "foreground": {"solid": {"color": C["muted"]}}, "background": {"solid": {"color": C["card"]}},
                              "transparency": 0}],
            "padding": [{"top": 8, "bottom": 8, "left": 10, "right": 10}],
            "categoryAxis": [{"labelColor": {"solid": {"color": C["muted"]}}, "fontSize": 8, "showAxisTitle": False,
                              "gridlineShow": False}],
            "valueAxis": [{"labelColor": {"solid": {"color": C["muted"]}}, "fontSize": 8, "showAxisTitle": False,
                           "gridlineColor": {"solid": {"color": C["grid"]}}, "gridlineStyle": "dotted"}],
            "legend": [{"show": True, "position": "Top", "labelColor": {"solid": {"color": C["text"]}}, "fontSize": 8}],
            "labels": [{"color": {"solid": {"color": C["text"]}}, "fontSize": 8}],
            "tooltip": [{"background": {"solid": {"color": C["bg"]}}, "valueFontColor": {"solid": {"color": C["text"]}},
                         "titleFontColor": {"solid": {"color": C["muted"]}}}],
        }},
        "page": {"*": {"background": [{"color": {"solid": {"color": C["bg"]}}, "transparency": 0}],
                       "outspace": [{"color": {"solid": {"color": C["bg"]}}, "transparency": 0}]}},
        "textbox": {"*": {"background": [{"show": False}], "border": [{"show": False}], "dropShadow": [{"show": False}],
                          "visualHeader": [{"show": False}]}},
        "card": {"*": {"labels": [{"color": {"solid": {"color": C["text"]}}, "fontSize": 22}],
                       "categoryLabels": [{"color": {"solid": {"color": C["muted"]}}}]}},
        "slicer": {"*": {"background": [{"show": True, "color": {"solid": {"color": C["card"]}}}],
                         "items": [{"fontColor": {"solid": {"color": C["text"]}}, "background": {"solid": {"color": C["card"]}}}],
                         "header": [{"fontColor": {"solid": {"color": C["muted"]}}}],
                         "numericInputStyle": [{"fontColor": {"solid": {"color": C["text"]}}, "background": {"solid": {"color": C["bg"]}}}],
                         "slider": [{"color": {"solid": {"color": C["pink"]}}}]}},
        "tableEx": {"*": {"columnHeaders": [{"fontColor": {"solid": {"color": C["text"]}}, "backColor": {"solid": {"color": C["purple"]}},
                                             "fontSize": 8}],
                          "values": [{"fontColorPrimary": {"solid": {"color": C["text"]}}, "backColorPrimary": {"solid": {"color": C["card"]}},
                                      "fontColorSecondary": {"solid": {"color": C["text"]}}, "backColorSecondary": {"solid": {"color": C["row_alt"]}},
                                      "fontSize": 8}],
                          "grid": [{"gridHorizontalColor": {"solid": {"color": C["grid"]}}, "outlineColor": {"solid": {"color": C["purple"]}}}]}},
        "pivotTable": {"*": {"columnHeaders": [{"fontColor": {"solid": {"color": C["text"]}}, "backColor": {"solid": {"color": C["purple"]}}}],
                             "rowHeaders": [{"fontColor": {"solid": {"color": C["text"]}}, "backColor": {"solid": {"color": C["card"]}}}],
                             "values": [{"fontColorPrimary": {"solid": {"color": C["text"]}}, "backColorPrimary": {"solid": {"color": C["card"]}},
                                         "fontColorSecondary": {"solid": {"color": C["text"]}}, "backColorSecondary": {"solid": {"color": C["card"]}}}],
                             "grid": [{"gridHorizontalColor": {"solid": {"color": C["grid"]}}, "gridVerticalColor": {"solid": {"color": C["grid"]}}}]}},
        "multiRowCard": {"*": {"dataLabels": [{"color": {"solid": {"color": C["text"]}}}],
                               "categoryLabels": [{"color": {"solid": {"color": C["muted"]}}}],
                               "card": [{"background": {"solid": {"color": C["card"]}}}]}},
    },
}


def build_report():
    pages = [page_overview(), page_players(), page_match(), page_player_detail()]
    d = RP / "definition"
    wjson(RP / "definition.pbir", {"$schema": f"https://developer.microsoft.com/json-schemas/fabric/item/report/definitionProperties/2.0.0/schema.json",
                                   "version": "4.0", "datasetReference": {"byPath": {"path": f"../{NAME}.SemanticModel"}}})
    wjson(d / "version.json", {"$schema": f"{SCHEMA}/versionMetadata/1.0.0/schema.json", "version": "2.0.0"})
    wjson(RP / "StaticResources" / "RegisteredResources" / "IPL_Dark_Theme.json", THEME)
    wjson(d / "report.json", {
        "$schema": f"{SCHEMA}/report/1.3.0/schema.json",
        "themeCollection": {"baseTheme": {"name": "CY24SU10", "reportVersionAtImport": "5.61", "type": "SharedResources"},
                            "customTheme": {"name": "IPL_Dark_Theme.json", "reportVersionAtImport": "5.61", "type": "RegisteredResources"}},
        "layoutOptimization": "None",
        "resourcePackages": [
            {"name": "SharedResources", "type": "SharedResources",
             "items": [{"name": "CY24SU10", "path": "BaseThemes/CY24SU10.json", "type": "BaseTheme"}]},
            {"name": "RegisteredResources", "type": "RegisteredResources",
             "items": [{"name": "IPL_Dark_Theme.json", "path": "IPL_Dark_Theme.json", "type": "CustomTheme"}]}],
        "settings": {"useStylableVisualContainerHeader": True, "exportDataMode": "AllowSummarized",
                     "defaultDrillFilterOtherVisuals": True, "allowChangeFilterTypes": True, "useEnhancedTooltips": True}})
    wjson(d / "pages" / "pages.json", {"$schema": f"{SCHEMA}/pagesMetadata/1.0.0/schema.json",
                                       "pageOrder": [p.name for p in pages], "activePageName": pages[0].name})
    for p in pages:
        pj = {"$schema": f"{SCHEMA}/page/1.4.0/schema.json", "name": p.name, "displayName": p.display,
              "displayOption": "FitToPage", "height": 720, "width": 1280,
              "objects": {"background": [{"properties": {"color": color(C["bg"]), "transparency": lit("0D")}}],
                          "outspace": [{"properties": {"color": color(C["bg"]), "transparency": lit("0D")}}]}}
        if p.hidden:
            pj["visibility"] = "HiddenInViewMode"
        if p.filter_config:
            pj["filterConfig"] = p.filter_config
        if p.page_binding:
            pj["pageBinding"] = p.page_binding
        wjson(d / "pages" / p.name / "page.json", pj)
        for v in p.visuals:
            wjson(d / "pages" / p.name / "visuals" / v["name"] / "visual.json", v)
    return pages


def main():
    if ROOT.exists():
        for sub in [SM, RP]:
            if sub.exists():
                shutil.rmtree(sub)
    ROOT.mkdir(parents=True, exist_ok=True)
    wjson(ROOT / f"{NAME}.pbip", {"version": "1.0", "artifacts": [{"report": {"path": f"{NAME}.Report"}}],
                                  "settings": {"enableAutoRecovery": True}})
    write(ROOT / ".gitignore", "**/.pbi/localSettings.json\n**/.pbi/cache.abf\n")
    build_model()
    pages = build_report()
    print(f"[ok] {ROOT}")
    print(f"     measures: {len(MEASURES)} | relationships: {len(RELS)} | pages: {len(pages)} | visuals: {sum(len(p.visuals) for p in pages)}")


if __name__ == "__main__":
    main()
