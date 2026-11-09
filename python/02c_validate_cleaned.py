"""
Phase 2c - Before/After Validation of Cleaned Data
==================================================

Independently re-derives expected values from the RAW files and compares them
with the CLEANED outputs. Any FAIL makes the script exit with code 1.

Outputs
-------
reports/validation/phase2_validation_checks.csv
reports/validation/phase2_before_after_validation_report.md

Run from the project root (after 02b):
    python python/02c_validate_cleaned.py
"""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ipl_config as cfg  # noqa: E402
from importlib import import_module  # noqa: E402

profiling = import_module("01_data_profiling")
md_table = profiling.md_table


class Checks:
    def __init__(self):
        self.rows = []

    def add(self, cid, area, check, before, after, ok, note=""):
        self.rows.append({"check_id": cid, "area": area, "check": check, "before_raw": before,
                          "after_clean": after, "status": "PASS" if ok else "FAIL", "note": note})

    def frame(self):
        return pd.DataFrame(self.rows)


def same(a: pd.Series, b: pd.Series) -> bool:
    """Value-equality treating NaN == NaN and ignoring dtype/index."""
    a, b = pd.Series(a).reset_index(drop=True), pd.Series(b).reset_index(drop=True)
    return bool(((a == b) | (a.isna() & b.isna())).all())


