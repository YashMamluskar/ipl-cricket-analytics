"""
Phase 6e - Validate the Power BI dashboard model against approved Python, SQL and Phase 5 outputs
=================================================================================================

Runs DAX queries against the model OPEN in Power BI Desktop (python/06d_open_refresh_capture.ps1
opens and refreshes it) and compares every result with values recomputed from the approved
pipelines (03_eda / 05_advanced_analytics) and the Phase 4 SQL query outputs. No typed constants.

Outputs: reports/powerbi/dashboard_validation_checks.csv, reports/powerbi/dashboard_validation_report.md
Run:     python python/06e_validate_dashboard.py
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from datetime import datetime
from importlib import import_module
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ipl_config as cfg  # noqa: E402

eda = import_module("03_eda")
adv = import_module("05_advanced_analytics")
build = import_module("06c_build_pbip")
md_table = import_module("01_data_profiling").md_table
HERE = Path(__file__).resolve().parent
OUT = cfg.REPORTS_DIR / "powerbi"
TOL = 1e-9


def dax(query: str) -> pd.DataFrame:
    with tempfile.NamedTemporaryFile("w", suffix=".dax", delete=False, encoding="utf-8") as f:
        f.write(query)
        path = f.name
    r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(HERE / "pbi_dax_json.ps1"),
                        "-QueryFile", path], capture_output=True, text=True, encoding="utf-8")
    Path(path).unlink(missing_ok=True)
    txt = r.stdout.strip()
    if not txt:
        raise RuntimeError(r.stderr[:500])
    data = json.loads(txt)
    if isinstance(data, dict):
        data = [data]
    df = pd.DataFrame(data)
    if "__error__" in df.columns:
        raise RuntimeError(df["__error__"].iloc[0])
    df.columns = [c.split("[")[-1].rstrip("]") if "[" in c else c for c in df.columns]
    return df


class V:
    def __init__(self):
        self.rows = []

    def add(self, cid, area, check, expected, actual, ok, note=""):
        self.rows.append({"check_id": cid, "area": area, "check": check, "expected (approved source)": str(expected),
                          "actual (Power BI DAX)": str(actual), "status": "PASS" if bool(ok) else "FAIL", "note": note})


def close(a, b):
    return a is not None and b is not None and not pd.isna(a) and not pd.isna(b) and abs(float(a) - float(b)) <= TOL * max(1, abs(float(b)))


def cmp_frames(py: pd.DataFrame, pb: pd.DataFrame, key: str, cols: dict):
    """cols: {python_col: powerbi_col}. Returns (n_compared, n_mismatch, max_abs_diff)."""
    m = py.merge(pb, left_on=key, right_on=key, how="outer", suffixes=("_py", "_pb"), indicator=True)
    miss = int((m["_merge"] != "both").sum())
    mism, mx = miss, 0.0
    for pc, bc in cols.items():
        a = m[pc + "_py"] if pc + "_py" in m else m[pc]
        b = m[bc + "_pb"] if bc + "_pb" in m else m[bc]
        d = (pd.to_numeric(a, errors="coerce") - pd.to_numeric(b, errors="coerce")).abs()
        both_nan = pd.to_numeric(a, errors="coerce").isna() & pd.to_numeric(b, errors="coerce").isna()
        bad = ~(both_nan | (d <= TOL * np.maximum(1, pd.to_numeric(a, errors="coerce").abs())))
        mism += int(bad.sum())
        mx = max(mx, float(d.fillna(0).max()))
    return len(m), mism, mx


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    D, S, T, Vt, Q, _ = eda.build_all()
    A = adv.Adv()
    v = V()
    reg = D.reg

    # ---------------------------------------------------------------- 0. every measure evaluates without error
    errs = []
    for _, name, *_ in build.MEASURES:
        try:
            dax(f'EVALUATE ROW("v", [{name}])')
        except Exception as e:  # noqa: BLE001
            errs.append(f"{name}: {str(e)[:120]}")
    v.add("B00", "DAX", f"All {len(build.MEASURES)} measures evaluate without error", 0, len(errs), not errs, "; ".join(errs[:5]))

    # ---------------------------------------------------------------- 1. KPI totals vs Phase 3 / Phase 4
    k = dax('EVALUATE ROW("Matches",[Matches],"Seasons",[Seasons],"Runs",[Total Runs],"Wkts",[Bowler Wickets],'
            '"Dism",[Dismissals],"RR",[Run Rate],"Avg1",[Avg First Innings],"Chase",[Chasing Win %],"BF",[Batting First Win %],'
            '"Toss",[Toss Winner Win %],"Close",[Close Match %],"Legal",[Legal Balls],"Wins",[Wins],"AllRuns",SUM(FactDelivery[total_runs]))').iloc[0]
    dec = D.decided_bfc
    exp = {"Matches": len(D.mc), "Seasons": D.mc.season_year.nunique(), "Runs": reg.total_runs.sum(), "Wkts": reg.is_bowler_wicket.sum(),
           "Dism": reg.is_player_out.sum(), "RR": reg.total_runs.sum() / reg.is_legal_delivery.sum() * 6,
           "Avg1": D.full.inn1_runs.mean(), "Chase": (dec.result_for == "chasing").mean(), "BF": (dec.result_for == "batting first").mean(),
           "Toss": D.mc[D.mc.is_no_result == 0].toss_winner_won.mean(), "Close": len(A.close_ids) / (D.mc.is_no_result == 0).sum(),
           "Legal": reg.is_legal_delivery.sum(), "Wins": T.wins.sum()}
    bad = {kk: (exp[kk], k[kk]) for kk in exp if not close(k[kk], exp[kk])}
    v.add("K01", "KPIs", "13 headline KPIs equal Phase 3 (matches, seasons, runs, wickets, dismissals, run rate, avg 1st inns, "
          "chase/bat-first/toss/close %, legal balls, wins)", "13 equal", f"{13 - len(bad)} equal", not bad, str(bad) if bad else "")
    v.add("K02", "Super overs", "Measures exclude super overs: all-ball runs minus [Total Runs] = super-over runs",
          int(D.so.total_runs.sum()), int(k["AllRuns"] - k["Runs"]), int(k["AllRuns"] - k["Runs"]) == int(D.so.total_runs.sum()))
    sql = pd.read_csv(cfg.REPORTS_DIR / "sql_query_results" / "Q24.csv")
    v.add("K03", "KPIs vs SQL", "Chasing win % equals Phase 4 SQL Q24 (rounded to 2 dp)", sql.chasing_win_pct.iloc[0],
          round(k["Chase"] * 100, 2), round(k["Chase"] * 100, 2) == sql.chasing_win_pct.iloc[0])
    v.add("K04", "Retired hurt", "[Dismissals] excludes retired hurt (= is_wicket - retired hurt, regulation)",
          int(reg.is_wicket.sum() - reg.is_retired_hurt.sum()), int(k["Dism"]), int(k["Dism"]) == int(reg.is_wicket.sum() - reg.is_retired_hurt.sum()))

    # ---------------------------------------------------------------- 2. season trends vs Phase 3
    s = dax('EVALUATE ADDCOLUMNS(VALUES(DimSeason[Season]), "matches",[Matches], "runs",[Total Runs], "rr",[Run Rate], '
            '"avg1",[Avg First Innings], "wkts",[Bowler Wickets], "pp",[Run Rate Powerplay], "mid",[Run Rate Middle], "death",[Run Rate Death], '
            '"chase",[Chasing Win %])')
    s = s.rename(columns={"Season": "season_year"})
    pyS = S[["season_year", "matches", "runs", "run_rate", "avg_inn1", "bowler_wickets"]].rename(
        columns={"run_rate": "rr", "avg_inn1": "avg1", "bowler_wickets": "wkts"})
    n, mm, mx = cmp_frames(pyS, s, "season_year", {"matches": "matches", "runs": "runs", "rr": "rr", "avg1": "avg1", "wkts": "wkts"})
    v.add("S01", "Season trends", "Per season: matches, runs, run rate, avg 1st inns, bowler wickets equal Phase 3 (17 x 5)",
          "0 mismatches", f"{mm} mismatches (max diff {mx:.1e})", mm == 0)
    ph = reg.groupby(["season_year", "phase"]).agg(r=("total_runs", "sum"), b=("is_legal_delivery", "sum"))
    ph = (ph.r / ph.b * 6).unstack().reset_index().rename(columns={"Powerplay": "pp", "Middle": "mid", "Death": "death"})
    n, mm, mx = cmp_frames(ph, s, "season_year", {"pp": "pp", "mid": "mid", "death": "death"})
    v.add("S02", "Season trends", "Phase run rates per season equal Phase 3 A4 (17 x 3)", "0 mismatches", f"{mm} mismatches (max {mx:.1e})", mm == 0)
    ch = dec.groupby("season_year").result_for.apply(lambda x: (x == "chasing").mean()).rename("chase").reset_index()
    n, mm, mx = cmp_frames(ch, s, "season_year", {"chase": "chase"})
    v.add("S03", "Season trends", "Chasing win % per season equals Phase 3 E2 (17)", "0 mismatches", f"{mm} mismatches", mm == 0)

    # ---------------------------------------------------------------- 3. teams vs Phase 3 / SQL / Phase 5
    t = dax('EVALUATE ADDCOLUMNS(VALUES(DimTeam[Franchise]), "wins",[Wins], "decided",[Decided], "winpct",[Win %], "titles",[Titles], '
            '"bf",[Bat First Win % (Team)], "chase",[Chase Win % (Team)], "bat_adj",[Team Batting vs League], "bowl_adj",[Team Bowling vs League])')
    t = t.rename(columns={"Franchise": "team"})
    pyT = T.assign(win_pct=T.win_pct / 100, bf=T.bat_first_win_pct / 100, ch=T.chase_win_pct / 100)
    n, mm, mx = cmp_frames(pyT[["team", "wins", "decided", "win_pct", "titles", "bf", "ch"]].rename(columns={"win_pct": "winpct", "ch": "chase"}),
                           t, "team", {"wins": "wins", "decided": "decided", "winpct": "winpct", "titles": "titles", "bf": "bf", "chase": "chase"})
    v.add("T01", "Teams", "Per franchise: wins, decided, win %, titles, bat-first %, chase % equal Phase 3 (15 x 6)", "0 mismatches",
          f"{mm} mismatches (max {mx:.1e})", mm == 0)
    q7 = pd.read_csv(cfg.REPORTS_DIR / "sql_query_results" / "Q07.csv").rename(columns={"franchise_name": "team"})
    m7 = q7.merge(t, on="team")
    ok = len(m7) == 15 and ((m7.win_pct - (m7.winpct * 100).round(2)).abs() < 1e-9).all() and (m7.wins_x == m7.wins_y).all()
    v.add("T02", "Teams vs SQL", "Wins and win % equal Phase 4 SQL Q07 for all 15 franchises", "15 equal", f"{int(ok) * 15 if ok else 'mismatch'}", ok)
    d3 = pd.read_csv(cfg.REPORTS_DIR / "advanced_analytics_tables" / "D3_team_strengths.csv")
    n, mm, mx = cmp_frames(d3[["team", "batting_rr_vs_league", "bowling_econ_vs_league"]].rename(
        columns={"batting_rr_vs_league": "bat_adj", "bowling_econ_vs_league": "bowl_adj"}), t, "team",
        {"bat_adj": "bat_adj", "bowl_adj": "bowl_adj"})
    v.add("T03", "Teams vs Phase 5", "Season/phase-adjusted batting and bowling equal Phase 5 D3 (15 x 2; table stored to 4 dp)",
          "0 mismatches at 1e-4", f"max diff {mx:.1e}", mx <= 5e-5, "D3 CSV is rounded to 4 dp")
    c5 = pd.read_csv(cfg.REPORTS_DIR / "advanced_analytics_tables" / "C5_close_matches_team.csv")
    cm = dax('EVALUATE FILTER(ADDCOLUMNS(VALUES(DimTeam[Franchise]), "cw",[Close Match Win % (min 20)], "n",[Close Matches (Team)]), NOT ISBLANK([cw]))')
    cm = cm.rename(columns={"Franchise": "team"}).merge(c5[["team", "close_win_pct", "close_matches"]], on="team", how="outer")
    ok = len(cm) == len(c5) and ((cm.cw * 100 - cm.close_win_pct).abs() <= 5e-4).all() and (cm.n == cm.close_matches).all()
    v.add("T04", "Teams vs Phase 5", "Close-match win % (20+ threshold) equals Phase 5 C5, same qualifying teams and match counts",
          f"{len(c5)} teams", f"{len(cm)} teams (max diff {(cm.cw * 100 - cm.close_win_pct).abs().max():.1e} pp)", ok,
          "C5 CSV stores percentages rounded to 3 dp, so tolerance is 5e-4 pp")

    # ---------------------------------------------------------------- 4. players vs Phase 3 (all players + rankings)
    b = dax('EVALUATE FILTER(ADDCOLUMNS(VALUES(DimPlayer[Player]), "inn",[Innings], "runs",[Bat Runs], "balls",[Balls Faced], "outs",[Outs], '
            '"avg",[Batting Average], "sr",[Strike Rate], "sixes",[Bat Sixes]), NOT ISBLANK([inn]))').rename(columns={"Player": "player"})
    n, mm, mx = cmp_frames(D.batters[["player", "innings", "runs", "balls", "outs", "average", "strike_rate", "sixes"]].rename(
        columns={"innings": "inn", "average": "avg", "strike_rate": "sr"}), b, "player",
        {"inn": "inn", "runs": "runs", "balls": "balls", "outs": "outs", "avg": "avg", "sr": "sr", "sixes": "sixes"})
    v.add("P01", "Players", f"Every batter ({len(D.batters)}): innings, runs, balls, outs, average, SR, sixes equal Phase 3",
          "0 mismatches", f"{mm} mismatches over {n} players (max {mx:.1e})", mm == 0)
    w = dax('EVALUATE FILTER(ADDCOLUMNS(VALUES(DimPlayer[Player]), "balls",[Bowl Legal Balls], "runs",[Bowl Runs Conceded], "wkts",[Bowl Wickets], '
            '"econ",[Economy], "avg",[Bowling Average], "sr",[Bowling Strike Rate]), NOT ISBLANK([balls]))').rename(columns={"Player": "bowler"})
    n, mm, mx = cmp_frames(D.bowlers[["bowler", "legal_balls", "runs_conceded", "wickets", "economy", "average", "strike_rate"]].rename(
        columns={"legal_balls": "balls", "runs_conceded": "runs", "wickets": "wkts", "economy": "econ", "average": "avg", "strike_rate": "sr"}),
        w, "bowler", {"balls": "balls", "runs": "runs", "wkts": "wkts", "econ": "econ", "avg": "avg", "sr": "sr"})
    v.add("P02", "Players", f"Every bowler ({len(D.bowlers)}): balls, runs conceded, wickets, economy, average, SR equal Phase 3",
          "0 mismatches", f"{mm} mismatches over {n} bowlers (max {mx:.1e})", mm == 0)
    for cid, meas, pylist, label in [
        ("P03", "Top 10 Run Scorers", D.batters.nlargest(10, "runs").player.tolist(), "Top 10 run scorers (C1)"),
        ("P04", "Top 10 Wicket Takers", D.bowlers.sort_values("wickets", ascending=False).head(10).bowler.tolist(), "Top 10 wicket takers (D1)")]:
        r = dax(f'EVALUATE TOPN(20, FILTER(ADDCOLUMNS(VALUES(DimPlayer[Player]), "v",[{meas}]), NOT ISBLANK([v])), [v], DESC) ORDER BY [v] DESC')
        got = r.Player.tolist()
        v.add(cid, "Rankings", f"{label}: membership and order (ties by value)", " > ".join(pylist), " > ".join(got),
              len(got) == 10 and sorted(got) == sorted(pylist) and list(r.v) == sorted(r.v, reverse=True))
    qa = dax('EVALUATE TOPN(10, FILTER(ADDCOLUMNS(VALUES(DimPlayer[Player]), "v",[Q Batting Average]), NOT ISBLANK([v])), [v], DESC) ORDER BY [v] DESC')
    exp_qa = D.batters[D.batters.innings >= 50].nlargest(10, "average").player.tolist()
    v.add("P05", "Rankings", "Top 10 batting average (50+ innings) equals Phase 3 C2", " > ".join(exp_qa), " > ".join(qa.Player), qa.Player.tolist() == exp_qa)
    qe = dax('EVALUATE TOPN(10, FILTER(ADDCOLUMNS(VALUES(DimPlayer[Player]), "v",[Q Economy]), NOT ISBLANK([v])), [v], ASC) ORDER BY [v] ASC')
    exp_qe = D.bowlers[D.bowlers.legal_balls >= 1000].nsmallest(10, "economy").bowler.tolist()
    v.add("P06", "Rankings", "Top 10 economy (1,000+ legal balls) equals Phase 3 D2", " > ".join(exp_qe), " > ".join(qe.Player), qe.Player.tolist() == exp_qe)
    th = dax('EVALUATE ROW("bat", COUNTROWS(FILTER(VALUES(DimPlayer[Player]), NOT ISBLANK([Q Batting Average]))), '
             '"sr", COUNTROWS(FILTER(VALUES(DimPlayer[Player]), NOT ISBLANK([Q Strike Rate]))), '
             '"bowl", COUNTROWS(FILTER(VALUES(DimPlayer[Player]), NOT ISBLANK([Q Economy]))))').iloc[0]
    exp_th = ((D.batters.innings >= 50).sum(), (D.batters.balls >= 500).sum(), (D.bowlers.legal_balls >= 1000).sum())
    v.add("P07", "Thresholds", "Number of players passing each ranking threshold (50 inn / 500 balls / 1,000 balls)", exp_th,
          (int(th.bat), int(th.sr), int(th.bowl)), (int(th.bat), int(th.sr), int(th.bowl)) == tuple(int(x) for x in exp_th))
    pa = dax('EVALUATE ROW("a", CALCULATE([Player A Runs], \'Player A\'[Player A] = "V Kohli"), '
             '"b", CALCULATE([Player B Wickets], \'Player B\'[Player B] = "YS Chahal"), "none", [Player A Runs])').iloc[0]
    ok = int(pa.a) == int(D.batters.set_index("player").runs["V Kohli"]) and int(pa.b) == int(D.bowlers.set_index("bowler").wickets["YS Chahal"]) \
        and pd.isna(pa.get("none"))
    v.add("P08", "Comparison", "Player A/B measures via TREATAS: Kohli runs, Chahal wickets; blank when no single player selected",
          "8004 / 205 / blank", f"{pa.a} / {pa.b} / {'blank' if pd.isna(pa.get('none')) else pa.get('none')}", ok)

    # ---------------------------------------------------------------- 5. match & venue vs Phase 5 / Phase 3
    cb = dax('EVALUATE ADDCOLUMNS(VALUES(FactMatch[First-innings band]), "n",[Chases], "p",[Chase Success %], "lo",[Chase Success CI Low], "hi",[Chase Success CI High])')
    c1 = pd.read_csv(cfg.REPORTS_DIR / "advanced_analytics_tables" / "C1_chase_by_first_innings.csv")
    c1 = c1[c1.period == "All"].rename(columns={"first_innings": "First-innings band"})
    m1 = c1.merge(cb, on="First-innings band")
    ok = len(m1) == 5 and (m1.matches == m1.n).all() and ((m1.chase_win_pct - m1.p * 100).abs() < 1e-3).all() \
        and ((m1.ci_low - m1.lo * 100).abs() < 1e-3).all() and ((m1.ci_high - m1.hi * 100).abs() < 1e-3).all()
    v.add("M01", "Chase", "Chase success and Wilson 95% CI by first-innings band equal Phase 5 C1 (5 bands)", "5 equal",
          f"{len(m1)} bands compared", ok, "C1 CSV stored to 3 dp")
    wl = dax('EVALUATE FILTER(SUMMARIZECOLUMNS(FactDelivery[Wickets lost before ball], DimPhase[Phase], "rr",[Run Rate], "balls",[Legal Balls]), NOT ISBLANK([rr]))')
    c3 = pd.read_csv(cfg.REPORTS_DIR / "advanced_analytics_tables" / "C3_wickets_remaining.csv")
    m3 = c3.merge(wl, left_on=["wkts_lost_band", "phase"], right_on=["Wickets lost before ball", "Phase"])
    ok = len(m3) == len(c3) and ((m3.run_rate - m3.rr).abs() < 1e-3).all() and (m3.balls_x == m3.balls_y).all()
    v.add("M02", "Wickets in hand", "Run rate by wickets lost x phase equals Phase 5 C3 (cells with 1,000+ balls)", f"{len(c3)} cells",
          f"{len(m3)} matched", ok)
    vv = dax('EVALUATE FILTER(ADDCOLUMNS(VALUES(DimVenue[Venue]), "n",[Venue Full Matches (min 20)], "avg1",[Venue Avg First Innings (min 20)], '
             '"adj",[Venue vs Season (min 20)], "chase",[Venue Chase Win % (min 20)]), NOT ISBLANK([n]))').rename(columns={"Venue": "venue"})
    pyV = Vt[(Vt.full_matches >= 20) & (Vt.decided >= 20)][["venue", "full_matches", "avg_inn1", "avg_inn1_vs_season", "chase_win_pct"]]
    pyV = pyV.assign(chase_win_pct=pyV.chase_win_pct / 100)
    n, mm, mx = cmp_frames(pyV.rename(columns={"full_matches": "n", "avg_inn1": "avg1", "avg_inn1_vs_season": "adj", "chase_win_pct": "chase"}),
                           vv, "venue", {"n": "n", "avg1": "avg1", "adj": "adj", "chase": "chase"})
    v.add("M03", "Venues", "Qualifying venues (20+): matches, avg 1st inns, season-adjusted, chase % equal Phase 3 E3/E4", "0 mismatches",
          f"{mm} mismatches over {n} venues (max {mx:.1e})", mm == 0)
    tf = dax('EVALUATE ADDCOLUMNS(VALUES(FactMatch[Toss decision]), "p",[Toss Winner Win %])').set_index("Toss decision").p
    exp_tf = D.mc[D.mc.is_no_result == 0].groupby("toss_decision").toss_winner_won.mean()
    v.add("M04", "Toss", "Toss-winner win % by decision equals Phase 3 E1", exp_tf.round(6).to_dict(), tf.round(6).to_dict(),
          all(close(tf[kk], exp_tf[kk]) for kk in exp_tf.index))

    # ---------------------------------------------------------------- 6. filter behaviour
    f24 = dax('EVALUATE CALCULATETABLE(ROW("m",[Matches],"r",[Total Runs],"a",[Avg First Innings],"w",[Wins]), DimSeason[Season] = 2024)').iloc[0]
    s24 = S.set_index("season_year").loc[2024]
    ok = int(f24.m) == s24.matches and int(f24.r) == s24.runs and close(f24.a, s24.avg_inn1) and int(f24.w) == int((D.mc[(D.mc.season_year == 2024)].is_no_result == 0).sum())
    v.add("F01", "Filters", "Season slicer = 2024 filters all 3 fact tables consistently (matches, runs, avg 1st inns, wins)",
          f"{s24.matches} / {s24.runs} / {s24.avg_inn1:.4f}", f"{f24.m} / {f24.r} / {f24.a:.4f}", ok)
    fv = dax('EVALUATE CALCULATETABLE(ROW("a",[Avg First Innings],"c",[Chasing Win %]), DimVenue[Venue] = "Wankhede Stadium")').iloc[0]
    vw = Vt.set_index("venue").loc["Wankhede Stadium"]
    v.add("F02", "Filters", "Venue slicer = Wankhede: avg 1st inns and chase % equal Phase 3 venue table",
          f"{vw.avg_inn1:.4f} / {vw.chase_win_pct / 100:.4f}", f"{fv.a:.4f} / {fv.c:.4f}", close(fv.a, vw.avg_inn1) and close(fv.c, vw.chase_win_pct / 100))
    ft = dax('EVALUATE CALCULATETABLE(ROW("bat",[Bat Runs],"bw",[Bowl Wickets],"tr",[Total Runs]), DimTeam[Franchise] = "Mumbai Indians")').iloc[0]
    exp_bat = int(D.bat_inn[D.bat_inn.team == "Mumbai Indians"].runs.sum())
    exp_bw = int(reg[reg.bowling_team == "Mumbai Indians"].is_bowler_wicket.sum())
    exp_tr = int(reg[reg.batting_team == "Mumbai Indians"].total_runs.sum())
    v.add("F03", "Filters", "Franchise slicer = MI: batting measures use batting team, bowling measures use bowling team (USERELATIONSHIP)",
          f"{exp_bat} / {exp_bw} / {exp_tr}", f"{ft.bat} / {ft.bw} / {ft.tr}", (int(ft.bat), int(ft.bw), int(ft.tr)) == (exp_bat, exp_bw, exp_tr))
    fp = dax('EVALUATE CALCULATETABLE(ROW("r",[Bat Runs],"bw",[Bowl Wickets],"i",[Innings]), DimPlayer[Player] = "RA Jadeja")').iloc[0]
    jb, jw = D.batters.set_index("player").loc["RA Jadeja"], D.bowlers.set_index("bowler").loc["RA Jadeja"]
    v.add("F04", "Filters", "Player filter (drill-through field) = Jadeja: batting from batter role, wickets from bowler role",
          f"{jb.runs} / {jw.wickets} / {jb.innings}", f"{fp.r} / {fp.bw} / {fp.i}", (int(fp.r), int(fp.bw), int(fp.i)) == (int(jb.runs), int(jw.wickets), int(jb.innings)))
    fc = dax('EVALUATE CALCULATETABLE(ROW("rr",[Run Rate],"s",[Seasons]), DimSeason[Season] >= 2023, DimPhase[Phase] = "Powerplay")').iloc[0]
    r23 = reg[(reg.season_year >= 2023) & (reg.phase == "Powerplay")]
    v.add("F05", "Filters", "Combined filters (seasons 2023-24 + Powerplay) on ball-level run rate", f"{r23.total_runs.sum() / r23.is_legal_delivery.sum() * 6:.6f}",
          f"{fc.rr:.6f}", close(fc.rr, r23.total_runs.sum() / r23.is_legal_delivery.sum() * 6))

    # ---------------------------------------------------------------- 7. model integrity
    ig = dax('EVALUATE ROW("orph_p", COUNTROWS(FILTER(FactDelivery, ISBLANK(RELATED(DimPlayer[Player])))), '
             '"orph_t", COUNTROWS(FILTER(FactDelivery, ISBLANK(RELATED(DimTeam[Franchise])))), '
             '"orph_s", COUNTROWS(FILTER(FactMatch, ISBLANK(RELATED(DimSeason[Season])))), '
             '"orph_v", COUNTROWS(FILTER(FactTeamMatch, ISBLANK(RELATED(DimVenue[Venue])))), '
             '"orph_b", COUNTROWS(FILTER(FactBattingInnings, ISBLANK(RELATED(DimPlayer[Player])))), '
             '"rows_d", COUNTROWS(FactDelivery), "rows_m", COUNTROWS(FactMatch), "rows_tm", COUNTROWS(FactTeamMatch), "rows_bi", COUNTROWS(FactBattingInnings), '
             '"dup_p", COUNTROWS(DimPlayer) - DISTINCTCOUNT(DimPlayer[Player]), "dup_t", COUNTROWS(DimTeam) - DISTINCTCOUNT(DimTeam[Franchise]), '
             '"dup_v", COUNTROWS(DimVenue) - DISTINCTCOUNT(DimVenue[Venue]))').iloc[0]
    orphan = sum(int(ig[c] or 0) for c in ["orph_p", "orph_t", "orph_s", "orph_v", "orph_b"])
    v.add("R01", "Relationships", "No fact rows without a matching dimension member (5 relationships probed)", 0, orphan, orphan == 0)
    rows_ok = (int(ig.rows_d), int(ig.rows_m), int(ig.rows_tm), int(ig.rows_bi)) == (len(D.dc), len(D.mc), len(D.team_long), len(D.bat_inn))
    v.add("R02", "Row counts", "Fact row counts in Power BI equal source (deliveries, matches, team-match, batting innings)",
          f"{len(D.dc)} / {len(D.mc)} / {len(D.team_long)} / {len(D.bat_inn)}", f"{ig.rows_d} / {ig.rows_m} / {ig.rows_tm} / {ig.rows_bi}", rows_ok)
    dup = int(ig.dup_p) + int(ig.dup_t) + int(ig.dup_v)
    v.add("R03", "Duplicates", "Dimension keys unique (player, franchise, venue names)", 0, dup, dup == 0)
    ag = dax('EVALUATE ROW("sum_players", SUMX(VALUES(DimPlayer[Player]), [Bat Runs]), "total", SUM(FactBattingInnings[runs]), '
             '"sum_teams", SUMX(VALUES(DimTeam[Franchise]), [Wins]), "sum_seasons", SUMX(VALUES(DimSeason[Season]), [Total Runs]))').iloc[0]
    ok = int(ag.sum_players) == int(ag.total) == int(D.batters.runs.sum()) and int(ag.sum_teams) == int(T.wins.sum()) and int(ag.sum_seasons) == int(reg.total_runs.sum())
    v.add("R04", "Aggregation", "Sum over players / teams / seasons equals grand totals (additivity, no double counting)",
          f"{D.batters.runs.sum()} / {T.wins.sum()} / {reg.total_runs.sum()}", f"{ag.sum_players} / {ag.sum_teams} / {ag.sum_seasons}", ok)
    bl = dax('EVALUATE ROW("sb", CALCULATE([Total Runs], USERELATIONSHIP(FactDelivery[bowling_team_key], DimTeam[team_key])), "t", [Total Runs])').iloc[0]
    v.add("R05", "Relationships", "Inactive bowling relationship activates without changing unfiltered totals", int(bl.t), int(bl.sb), int(bl.sb) == int(bl.t))
    nulls = dax('EVALUATE ROW("np", COUNTROWS(FILTER(DimPlayer, ISBLANK(DimPlayer[Player]))), "nt", COUNTROWS(FILTER(DimTeam, ISBLANK(DimTeam[Franchise]))), '
                '"nv", COUNTROWS(FILTER(DimVenue, ISBLANK(DimVenue[Venue]))), "nb", COUNTROWS(FILTER(FactMatch, ISBLANK(FactMatch[First-innings band]))))').iloc[0]
    v.add("R06", "Missing values", "No blank names / bands in dimensions and FactMatch", 0, int(sum(int(nulls[c] or 0) for c in ["np", "nt", "nv", "nb"])),
          sum(int(nulls[c] or 0) for c in ["np", "nt", "nv", "nb"]) == 0)

    df = pd.DataFrame(v.rows)
    df.to_csv(OUT / "dashboard_validation_checks.csv", index=False)
    c = df.status.value_counts().to_dict()
    lines = ["# Phase 6 - Power BI Dashboard Validation Report", "",
             f"_Generated by `python/06e_validate_dashboard.py` on {datetime.now():%Y-%m-%d %H:%M}. Each check runs a DAX query against the "
             "model open in Power BI Desktop (refreshed from `data/final/powerbi/`) and compares it with values recomputed from the approved "
             "Phase 3/5 Python pipelines or the Phase 4 SQL outputs. Tolerance for ratios 1e-9 unless the reference file is rounded (noted)._", "",
             f"**Result: {c.get('PASS', 0)} PASS | {c.get('FAIL', 0)} FAIL** (of {len(df)})", "", md_table(df), ""]
    (OUT / "dashboard_validation_report.md").write_text("\n".join(lines), encoding="utf-8")
    print(df[["check_id", "check", "actual (Power BI DAX)", "status"]].to_string(index=False, max_colwidth=70))
    print(f"\nPASS={c.get('PASS', 0)} FAIL={c.get('FAIL', 0)}")
    if c.get("FAIL", 0):
        sys.exit(1)


if __name__ == "__main__":
    main()
