"""
Phase 4c - Execute the SQL business analysis on MySQL
=====================================================

Runs every tagged query in sql/06_business_analysis.sql against the live database,
saves each result to reports/sql_query_results/Qnn.csv and writes
reports/sql_business_analysis_report.md (question, SQL, explanation, actual output,
insight). Insights are generated FROM the returned rows, never typed by hand.

Run from the project root (after 04_load_mysql.py):
    python python/04c_run_sql_analysis.py
"""
from __future__ import annotations

import re
import sys
import time
from datetime import datetime
from importlib import import_module
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ipl_config as cfg  # noqa: E402
import mysql_utils as mu  # noqa: E402

md_table = import_module("01_data_profiling").md_table
OUT_DIR = cfg.REPORTS_DIR / "sql_query_results"


def top(df, col, n=0):
    return df.sort_values(col, ascending=False).iloc[n]


# question text, explanation of the SQL, and an insight built from the result -------------
META = {
    "Q01": ("How many matches were played in each season?",
            "Single-table `GROUP BY season_year` on `matches`; conditional sums of 0/1 flags count playoffs, ties, "
            "no-results and D/L games.",
            lambda d: f"{d.matches.sum():,} matches across {len(d)} seasons. The most matches with play were in "
                      f"{int(d.loc[d.matches.idxmax(), 'season_year'])} ({d.matches.max()}) and the fewest in "
                      f"{int(d.loc[d.matches.idxmin(), 'season_year'])} ({d.matches.min()}). "
                      f"{d.no_results.sum()} no-results and {d.dls_matches.sum()} D/L games are kept and flagged."),
    "Q02": ("How many total runs and bowler-credited wickets occurred in each season?",
            "Aggregates `v_reg_deliveries` (regulation balls only, super overs excluded). Bowler wickets use "
            "`is_bowler_wicket`; `all_dismissals` uses `is_player_out` (excludes retired hurt). A window "
            "`SUM(SUM(total_runs)) OVER (ORDER BY season_year)` gives the running total.",
            lambda d: f"{d.cumulative_runs.iloc[-1]:,} regulation runs and {d.bowler_wickets.sum():,} bowler wickets in "
                      f"total. 2024 alone produced {d.total_runs.iloc[-1]:,} runs. The gap between all dismissals and "
                      f"bowler wickets ({d.all_dismissals.sum() - d.bowler_wickets.sum():,}) is run-outs, retired-out "
                      f"and obstructing the field, which are not credited to bowlers."),
    "Q03": ("Which seasons had the highest average first-innings scores?",
            "Averages `inn1_runs` over `v_full_matches` (no no-results, `target_overs = 20`) so rain-shortened and D/L "
            "games don't distort the average. `RANK()` window orders seasons.",
            lambda d: f"{int(d.iloc[0].season_year)} ({d.iloc[0].avg_first_innings}) and {int(d.iloc[1].season_year)} "
                      f"({d.iloc[1].avg_first_innings}) are {d.iloc[1].avg_first_innings - d.iloc[2].avg_first_innings:.1f}+ "
                      f"runs above every other season; the lowest is "
                      f"{int(d.iloc[-1].season_year)} ({d.iloc[-1].avg_first_innings})."),
    "Q04": ("How did scoring rates change across seasons?",
            "Conditional aggregation (`SUM(CASE WHEN phase = ...)`) computes the run rate per phase in one pass; "
            "`LAG()` gives the change from the previous season. Run rate = runs x 6 / legal balls.",
            lambda d: f"Run rate peaked at {d.run_rate.max()} in {d.loc[d.run_rate.idxmax(), 'season_year']}; the "
                      f"largest season-on-season jump was {d.change_vs_prev.max():+.2f} "
                      f"({d.loc[d.change_vs_prev.idxmax(), 'season_year']}). Death overs score fastest in every season "
                      f"({int((d.rr_death > d[['rr_powerplay', 'rr_middle']].max(axis=1)).sum())}/{len(d)})."),
    "Q05": ("Which seasons had the highest average runs per match?",
            "Reads `v_season_summary`: `runs_per_match_all` = regulation runs / matches with play; "
            "`runs_per_full_match` = mean of inn1 + inn2 over full matches. Ranked with `RANK()`.",
            lambda d: f"{int(d.iloc[0].season_year)} leads with {d.iloc[0].runs_per_full_match} runs per full match, "
                      f"{d.iloc[0].runs_per_full_match - d.iloc[-1].runs_per_full_match:.1f} more than the lowest season "
                      f"({int(d.iloc[-1].season_year)})."),
    "Q06": ("Which franchises have the most match wins?",
            "`v_team_match` has two rows per match (batting-first and chasing team, derived from deliveries). A CTE "
            "counts Final wins as titles and is LEFT JOINed so teams without titles keep 0.",
            lambda d: f"{d.iloc[0].franchise_name} have the most wins ({d.iloc[0].wins}), then {d.iloc[1].franchise_name} "
                      f"({d.iloc[1].wins}). Titles: " + ", ".join(f"{r.franchise_name} {r.titles}" for r in
                                                                  d[d.titles > 0].sort_values('titles', ascending=False).itertuples())
                      + f" (total {d.titles.sum()})."),
    "Q07": ("Which franchises have the highest win percentage?",
            "Win % = wins / decided matches (no-results excluded). A `CASE` label flags short-lived franchises so small "
            "samples aren't over-read.",
            lambda d: (lambda e: f"Among established franchises, {e.iloc[0].franchise_name} lead ({e.iloc[0].win_pct}%), "
                                 f"then {e.iloc[1].franchise_name} ({e.iloc[1].win_pct}%). {d.iloc[0].franchise_name} top the "
                                 f"overall list ({d.iloc[0].win_pct}%) from only {d.iloc[0].decided_matches} matches.")(
                d[d.sample_note.str.startswith("established")])),
    "Q08": ("Which teams perform best batting first?",
            "Filters `v_team_match` to `batted_first = 1` and `result_for IN ('batting first','chasing')` (ties settled "
            "by super over and no-results excluded); `HAVING COUNT(*) >= 20` applies the EDA threshold.",
            lambda d: f"{d.iloc[0].franchise_name} have the best batting-first record ({d.iloc[0].bat_first_win_pct}% of "
                      f"{d.iloc[0].bat_first_matches}, a small sample); among long-serving sides "
                      f"{d.iloc[1].franchise_name} ({d.iloc[1].bat_first_win_pct}%) and {d.iloc[2].franchise_name} "
                      f"({d.iloc[2].bat_first_win_pct}%) lead."),
    "Q09": ("Which teams perform best while chasing?",
            "Same as Q08 with `batted_first = 0`. `result_for` (not `win_type`) is used, so the 6 D/L chases won 'by runs' "
            "are correctly counted as chasing wins.",
            lambda d: f"{d.iloc[0].franchise_name} lead ({d.iloc[0].chase_win_pct}% of {d.iloc[0].chase_matches}), then "
                      f"{d.iloc[1].franchise_name} ({d.iloc[1].chase_win_pct}%) and {d.iloc[2].franchise_name} "
                      f"({d.iloc[2].chase_win_pct}%)."),
    "Q10": ("Which teams have the best season-adjusted first-innings scoring?",
            "Window function `AVG(inn1_runs) OVER (PARTITION BY season_year)` gives each season's average; each score "
            "minus that average is then averaged per team. Two CTEs count innings in each role so the same 20+20 "
            "threshold as Python applies.",
            lambda d: f"Adjusted for season, {d.iloc[0].franchise_name} (+{d.iloc[0].vs_season_avg}) and "
                      f"{d.iloc[1].franchise_name} (+{d.iloc[1].vs_season_avg}) set the strongest totals; "
                      f"{d.loc[d.avg_first_innings.idxmax(), 'franchise_name']} have the highest RAW average "
                      f"({d.avg_first_innings.max()}) but only {d.loc[d.avg_first_innings.idxmax(), 'vs_season_avg']:+} "
                      f"after adjustment, because they only played in high-scoring seasons."),
    "Q11": ("Which teams have the best season-adjusted bowling economy?",
            "CTE `league` = runs per legal ball for each season; CTE `team_season` = runs/balls conceded per team-season. "
            "Expected runs = balls x league rate; (actual - expected) x 6 / balls = runs per over better/worse than the "
            "league in the same seasons. `RANK()` over that aggregate.",
            lambda d: (lambda e: f"{d.iloc[0].franchise_name} ({d.iloc[0].economy_vs_league:+}) and "
                                 f"{d.iloc[1].franchise_name} ({d.iloc[1].economy_vs_league:+}) are best but from 2-3 seasons. "
                                 f"Among 10+ season franchises, {e.iloc[0].franchise_name} ({e.iloc[0].economy_vs_league:+}) "
                                 f"are best and {e.iloc[-1].franchise_name} ({e.iloc[-1].economy_vs_league:+}) most expensive.")(
                d[d.seasons >= 10])),
    "Q12": ("Who are the top 10 run scorers?",
            "Reads `v_batter_career`, built from `v_batting_innings` (one row per player per innings: appeared as "
            "striker, non-striker or was dismissed). Runs = `batsman_runs`; balls exclude wides.",
            lambda d: f"{d.iloc[0].player_name} leads with {d.iloc[0].runs:,} runs ({d.iloc[0].innings} innings, average "
                      f"{d.iloc[0].batting_average}, SR {d.iloc[0].strike_rate})"
                      + (" - matching the published 8,004 for V Kohli" if (d.iloc[0].player_name == "V Kohli"
                                                                           and d.iloc[0].runs == 8004)
                         else " - NOTE: differs from the published V Kohli figure of 8,004")
                      + f" - ahead of {d.iloc[1].player_name} ({d.iloc[1].runs:,})."),
    "Q13": ("Which players have the highest batting averages (min 50 innings)?",
            "Average = runs / dismissals, where dismissals use `is_player_out` (retired hurt is not out). "
            "`WHERE innings >= 50` matches the Python threshold.",
            lambda d: f"{d.iloc[0].player_name} ({d.iloc[0].batting_average}) leads, then {d.iloc[1].player_name} "
                      f"({d.iloc[1].batting_average}) and {d.iloc[2].player_name} ({d.iloc[2].batting_average})."),
    "Q14": ("Which players have the highest strike rates (min 500 balls)?",
            "Strike rate = runs x 100 / balls faced (no-balls count as faced, wides do not). `WHERE balls >= 500`.",
            lambda d: f"{d.iloc[0].player_name} ({d.iloc[0].strike_rate}), {d.iloc[1].player_name} ({d.iloc[1].strike_rate}) "
                      f"and {d.iloc[2].player_name} ({d.iloc[2].strike_rate}) score fastest."),
    "Q15": ("Who has scored the most sixes and fours?",
            "Two `RANK()` windows (sixes, fours) in a CTE; the outer query keeps anyone in either top 10. Fours/sixes "
            "use the documented proxy `batsman_runs = 4 / 6`.",
            lambda d: f"{top(d, 'sixes').player_name} hit the most sixes ({d.sixes.max()}); "
                      f"{top(d, 'fours').player_name} the most fours ({d.fours.max()}). "
                      f"{d.sort_values('balls_per_six').iloc[0].player_name} hits a six every "
                      f"{d.balls_per_six.min()} balls among these players."),
    "Q16": ("Which batters score most consistently (min 50 innings)?",
            "Uses the view's conditional aggregates `SUM(runs >= 30) / COUNT(*)` and `SUM(runs < 10) / COUNT(*)` per "
            "player (MySQL treats a TRUE comparison as 1).",
            lambda d: f"{d.iloc[0].player_name} passes 30 in {d.iloc[0].pct_30_plus}% of innings, then "
                      f"{d.iloc[1].player_name} ({d.iloc[1].pct_30_plus}%); even these fail (<10) in "
                      f"{d.pct_under_10.min()}-{d.pct_under_10.max()}% of innings."),
    "Q17": ("Which players score most effectively in each innings phase?",
            "Aggregates batter runs/balls per phase with `HAVING balls >= 300`, then `ROW_NUMBER() OVER (PARTITION BY "
            "phase ORDER BY strike rate DESC)` keeps the top 5 per phase.",
            lambda d: "; ".join(f"{p}: {g.iloc[0].player_name} (SR {g.iloc[0].strike_rate})"
                                for p, g in d.groupby("phase", sort=False)) + "."),
    "Q18": ("Who are the top 10 bowler-credited wicket takers?",
            "Reads `v_bowler_career`: wickets = `SUM(is_bowler_wicket)` (bowled, caught, c&b, lbw, stumped, hit wicket). "
            "Raw `is_wicket` is NOT used.",
            lambda d: f"{d.iloc[0].player_name} ({d.iloc[0].wickets}), {d.iloc[1].player_name} ({d.iloc[1].wickets}) and "
                      f"{d.iloc[2].player_name} ({d.iloc[2].wickets}) lead."),
    "Q19": ("Which bowlers have the best economy (min 1,000 legal deliveries)?",
            "Economy = bowler runs conceded (batter runs + wides + no-balls) x 6 / legal balls. `WHERE legal_balls >= 1000`.",
            lambda d: f"{d.iloc[0].player_name} ({d.iloc[0].economy}), {d.iloc[1].player_name} ({d.iloc[1].economy}) and "
                      f"{d.iloc[2].player_name} ({d.iloc[2].economy}) are the most economical."),
    "Q20": ("Which bowlers have the best bowling averages and strike rates?",
            "Average = runs conceded / wickets; strike rate = legal balls / wickets. Two `RANK()` windows rank all "
            "qualifying bowlers on each measure before `LIMIT`.",
            lambda d: f"Best average: {d.iloc[0].player_name} ({d.iloc[0].bowling_average}). Best strike rate in this list: "
                      f"{d.sort_values('bowling_strike_rate').iloc[0].player_name} "
                      f"({d.bowling_strike_rate.min()}, overall rank "
                      f"{d.sort_values('bowling_strike_rate').iloc[0].strike_rate_rank})."),
    "Q21": ("Which bowlers perform best in Powerplay, Middle and Death overs?",
            "Per-phase bowler totals with `HAVING legal_balls >= 600`, then `ROW_NUMBER()` per phase by economy.",
            lambda d: "; ".join(f"{p}: {g.iloc[0].player_name} ({g.iloc[0].economy})"
                                for p, g in d.groupby("phase", sort=False)) + "."),
    "Q22": ("How have economy rates and wicket-taking rates changed by season?",
            "Season-level economy, balls per bowler wicket and dot-ball %, with `LAG()` for the season-on-season change.",
            lambda d: f"Economy rose from {d.economy.iloc[0]} (2008) to {d.economy.iloc[-1]} (2024); balls per bowler "
                      f"wicket was {d.balls_per_bowler_wicket.iloc[-1]} in 2024 (lowest season: "
                      f"{int(d.loc[d.balls_per_bowler_wicket.idxmin(), 'season_year'])}), so wickets did not become rarer "
                      f"while scoring rose."),
    "Q23": ("Does winning the toss correlate with winning the match?",
            "`UNION ALL` of an overall row and per-decision rows; `AVG(toss_winner_won)` over a 0/1 flag gives the win share.",
            lambda d: f"Toss winners won {d.iloc[0].toss_winner_win_pct}% of {d.iloc[0].matches} decided matches - close to "
                      f"a coin flip (Phase 3: 95% CI includes 50%). " + "; ".join(
                f"{r.segment}: {r.toss_winner_win_pct}%" for r in d.iloc[1:].itertuples()) + "."),
    "Q24": ("What is the win percentage when batting first versus chasing?",
            "Conditional aggregation on `result_for`, with and without D/L matches as a sensitivity check.",
            lambda d: f"Chasing teams won {d.iloc[0].chasing_win_pct}% of {d.iloc[0].matches} decided matches "
                      f"({d.iloc[1].chasing_win_pct}% excluding D/L)."),
    "Q25": ("Which venues have the highest season-adjusted first-innings scores?",
            "Window `AVG() OVER (PARTITION BY season_year)` over all full matches, then grouped by venue with "
            "`HAVING COUNT(*) >= 20`.",
            lambda d: f"{d.iloc[0].venue_name} is the highest-scoring venue (+{d.iloc[0].vs_season_avg} vs season) and "
                      f"{d.iloc[-1].venue_name} the lowest ({d.iloc[-1].vs_season_avg})."),
    "Q26": ("Which venues have the highest chasing success rates?",
            "Decided matches (`result_for` in batting first/chasing) per venue; conditional `SUM(result_for = 'chasing')`.",
            lambda d: f"Chasing succeeds most at {d.iloc[0].venue_name} ({d.iloc[0].chase_win_pct}% of "
                      f"{d.iloc[0].decided_matches}) and least at {d.iloc[-1].venue_name} ({d.iloc[-1].chase_win_pct}%). "
                      f"Phase 3 showed only the top venue's 95% interval excludes 50%."),
    "Q27": ("What are the most common winning margins?",
            "A CTE bins runs margins with `CASE` and labels wickets margins; `COUNT(*) / SUM(COUNT(*)) OVER (PARTITION BY "
            "type)` gives the share within each type and `RANK()` the most frequent band. D/L matches excluded.",
            lambda d: "Most common: " + "; ".join(
                f"{t} - {g.sort_values('matches').iloc[-1].margin_band} ({g.sort_values('matches').iloc[-1].pct_of_type}%)"
                for t, g in d.groupby("margin_type")) + "."),
    "Q28": ("How have franchises fared in super overs? (kept separate from all other statistics)",
            "`v_team_match` filtered to `is_super_over = 1`; super-over balls never enter Q01-Q27.",
            lambda d: f"{d.super_over_matches.sum() // 2} tied matches went to super overs; "
                      f"{d.iloc[0].franchise_name} played the most ({d.iloc[0].super_over_matches}, won "
                      f"{d.iloc[0].super_over_wins})."),
}


