"""
Phase 6g - Generate Power BI documentation from the dashboard generator's own definitions
(so documentation can never drift from what was built).

Outputs: dashboard/docs/power_bi_dax_measures.md, dashboard/docs/power_bi_data_model.md
    python python/06g_write_powerbi_docs.py
"""
from __future__ import annotations

import sys
from importlib import import_module
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ipl_config as cfg  # noqa: E402

b = import_module("06c_build_pbip")
DOCS = cfg.PROJECT_ROOT / "dashboard" / "docs"


def esc(s):
    return str(s).replace("|", "\\|")


def dax_doc():
    lines = ["# DAX Measures - IPL Cricket Analytics Dashboard", "",
             f"_Generated from `python/06c_build_pbip.py` (the single source of the model). {len(b.MEASURES)} measures, "
             "all in the hidden `_Measures` table, grouped by display folder._", "",
             "## Shared rules", "",
             "- **Regulation only:** every ball-level measure filters `FactDelivery[is_super_over] = 0`.",
             "- **Wickets:** `Bowler Wickets` / `Bowl Wickets` sum `is_bowler_wicket` (bowled, caught, c&b, lbw, stumped, hit wicket). "
             "`Dismissals` / `Outs` use `is_player_out` (retired hurt is not out). Raw `is_wicket` is never used.",
             "- **Denominators:** run rate and economy use **legal balls** (not wides/no-balls); strike rate uses **balls faced** "
             "(all except wides); averages use **dismissals**; win % uses **decided** matches.",
             "- **Bowling role:** bowling measures call `USERELATIONSHIP` on the inactive `bowler_key` and `bowling_team_key` "
             "relationships, so a player or franchise filter means 'as bowler / bowling side'.",
             "- **Thresholds** (Phase 3/5): `Q ...` measures return BLANK below 50 innings, 500 balls faced or 1,000 legal balls; "
             "venue measures below 20 matches; close-match win % below 20 close matches.",
             "- **Season-adjusted:** `exp_runs` / `exp_bowler_wkts` on each legal ball = league rate for that season and phase "
             "(computed in Python, validated to sum exactly to actual totals).", ""]
    folder = None
    for f, name, expr, fmt, desc in b.MEASURES:
        if f != folder:
            lines += ["", f"## {f[2:]}", "", "| Measure | DAX | Format | Definition |", "|---|---|---|---|"]
            folder = f
        lines.append(f"| **{esc(name)}** | `{esc(expr)}` | `{esc(fmt)}` | {esc(desc)} |")
    (DOCS / "power_bi_dax_measures.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def model_doc():
    rows = []
    for t in ["FactDelivery", "FactBattingInnings", "FactTeamMatch", "FactMatch", "DimSeason", "DimTeam", "DimVenue", "DimPlayer", "DimPhase"]:
        df = pd.read_csv(cfg.FINAL_DIR / "powerbi" / f"{t}.csv")
        rows.append({"table": t, "type": "Fact" if t.startswith("Fact") else "Dimension", "rows": f"{len(df):,}", "columns": df.shape[1],
                     "grain / description": b.DESCRIPTIONS.get(t, "")})
    rows += [{"table": "Player A / Player B", "type": "Disconnected", "rows": "741", "columns": 1, "grain / description": b.DESCRIPTIONS["Player A"]},
             {"table": "_Measures", "type": "Measures", "rows": "0", "columns": 1, "grain / description": f"{len(b.MEASURES)} DAX measures"}]
    disp = lambda t, c: b.DISPLAY.get(t, {}).get(c, c)  # noqa: E731
    rel = pd.DataFrame([{"from (many)": f"{ft}[{disp(ft, fc)}]", "to (one)": f"{tt}[{tc}]", "cardinality": "many-to-one",
                         "cross-filter": "single (dimension -> fact)", "active": "yes" if a else "no (USERELATIONSHIP in bowling measures)"}
                        for ft, fc, tt, tc, a in b.RELS])
    tb = pd.DataFrame(rows)
    md = lambda df: "\n".join(["| " + " | ".join(df.columns) + " |", "|" + "---|" * len(df.columns)] +  # noqa: E731
                              ["| " + " | ".join(esc(x) for x in r) + " |" for r in df.astype(str).values])
    lines = ["# Power BI Data Model - IPL Cricket Analytics", "",
             "_Generated from `python/06c_build_pbip.py`. Source: validated CSV extracts in `data/final/powerbi/` "
             "(`python/06b_export_powerbi_model.py`, 13/13 export checks incl. MySQL reconciliation)._", "",
             "## Design: star schema", "",
             "- **Four fact tables at different grains** (ball, batting innings, team-match, match). They never relate to each other, "
             "so there are no fact-to-fact joins or ambiguous filter paths.",
             "- **Shared conformed dimensions** (Season, Venue, Team, Player, Phase) filter every fact they apply to, so one slicer "
             "behaves consistently across all visuals.",
             "- **Role-playing dimensions without many-to-many:** `DimTeam` and `DimPlayer` each have one ACTIVE relationship to the "
             "batting role and one INACTIVE relationship to the bowling role; bowling measures switch with `USERELATIONSHIP`.",
             "- **All relationships are one-to-many, single direction** (dimension filters fact). No bi-directional filters.",
             "- **Disconnected `Player A` / `Player B`** tables drive the comparison via `TREATAS`, so they never filter other visuals.",
             "- **Why CSV extracts instead of a live MySQL connection:** no MySQL ODBC/Connector-NET is installed for Power BI and a live "
             "connection would require storing credentials in the report. The extracts are generated from the same validated "
             "pipeline and reconciled with MySQL (check X13).", "",
             "Diagram generated from the 16 model relationships (solid = active, dotted = inactive bowling role):", "",
             "```mermaid", "flowchart LR"] + [
             f"    {tt} {'-->' if a else '-.->'}|{tc}{'' if a else ' (bowling)'}| {ft}" for ft, fc, tt, tc, a in b.RELS] + [
             "    PlayerA[Player A] -. TREATAS .-> DimPlayer", "    PlayerB[Player B] -. TREATAS .-> DimPlayer",
             "```", "", "## Tables", "", md(tb), "", "## Relationships", "", md(rel), "",
             "## Keys", "",
             "| Table | Primary key | Foreign keys |", "|---|---|---|",
             "| FactDelivery | delivery_id | season_year, venue_key, batting_team_key, bowling_team_key, batter_key, bowler_key, phase |",
             "| FactBattingInnings | (match_id, inning, player_key) | season_year, venue_key, team_key, player_key |",
             "| FactTeamMatch | (match_id, team_key) | season_year, venue_key, team_key |",
             "| FactMatch | match_id | season_year, venue_key |",
             "| DimSeason / DimTeam / DimVenue / DimPlayer / DimPhase | Season / team_key / venue_key / player_key / Phase | - |", "",
             "Key uniqueness and foreign-key resolution are validated in `reports/powerbi/export_validation_checks.csv` (X05, X06) "
             "and again inside Power BI (`dashboard_validation_report.md` R01-R03)."]
    (DOCS / "power_bi_data_model.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    DOCS.mkdir(parents=True, exist_ok=True)
    dax_doc()
    model_doc()
    print("written", DOCS)
