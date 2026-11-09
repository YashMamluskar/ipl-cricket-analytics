"""
Phase 4d - Reconcile MySQL results with the approved Python EDA (Phase 3)
=========================================================================

Python side : python/03_eda.py build_all()  (unrounded in-memory tables)
SQL side    : live MySQL views/queries      (div_precision_increment = 30, unrounded)

Every entity (all seasons, all franchises, ALL batters/bowlers, all qualifying venues)
is compared metric by metric. Counts must match exactly; ratios must agree within 1e-9
(floating-point vs DECIMAL representation only). Ranked lists are compared for identical
membership and order.

Outputs: reports/sql_python_reconciliation.csv          (one row per entity x metric)
         reports/sql_python_reconciliation_summary.md   (one row per metric)
Run:     python python/04d_reconcile_sql_python.py
"""
from __future__ import annotations

import sys
from datetime import datetime
from importlib import import_module
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ipl_config as cfg  # noqa: E402
import mysql_utils as mu  # noqa: E402

eda = import_module("03_eda")
md_table = import_module("01_data_profiling").md_table
TOL = 1e-9

SQL = {
    "season": "SELECT season_year AS k, matches, runs, bowler_wickets, avg_inn1, run_rate FROM v_season_summary",
    "team": """WITH t AS (
                 SELECT team_id, SUM(won) AS wins, SUM(decided) AS decided,
                        SUM(CASE WHEN batted_first = 1 AND result_for IN ('batting first','chasing') THEN 1 ELSE 0 END) AS bf_n,
                        SUM(CASE WHEN batted_first = 1 AND result_for IN ('batting first','chasing') THEN won ELSE 0 END) AS bf_w,
                        SUM(CASE WHEN batted_first = 0 AND result_for IN ('batting first','chasing') THEN 1 ELSE 0 END) AS ch_n,
                        SUM(CASE WHEN batted_first = 0 AND result_for IN ('batting first','chasing') THEN won ELSE 0 END) AS ch_w
                 FROM v_team_match GROUP BY team_id)
               SELECT tm.franchise_name AS k, t.wins, t.decided, t.wins * 100 / t.decided AS win_pct,
                      t.bf_w * 100 / t.bf_n AS bat_first_win_pct, t.ch_w * 100 / t.ch_n AS chase_win_pct,
                      (SELECT COUNT(*) FROM matches m WHERE m.match_type = 'Final' AND m.winner_id = t.team_id) AS titles
               FROM t JOIN team tm ON tm.team_id = t.team_id""",
    "team_bowling": """WITH league AS (SELECT season_year, SUM(total_runs) / SUM(is_legal_delivery) AS rpb
                                       FROM v_reg_deliveries GROUP BY season_year),
                            ts AS (SELECT bowling_team_id AS team_id, season_year, SUM(total_runs) AS runs,
                                          SUM(is_legal_delivery) AS balls FROM v_reg_deliveries
                                   GROUP BY bowling_team_id, season_year)
                       SELECT t.franchise_name AS k, SUM(ts.runs) * 6 / SUM(ts.balls) AS economy,
                              (SUM(ts.runs) - SUM(ts.balls * l.rpb)) * 6 / SUM(ts.balls) AS economy_vs_league
                       FROM ts JOIN league l USING (season_year) JOIN team t USING (team_id)
                       GROUP BY t.team_id, t.franchise_name""",
    "team_first_innings": """WITH f AS (SELECT batting_first_team_id AS team_id,
                                               inn1_runs - AVG(inn1_runs) OVER (PARTITION BY season_year) AS adj,
                                               inn1_runs FROM v_full_matches)
                             SELECT t.franchise_name AS k, AVG(inn1_runs) AS avg_inn1, AVG(adj) AS avg_inn1_vs_season
                             FROM f JOIN team t USING (team_id) GROUP BY t.team_id, t.franchise_name""",
    "batter": """SELECT player_name AS k, innings, runs, balls, outs, batting_average AS average, strike_rate,
                        fours, sixes FROM v_batter_career""",
    "bowler": """SELECT player_name AS k, legal_balls, runs_conceded, wickets, economy,
                        bowling_average AS average, bowling_strike_rate AS strike_rate FROM v_bowler_career""",
    "venue": """WITH f AS (SELECT venue_id, inn1_runs,
                                  inn1_runs - AVG(inn1_runs) OVER (PARTITION BY season_year) AS adj FROM v_full_matches),
                     a AS (SELECT venue_id, COUNT(*) AS full_matches, AVG(inn1_runs) AS avg_inn1,
                                  AVG(adj) AS avg_inn1_vs_season FROM f GROUP BY venue_id),
                     c AS (SELECT venue_id, COUNT(*) AS decided, SUM(result_for = 'chasing') * 100 / COUNT(*) AS chase_win_pct
                           FROM matches WHERE result_for IN ('batting first','chasing') GROUP BY venue_id)
                SELECT v.venue_name AS k, a.full_matches, a.avg_inn1, a.avg_inn1_vs_season, c.decided, c.chase_win_pct
                FROM venue v JOIN a USING (venue_id) JOIN c USING (venue_id)""",
    "headline": """SELECT 'league' AS k,
                          (SELECT SUM(result_for = 'chasing') * 100 / COUNT(*) FROM matches
                            WHERE result_for IN ('batting first','chasing')) AS chasing_win_pct,
                          (SELECT AVG(toss_winner_won) * 100 FROM matches WHERE is_no_result = 0) AS toss_winner_win_pct,
                          (SELECT AVG(inn1_runs) FROM v_full_matches) AS avg_first_innings_all""",
}