def parse_queries() -> list[tuple[str, str, str, str]]:
    text = (mu.SQL_DIR / "06_business_analysis.sql").read_text(encoding="utf-8")
    parts = re.split(r"(?m)^-- @(Q\d+) \| ", text)[1:]
    out = []
    for qid, body in zip(parts[::2], parts[1::2]):
        header, rest = body.split("\n", 1)
        section, title = [x.strip() for x in header.split("|", 1)]
        sql_lines = []
        for ln in rest.splitlines():
            if ln.startswith("-- =") or ln.startswith("-- @"):
                break
            sql_lines.append(ln)
        sql = "\n".join(sql_lines).strip().rstrip(";").strip()
        out.append((qid, section, title, sql))
    return out


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    conn = mu.connect()
    info = mu.describe_connection(conn)
    queries = parse_queries()
    assert len(queries) == len(META), f"{len(queries)} queries vs {len(META)} metadata entries"
    lines = ["# Phase 4 - SQL Business Analysis Report", "",
             f"_Generated by `python/04c_run_sql_analysis.py` on {datetime.now():%Y-%m-%d %H:%M}. Every query below was "
             f"**executed on the live MySQL server** (version {info['mysql_version']}, user `{info['current_user']}`, "
             f"database `{info['database']}`); outputs are the actual returned rows, also saved in "
             "`reports/sql_query_results/`. Insights are generated from the returned values._", "",
             "**Conventions:** super overs excluded except Q28; bowler wickets = `is_bowler_wicket`; batting order and "
             "outcome from `batting_first_team_id` / `chasing_team_id` / `result_for`; thresholds identical to Python EDA.",
             "", "## Contents", ""]
    lines += [f"- [{q} - {t}](#{q.lower()})" for q, _, t, _ in queries]
    summary = []
    section = None
    for qid, sec, title, sql in queries:
        t0 = time.time()
        df = mu.query_df(conn, sql)
        ms = (time.time() - t0) * 1000
        df.to_csv(OUT_DIR / f"{qid}.csv", index=False)
        question, explain, insight_fn = META[qid]
        insight = insight_fn(df)
        summary.append((qid, title, len(df), round(ms)))
        if sec != section:
            lines += ["", f"## {sec}", ""]
            section = sec
        lines += [f'<a id="{qid.lower()}"></a>', f"### {qid}. {title}", "",
                  f"**Business question.** {question}", "",
                  "```sql", sql + ";", "```", "",
                  f"**How it works.** {explain}", "",
                  f"**Actual output** ({len(df)} rows, {ms:.0f} ms):", "", md_table(df.head(20)), "",
                  f"**Insight.** {insight}", ""]
        print(f"{qid}: {len(df):3d} rows {ms:7.0f} ms | {title}")
    conn.close()
    (cfg.REPORTS_DIR / "sql_business_analysis_report.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"[ok] {len(queries)} queries executed; report + CSVs written")


if __name__ == "__main__":
    main()