def main():
    profiling.verify_raw_files()
    m, d = profiling.load_raw()
    mc = pd.read_csv(cfg.CLEAN_MATCHES)
    dc = pd.read_csv(cfg.CLEAN_DELIVERIES)
    fm = pd.read_csv(cfg.FRANCHISE_MAPPING_CSV)
    vm = pd.read_csv(cfg.VENUE_MAPPING_CSV)
    C = Checks()

    # ------------------------------------------------------------------ counts
    C.add("V01", "Counts", "Match rows", len(m), len(mc), len(m) == len(mc))
    C.add("V02", "Counts", "Delivery rows", len(d), len(dc), len(d) == len(dc))
    C.add("V03", "Counts", "Distinct match_id set identical", m.id.nunique(), mc.match_id.nunique(),
          set(m.id) == set(mc.match_id))
    C.add("V04", "Counts", "Deliveries per match identical",
          "per-match counts", "per-match counts",
          d.groupby("match_id").size().equals(dc.groupby("match_id").size()))

    # ------------------------------------------------------------------ keys / FK
    C.add("V05", "Keys", "matches.match_id unique", "-", int(mc.match_id.duplicated().sum()), mc.match_id.is_unique)
    C.add("V06", "Keys", "deliveries.delivery_id unique", "-", int(dc.delivery_id.duplicated().sum()), dc.delivery_id.is_unique)
    k = dc.duplicated(["match_id", "inning", "over", "ball"]).sum()
    C.add("V07", "Keys", "(match_id, inning, over, ball) unique", 0, int(k), k == 0)
    orphan = (~dc.match_id.isin(mc.match_id)).sum()
    C.add("V08", "Keys", "FK deliveries.match_id -> matches.match_id (orphans)", 0, int(orphan), orphan == 0)

    # ------------------------------------------------------------------ raw values preserved
    pres_m = {"id": "match_id", "season": "season_label_original", "date": "match_date", "match_type": "match_type",
              "city": "city_original", "venue": "venue_original", "team1": "team1_original", "team2": "team2_original",
              "toss_winner": "toss_winner_original", "toss_decision": "toss_decision", "winner": "winner_original",
              "result": "result", "result_margin": "result_margin", "target_runs": "target_runs",
              "target_overs": "target_overs", "method": "method", "player_of_match": "player_of_match",
              "umpire1": "umpire1", "umpire2": "umpire2"}
    mc_by_id = mc.set_index("match_id").loc[m.id].reset_index()
    bad = [r for r, c in pres_m.items() if not same(m[r], mc_by_id[c])]
    bad += [] if same(m.super_over == "Y", mc_by_id.is_super_over == 1) else ["super_over"]
    C.add("V09", "Lineage", "Every raw matches column preserved (19 + super_over flag)", "20 cols", f"{20 - len(bad)} identical",
          not bad, f"differs: {bad}" if bad else "")
    pres_d = {c: c for c in d.columns}
    pres_d.update({"batting_team": "batting_team_original", "bowling_team": "bowling_team_original"})
    bad = [r for r, c in pres_d.items() if not same(d[r], dc[c])]
    C.add("V10", "Lineage", "Every raw deliveries column preserved (row order = delivery_id)", "17 cols",
          f"{17 - len(bad)} identical", not bad, f"differs: {bad}" if bad else "")

    # ------------------------------------------------------------------ franchise mapping
    tmap = dict(zip(fm.team_original, fm.franchise))
    raw_teams = set(m.team1) | set(m.team2)
    cl_teams = set(mc.team1) | set(mc.team2)
    C.add("V11", "Teams", "Distinct team names", len(raw_teams), len(cl_teams), len(cl_teams) == fm.franchise.nunique() == 15)
    ok = True
    for o, c in [("team1_original", "team1"), ("team2_original", "team2"), ("toss_winner_original", "toss_winner"),
                 ("winner_original", "winner")]:
        ok &= same(mc[o].map(tmap), mc[c])
    for o, c in [("batting_team_original", "batting_team"), ("bowling_team_original", "bowling_team")]:
        ok &= same(dc[o].map(tmap), dc[c])
    C.add("V12", "Teams", "Every team value equals franchise_mapping(original) (6 columns)", "-", "-", ok)
    merged = {"Delhi Daredevils": "Delhi Capitals", "Kings XI Punjab": "Punjab Kings",
              "Royal Challengers Bangalore": "Royal Challengers Bengaluru",
              "Rising Pune Supergiant": "Rising Pune Supergiants"}
    ok = all(tmap[a] == b for a, b in merged.items())
    kept = all(tmap[t] == t for t in ["Deccan Chargers", "Sunrisers Hyderabad", "Gujarat Lions", "Gujarat Titans"])
    C.add("V13", "Teams", "Approved merges applied; DC-08/SRH and GL/GT kept separate", "-", "-", ok and kept)
    j = dc.merge(mc[["match_id", "team1", "team2"]], on="match_id")
    wrong = (~(((j.batting_team == j.team1) & (j.bowling_team == j.team2)) |
               ((j.batting_team == j.team2) & (j.bowling_team == j.team1)))).sum()
    C.add("V14", "Teams", "Delivery batting/bowling teams consistent with match teams after mapping", 0, int(wrong), wrong == 0)
    win_ok = (mc.winner.isna() | (mc.winner == mc.team1) | (mc.winner == mc.team2)).all() and \
             ((mc.toss_winner == mc.team1) | (mc.toss_winner == mc.team2)).all()
    C.add("V15", "Teams", "winner / toss_winner still one of the two (mapped) teams", "-", "-", bool(win_ok))
    mapped_teams = pd.concat([m[["team1", "team2"]].stack()]).map(tmap)
    per_team_before = mapped_teams.value_counts().sort_index()
    per_team_after = pd.concat([mc.team1, mc.team2]).value_counts().sort_index()
    C.add("V16", "Teams", "Matches per franchise = sum of matches under its original names", "-", "-",
          per_team_before.equals(per_team_after))

    # ------------------------------------------------------------------ venue / city
    vmap = dict(zip(vm.venue_original, vm.venue_standardized))
    C.add("V17", "Venue", "Distinct venues", m.venue.nunique(), mc.venue.nunique(), mc.venue.nunique() == 36)
    C.add("V18", "Venue", "Every venue equals venue_mapping(original)", "-", "-", same(mc.venue_original.map(vmap), mc.venue))
    five = {"Feroz Shah Kotla": "Arun Jaitley Stadium", "Sardar Patel Stadium, Motera": "Narendra Modi Stadium",
            "Punjab Cricket Association Stadium, Mohali": "Punjab Cricket Association IS Bindra Stadium",
            "Subrata Roy Sahara Stadium": "Maharashtra Cricket Association Stadium",
            "Zayed Cricket Stadium, Abu Dhabi": "Sheikh Zayed Stadium"}
    C.add("V19", "Venue", "Five approved historical ground mappings applied", "-", "-", all(vmap[a] == b for a, b in five.items()))
    mull = vmap["Maharaja Yadavindra Singh International Cricket Stadium, Mullanpur"]
    C.add("V20", "Venue", "Mullanpur NOT merged with PCA IS Bindra Stadium", "-", mull,
          mull != "Punjab Cricket Association IS Bindra Stadium")
    C.add("V21", "City", "Missing cities", int(m.city.isna().sum()), int(mc.city.isna().sum()), mc.city.isna().sum() == 0)
    imp = mc[mc.is_city_imputed == 1]
    imp_ok = len(imp) == 51 and set(zip(imp.venue, imp.city)) == {
        ("Dubai International Cricket Stadium", "Dubai"), ("Sharjah Cricket Stadium", "Sharjah")}
    C.add("V22", "City", "Imputed cities are exactly the 51 Dubai/Sharjah rows", 51, len(imp), imp_ok,
          str(imp.city.value_counts().to_dict()))
    C.add("V23", "City", "One city per standardized venue", "-", int(mc.groupby("venue").city.nunique().max()),
          mc.groupby("venue").city.nunique().max() == 1)
    cs = mc.loc[mc.venue == "M Chinnaswamy Stadium", "city"].unique().tolist() + \
         mc.loc[mc.venue == "Dr DY Patil Sports Academy", "city"].unique().tolist()
    C.add("V24", "City", "Chinnaswamy -> Bengaluru, DY Patil -> Navi Mumbai", "Bangalore/Bengaluru; Mumbai/Navi Mumbai",
          " ; ".join(cs), cs == ["Bengaluru", "Navi Mumbai"])
    changed = mc.city_original.notna() & (mc.city_original != mc.city)
    C.add("V25", "City", "Non-missing cities changed only by approved rules", "-", int(changed.sum()),
          set(mc.loc[changed, "venue"]) <= {"M Chinnaswamy Stadium", "Dr DY Patil Sports Academy"})

    # ------------------------------------------------------------------ season
    yr = mc.groupby("season_label_original").season_year.nunique().max()
    C.add("V26", "Season", "season_year from date: 17 seasons 2008-2024, one year per label",
          m.season.nunique(), f"{mc.season_year.nunique()} ({mc.season_year.min()}-{mc.season_year.max()})",
          mc.season_year.nunique() == 17 and yr == 1 and
          same(pd.to_datetime(mc.match_date).dt.year, mc.season_year))
    C.add("V27", "Season", "Season year carried to deliveries matches parent match", "-", "-",
          same(dc.match_id.map(mc.set_index("match_id").season_year), dc.season_year))

    # ------------------------------------------------------------------ runs & extras
    C.add("V28", "Runs", "Total runs (all deliveries)", int(d.total_runs.sum()), int(dc.total_runs.sum()),
          d.total_runs.sum() == dc.total_runs.sum())
    C.add("V29", "Runs", "Batter runs (all deliveries)", int(d.batsman_runs.sum()), int(dc.batsman_runs.sum()),
          d.batsman_runs.sum() == dc.batsman_runs.sum())
    C.add("V30", "Runs", "total_runs == batsman_runs + extra_runs (rows failing)", 0,
          int((dc.total_runs != dc.batsman_runs + dc.extra_runs).sum()), (dc.total_runs == dc.batsman_runs + dc.extra_runs).all())
    comp = dc.wide_runs + dc.noball_runs + dc.bye_runs + dc.legbye_runs + dc.penalty_runs
    C.add("V31", "Runs", "extra components (wide+nb+bye+lb+penalty) == extra_runs", 0,
          int((comp != dc.extra_runs).sum()), (comp == dc.extra_runs).all())
    by_type_raw = d.groupby(d.extras_type.fillna("none")).extra_runs.sum()
    by_type_cl = pd.Series({"wides": dc.wide_runs.sum(), "noballs": dc.noball_runs.sum(), "byes": dc.bye_runs.sum(),
                            "legbyes": dc.legbye_runs.sum(), "penalty": dc.penalty_runs.sum()})
    C.add("V32", "Runs", "Extras by type", str(by_type_raw.drop("none").to_dict()), str(by_type_cl.to_dict()),
          by_type_raw.drop("none").sort_index().equals(by_type_cl.sort_index()))
    recon = dc.bowler_runs_conceded + dc.bye_runs + dc.legbye_runs + dc.penalty_runs
    C.add("V33", "Runs", "bowler_runs_conceded + byes + leg-byes + penalty == total_runs", 0,
          int((recon != dc.total_runs).sum()), (recon == dc.total_runs).all())
    batter_on_bye = int(((dc.is_bye + dc.is_legbye + dc.is_wide) > 0).mul(dc.batsman_runs).sum())
    C.add("V34", "Runs", "Batter runs credited on wides/byes/leg-byes", 0, batter_on_bye, batter_on_bye == 0)

    # ------------------------------------------------------------------ legal deliveries
    legal_raw = int((~d.extras_type.isin(["wides", "noballs"])).sum())
    C.add("V35", "Legal balls", "Legal deliveries (all innings)", legal_raw, int(dc.is_legal_delivery.sum()),
          legal_raw == dc.is_legal_delivery.sum())
    legal_reg_raw = int(((~d.extras_type.isin(["wides", "noballs"])) & (d.inning <= 2)).sum())
    legal_reg = int(dc.loc[dc.is_super_over == 0, "is_legal_delivery"].sum())
    C.add("V36", "Legal balls", "Legal deliveries (regulation innings)", legal_reg_raw, legal_reg, legal_reg == legal_reg_raw)
    faced_raw = int((d.extras_type != "wides").sum())
    C.add("V37", "Legal balls", "Balls faced by batters (all except wides)", faced_raw, int(dc.is_ball_faced.sum()),
          faced_raw == dc.is_ball_faced.sum())
    ov = dc.groupby(["match_id", "inning", "over"]).agg(lb=("is_legal_delivery", "sum"),
                                                         mx=("legal_ball_in_over", "max"), f=("is_seven_ball_over", "max"))
    C.add("V38", "Legal balls", "legal_ball_in_over max == legal balls in over", "-", int((ov.lb != ov.mx).sum()),
          (ov.lb == ov.mx).all())
    C.add("V39", "Legal balls", "Seven-legal-ball overs flagged (rows kept)", "29 overs (Phase 1)",
          f"{int((ov.f == 1).sum())} overs / {int(dc.is_seven_ball_over.sum())} rows",
          (ov.f == 1).sum() == 29 and ((ov.lb > 6) == (ov.f == 1)).all())
    reg = dc[dc.is_super_over == 0]
    C.add("V40", "Legal balls", "Regulation over_number within 1..20; phase assigned to all rows", "-",
          f"{reg.over_number.min()}..{reg.over_number.max()}",
          reg.over_number.between(1, 20).all() and dc.phase.notna().all())
    ph_ok = (((reg.phase == "Powerplay") == reg.over_number.between(1, 6)).all() and
             ((reg.phase == "Middle") == reg.over_number.between(7, 15)).all() and
             ((reg.phase == "Death") == reg.over_number.between(16, 20)).all())
    C.add("V41", "Legal balls", "Phase boundaries: PP 1-6, Middle 7-15, Death 16-20", "-",
          str(reg.phase.value_counts().to_dict()), ph_ok)

    # ------------------------------------------------------------------ wickets
    raw_bw = int(d.dismissal_kind.isin(cfg.BOWLER_WICKET_KINDS).sum())
    C.add("V42", "Wickets", "Bowler wickets (bowled, caught, c&b, lbw, stumped, hit wicket)", raw_bw,
          int(dc.is_bowler_wicket.sum()), raw_bw == dc.is_bowler_wicket.sum())
    nb = int((dc.is_bowler_wicket & dc.dismissal_kind.isin(cfg.NON_BOWLER_DISMISSALS)).sum())
    C.add("V43", "Wickets", "Run outs / retired / obstructing credited to bowler", 0, nb, nb == 0)
    C.add("V44", "Wickets", "Raw is_wicket preserved", int(d.is_wicket.sum()), int(dc.is_wicket.sum()),
          d.is_wicket.sum() == dc.is_wicket.sum())
    C.add("V45", "Wickets", "Player-out count = is_wicket - retired hurt", int(d.is_wicket.sum()) - 15,
          int(dc.is_player_out.sum()), dc.is_player_out.sum() == d.is_wicket.sum() - (d.dismissal_kind == "retired hurt").sum())
    rh = dc[dc.dismissal_kind == "retired hurt"]
    rh_ok = len(rh) == 15 and (rh.is_wicket == 1).all() and (rh.is_player_out == 0).all() and \
        (rh.is_bowler_wicket == 0).all() and (rh.is_retired_hurt == 1).all() and rh.player_dismissed.notna().all()
    C.add("V46", "Retired hurt", "15 retired-hurt rows: original fields kept, not out, not bowler wicket", 15, len(rh), rh_ok)
    C.add("V47", "Wickets", "Bowler wickets are a subset of player outs", "-",
          int((dc.is_bowler_wicket > dc.is_player_out).sum()), (dc.is_bowler_wicket <= dc.is_player_out).all())

    # ------------------------------------------------------------------ innings & match reconciliation
    reg_raw = d[d.inning <= 2]
    tot_raw = reg_raw.groupby(["match_id", "inning"]).total_runs.sum().unstack()
    mci = mc.set_index("match_id")
    ok1 = same(tot_raw[1].reindex(mci.index), mci.inn1_runs) and same(tot_raw[2].reindex(mci.index), mci.inn2_runs)
    C.add("V48", "Innings", "inn1_runs / inn2_runs equal raw regulation sums per match", "-", "-", ok1)
    C.add("V49", "Innings", "Sum of innings totals == regulation runs", int(reg_raw.total_runs.sum()),
          int(mc.inn1_runs.sum() + mc.inn2_runs.sum()), reg_raw.total_runs.sum() == mc.inn1_runs.sum() + mc.inn2_runs.sum())
    nd = mc[(mc.is_dls == 0) & mc.target_runs.notna()]
    C.add("V50", "Innings", "target_runs == inn1_runs + 1 (non-DLS)", f"{len(nd)} matches",
          f"{int((nd.target_runs == nd.inn1_runs + 1).sum())} agree", (nd.target_runs == nd.inn1_runs + 1).all())
    dec = mc[mc.win_type.isin(["runs", "wickets"]) & (mc.is_dls == 0)]
    comp_w = np.where(dec.inn2_runs > dec.inn1_runs, dec.chasing_team, dec.batting_first_team)
    C.add("V51", "Results", "Winner recomputed from innings totals (decided, non-DLS)", f"{len(dec)} matches",
          f"{int((comp_w == dec.winner).sum())} agree", (comp_w == dec.winner).all())
    rr = dec[dec.win_type == "runs"]; ww = dec[dec.win_type == "wickets"]
    C.add("V52", "Results", "runs margin == inn1 - inn2; wickets margin == 10 - inn2_wickets", "-",
          f"{int((rr.result_margin != rr.inn1_runs - rr.inn2_runs).sum())} / {int((ww.result_margin != 10 - ww.inn2_wickets).sum())} mismatches",
          (rr.result_margin == rr.inn1_runs - rr.inn2_runs).all() and (ww.result_margin == 10 - ww.inn2_wickets).all())
    nd_all = mc[mc.is_dls == 0]
    rf = (((nd_all.win_type == "runs") == (nd_all.result_for == "batting first")).all() and
          ((nd_all.win_type == "wickets") == (nd_all.result_for == "chasing")).all() and
          ((mc.win_type == "wickets") <= (mc.result_for == "chasing")).all())
    C.add("V53", "Results", "result_for consistent with win_type (non-DLS: runs=batting first, wickets=chasing)", "-",
          str(mc.result_for.value_counts().to_dict()), rf)
    # Investigated in Phase 2: under DLS, a chase stopped by rain while AHEAD of par is a
    # win 'by runs' for the CHASING team; margin = inn2_runs - par, where par = target_runs - 1.
    dl_chase = mc[(mc.is_dls == 1) & (mc.win_type == "runs") & (mc.result_for == "chasing")]
    dl_ok = (dl_chase.result_margin == dl_chase.inn2_runs - (dl_chase.target_runs - 1)).all()
    C.add("V53b", "Results", "DLS chases won 'by runs' (ahead of par): margin == inn2_runs - (target - 1)", "-",
          f"{len(dl_chase)} matches: {dl_chase.match_id.tolist()}", bool(dl_ok),
          "Legitimate DLS outcome; kept as recorded")
    C.add("V54", "Results", "Result categories unchanged", str(m.result.value_counts().to_dict()),
          str(mc.result.value_counts().to_dict()), m.result.value_counts().equals(mc.result.value_counts()))
    C.add("V55", "Results", "Batting-first team implied by toss == innings-1 team", "-",
          int((np.where(mc.toss_decision == "bat", mc.toss_winner,
                        np.where(mc.toss_winner == mc.team1, mc.team2, mc.team1)) != mc.batting_first_team).sum()),
          (np.where(mc.toss_decision == "bat", mc.toss_winner,
                    np.where(mc.toss_winner == mc.team1, mc.team2, mc.team1)) == mc.batting_first_team).all())

    # ------------------------------------------------------------------ super overs
    so = dc[dc.is_super_over == 1]
    C.add("V56", "Super over", "Super-over deliveries retained and flagged", int((d.inning >= 3).sum()), len(so),
          len(so) == (d.inning >= 3).sum() and (so.phase == "Super Over").all())
    C.add("V57", "Super over", "Super-over matches flagged consistently (matches vs deliveries)",
          int((m.super_over == "Y").sum()), int(mc.is_super_over.sum()),
          set(mc.loc[mc.is_super_over == 1, "match_id"]) == set(so.match_id))
    C.add("V58", "Super over", "Innings totals exclude super-over runs", f"SO runs = {int(so.total_runs.sum())}",
          f"inn totals = {int(mc.inn1_runs.sum() + mc.inn2_runs.sum())}; all deliveries = {int(dc.total_runs.sum())}",
          mc.inn1_runs.sum() + mc.inn2_runs.sum() + so.total_runs.sum() == dc.total_runs.sum())
    C.add("V59", "Super over", "No regulation row flagged super over / no SO row in Powerplay-Death", "-", "-",
          ((dc.is_super_over == 1) == (dc.inning >= 3)).all() and ((dc.phase == "Super Over") == (dc.is_super_over == 1)).all())

    # ------------------------------------------------------------------ write
    res = C.frame()
    res.to_csv(cfg.VALIDATION_DIR / "phase2_validation_checks.csv", index=False)

    before_after = pd.DataFrame([
        ("Match rows", len(m), len(mc)),
        ("Delivery rows", len(d), len(dc)),
        ("Matches columns", m.shape[1], mc.shape[1]),
        ("Deliveries columns", d.shape[1], dc.shape[1]),
        ("Distinct team names", len(raw_teams), len(cl_teams)),
        ("Distinct venues", m.venue.nunique(), mc.venue.nunique()),
        ("Distinct cities (non-missing)", m.city.nunique(), mc.city.nunique()),
        ("Missing cities", int(m.city.isna().sum()), int(mc.city.isna().sum())),
        ("Season labels / season years", m.season.nunique(), mc.season_year.nunique()),
        ("Total runs (all)", int(d.total_runs.sum()), int(dc.total_runs.sum())),
        ("Total runs (regulation)", int(reg_raw.total_runs.sum()), int(reg.total_runs.sum())),
        ("Legal deliveries (all)", legal_raw, int(dc.is_legal_delivery.sum())),
        ("Raw is_wicket rows", int(d.is_wicket.sum()), int(dc.is_wicket.sum())),
        ("Player outs (excl. retired hurt)", "n/a", int(dc.is_player_out.sum())),
        ("Bowler wickets", "n/a (not in raw)", int(dc.is_bowler_wicket.sum())),
        ("Super-over deliveries", int((d.inning >= 3).sum()), int(dc.is_super_over.sum())),
        ("Seven-legal-ball overs flagged", "n/a", int((ov.f == 1).sum())),
    ], columns=["metric", "before (raw)", "after (clean)"])

    counts = res.status.value_counts().to_dict()
    lines = [
        "# Phase 2 - Before/After Validation Report", "",
        f"_Generated by `python/02c_validate_cleaned.py` on {datetime.now():%Y-%m-%d %H:%M}. "
        "Expected values are re-derived from the raw files independently of the cleaning code._", "",
        f"**Result: {counts.get('PASS', 0)} PASS | {counts.get('FAIL', 0)} FAIL** (of {len(res)} checks)", "",
        "## Before vs after", "", md_table(before_after), "",
        "## All checks", "", md_table(res), "",
    ]
    (cfg.VALIDATION_DIR / "phase2_before_after_validation_report.md").write_text("\n".join(lines), encoding="utf-8")
    print(before_after.to_string(index=False))
    print()
    print(res[["check_id", "check", "before_raw", "after_clean", "status"]].to_string(index=False))
    print(f"\nPASS={counts.get('PASS', 0)} FAIL={counts.get('FAIL', 0)}")
    if counts.get("FAIL", 0):
        sys.exit(1)


if __name__ == "__main__":
    main()