def compare(group, py: pd.DataFrame, sq: pd.DataFrame, metrics, rows):
    py = py.set_index("k")
    sq = sq.set_index("k")
    keys = sorted(set(py.index) | set(sq.index), key=str)
    for k in keys:
        for m in metrics:
            pv = py.at[k, m] if k in py.index else np.nan
            sv = sq.at[k, m] if k in sq.index else np.nan
            pv = None if pd.isna(pv) else float(pv)
            sv = None if pd.isna(sv) else float(sv)
            if pv is None and sv is None:
                diff, status = 0.0, "PASS (both undefined)"
            elif pv is None or sv is None:
                diff, status = np.nan, "FAIL (missing on one side)"
            else:
                diff = sv - pv
                status = "PASS" if abs(diff) <= TOL else "FAIL"
            rows.append({"group": group, "entity": k, "metric": m, "python_result": pv, "sql_result": sv,
                         "difference": diff, "status": status})


def main():
    D, S, T, V, Q, _ = eda.build_all()
    conn = mu.connect()
    sq = {k: mu.query_df(conn, s) for k, s in SQL.items()}
    rank = {
        "Top 10 run scorers (Q12 vs C1)": ("SELECT player_name FROM v_batter_career ORDER BY runs DESC LIMIT 10",
                                           D.batters.sort_values("runs", ascending=False).player.head(10)),
        "Top 10 wicket takers (Q18 vs D1)": ("SELECT player_name FROM v_bowler_career ORDER BY wickets DESC LIMIT 10",
                                             D.bowlers.sort_values("wickets", ascending=False).bowler.head(10)),
        "Top 10 batting average, 50+ inn (Q13 vs C2)": (
            "SELECT player_name FROM v_batter_career WHERE innings >= 50 ORDER BY batting_average DESC LIMIT 10",
            D.batters[D.batters.innings >= 50].sort_values("average", ascending=False).player.head(10)),
        "Top 10 strike rate, 500+ balls (Q14 vs C3)": (
            "SELECT player_name FROM v_batter_career WHERE balls >= 500 ORDER BY strike_rate DESC LIMIT 10",
            D.batters[D.batters.balls >= 500].sort_values("strike_rate", ascending=False).player.head(10)),
        "Top 10 economy, 1000+ balls (Q19 vs D2)": (
            "SELECT player_name FROM v_bowler_career WHERE legal_balls >= 1000 ORDER BY economy LIMIT 10",
            D.bowlers[D.bowlers.legal_balls >= 1000].sort_values("economy").bowler.head(10)),
        "Top 10 bowling average, 1000+ balls (Q20 vs D3)": (
            "SELECT player_name FROM v_bowler_career WHERE legal_balls >= 1000 ORDER BY bowling_average LIMIT 10",
            D.bowlers[D.bowlers.legal_balls >= 1000].sort_values("average").bowler.head(10)),
    }
    rank_res = []
    for name, (s, pylist) in rank.items():
        sql_list = mu.query_df(conn, s).player_name.tolist()
        same = sql_list == pylist.tolist()
        rank_res.append({"ranking": name, "python_top10": " > ".join(pylist), "sql_top10": " > ".join(sql_list),
                         "status": "PASS (identical order)" if same else "FAIL"})
    conn.close()

    rows = []
    compare("Season", S.rename(columns={"season_year": "k"}), sq["season"],
            ["matches", "runs", "bowler_wickets", "avg_inn1", "run_rate"], rows)
    compare("Franchise", T.rename(columns={"team": "k"}), sq["team"],
            ["wins", "decided", "win_pct", "bat_first_win_pct", "chase_win_pct", "titles"], rows)
    b6 = {q.qid: q for q in Q}["B6"].table  # rounded table; recompute unrounded from module for fairness
    reg = D.reg
    ts = reg.groupby(["bowling_team", "season_year"]).agg(runs=("total_runs", "sum"), balls=("is_legal_delivery", "sum"))
    lg = reg.groupby("season_year").total_runs.sum() / reg.groupby("season_year").is_legal_delivery.sum()
    ts["exp"] = ts.balls * ts.index.get_level_values(1).map(lg).values
    tb = ts.groupby(level=0).sum()
    py_tb = pd.DataFrame({"k": tb.index, "economy": tb.runs / tb.balls * 6,
                          "economy_vs_league": (tb.runs - tb.exp) / tb.balls * 6})
    assert np.allclose(py_tb.set_index("k").loc[b6.team, "economy_vs_league"].round(2).values, b6.economy_vs_league.values)
    compare("Team bowling (era-adjusted)", py_tb, sq["team_bowling"], ["economy", "economy_vs_league"], rows)
    f = D.full
    adj = f.assign(a=f.inn1_runs - f.groupby("season_year").inn1_runs.transform("mean"))
    py_tf = adj.groupby("batting_first_team").agg(avg_inn1=("inn1_runs", "mean"), avg_inn1_vs_season=("a", "mean"))
    compare("Team first innings (era-adjusted)", py_tf.rename_axis("k").reset_index(), sq["team_first_innings"],
            ["avg_inn1", "avg_inn1_vs_season"], rows)
    compare("Batter (all players)", D.batters.rename(columns={"player": "k"}), sq["batter"],
            ["innings", "runs", "balls", "outs", "average", "strike_rate", "fours", "sixes"], rows)
    compare("Bowler (all players)", D.bowlers.rename(columns={"bowler": "k"}), sq["bowler"],
            ["legal_balls", "runs_conceded", "wickets", "economy", "average", "strike_rate"], rows)
    compare("Venue (all with full & decided matches)", V.rename(columns={"venue": "k"}),
            sq["venue"], ["full_matches", "avg_inn1", "avg_inn1_vs_season", "decided", "chase_win_pct"], rows)
    dec = D.decided_bfc
    py_head = pd.DataFrame([{"k": "league",
                             "chasing_win_pct": (dec.result_for == "chasing").mean() * 100,
                             "toss_winner_win_pct": D.mc[D.mc.is_no_result == 0].toss_winner_won.mean() * 100,
                             "avg_first_innings_all": D.full.inn1_runs.mean()}])
    compare("League headline", py_head, sq["headline"],
            ["chasing_win_pct", "toss_winner_win_pct", "avg_first_innings_all"], rows)

    det = pd.DataFrame(rows)
    det.to_csv(cfg.REPORTS_DIR / "sql_python_reconciliation.csv", index=False)
    summ = (det.assign(absdiff=det.difference.abs(), ok=det.status.str.startswith("PASS"))
              .groupby(["group", "metric"], sort=False)
              .agg(entities=("entity", "size"), max_abs_difference=("absdiff", "max"), failures=("ok", lambda s: int((~s).sum())))
              .reset_index())
    summ["status"] = np.where(summ.failures == 0, "PASS", "FAIL")
    summ["max_abs_difference"] = summ.max_abs_difference.map(lambda x: f"{x:.2e}")
    # headline table in the requested Metric | Python | SQL | Difference | Status format
    pick = [("Season", 2024, "runs"), ("Season", 2024, "avg_inn1"), ("Season", 2009, "avg_inn1"),
            ("Franchise", "Mumbai Indians", "wins"), ("Franchise", "Chennai Super Kings", "win_pct"),
            ("Franchise", "Gujarat Titans", "chase_win_pct"), ("Franchise", "Lucknow Super Giants", "bat_first_win_pct"),
            ("Batter (all players)", "V Kohli", "runs"), ("Batter (all players)", "V Kohli", "average"),
            ("Batter (all players)", "V Kohli", "strike_rate"), ("Batter (all players)", "KL Rahul", "average"),
            ("Batter (all players)", "AD Russell", "strike_rate"), ("Batter (all players)", "CH Gayle", "sixes"),
            ("Bowler (all players)", "YS Chahal", "wickets"), ("Bowler (all players)", "M Muralitharan", "economy"),
            ("Bowler (all players)", "SL Malinga", "average"),
            ("Team bowling (era-adjusted)", "Chennai Super Kings", "economy_vs_league"),
            ("Venue (all with full & decided matches)", "M Chinnaswamy Stadium", "avg_inn1_vs_season"),
            ("Venue (all with full & decided matches)", "Sawai Mansingh Stadium", "chase_win_pct"),
            ("League headline", "league", "chasing_win_pct"), ("League headline", "league", "toss_winner_win_pct")]
    det_k = det.assign(ek=det.entity.astype(str))
    head = []
    for g, e, mtr in pick:
        r = det_k[(det_k.group == g) & (det_k.ek == str(e)) & (det_k.metric == mtr)].iloc[0]
        head.append({"Metric": f"{e} - {mtr}", "Python result": round(r.python_result, 4),
                     "SQL result": round(r.sql_result, 4), "Difference": f"{r.difference:.1e}", "Status": r.status})
    head = pd.DataFrame(head)
    rk = pd.DataFrame(rank_res)
    n_fail = int((~det.status.str.startswith("PASS")).sum())
    lines = ["# SQL vs Python Reconciliation", "",
             f"_Generated by `python/04d_reconcile_sql_python.py` on {datetime.now():%Y-%m-%d %H:%M}. Python = Phase 3 "
             "`03_eda.build_all()` (unrounded); SQL = live MySQL views with `div_precision_increment = 30`. Tolerance for "
             f"ratios: {TOL:g} (representation only); counts must be identical._", "",
             f"**Result: {len(det):,} entity-metric comparisons, {len(det) - n_fail:,} PASS, {n_fail} FAIL. "
             f"Ranked lists: {sum(r['status'].startswith('PASS') for r in rank_res)}/{len(rank_res)} identical.**", "",
             "## Headline metrics", "", md_table(head), "",
             "## Summary by metric (every entity compared)", "", md_table(summ), "",
             "## Ranked lists (membership and order)", "", md_table(rk), "",
             "Full detail: `reports/sql_python_reconciliation.csv`.", ""]
    (cfg.REPORTS_DIR / "sql_python_reconciliation_summary.md").write_text("\n".join(lines), encoding="utf-8")
    print(head.to_string(index=False))
    print("\n" + summ.to_string(index=False))
    print("\n" + rk[["ranking", "status"]].to_string(index=False))
    print(f"\nCOMPARISONS={len(det)} FAIL={n_fail}")
    if n_fail or not all(r["status"].startswith("PASS") for r in rank_res):
        sys.exit(1)


if __name__ == "__main__":
    main()
