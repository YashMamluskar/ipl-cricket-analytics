"""
Phase 6b - Export the Power BI star-schema extracts
===================================================

Builds the Power BI model tables from the APPROVED cleaned data, reusing the validated
Phase 3 (03_eda.Data) and Phase 5 (05_advanced_analytics.Adv) logic, so every derived
column has exactly the definition already validated. Nothing upstream is modified.

Outputs (data/final/powerbi/):
  DimSeason.csv DimTeam.csv DimVenue.csv DimPlayer.csv DimPhase.csv
  FactDelivery.csv FactBattingInnings.csv FactTeamMatch.csv FactMatch.csv
  reports/powerbi/export_validation_checks.csv

Run (MySQL checks need MYSQL_USER / MYSQL_PASSWORD):
    python python/06b_export_powerbi_model.py
"""
from __future__ import annotations

import sys
from importlib import import_module
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ipl_config as cfg  # noqa: E402

eda = import_module("03_eda")
adv = import_module("05_advanced_analytics")
OUT = cfg.FINAL_DIR / "powerbi"
REP = cfg.REPORTS_DIR / "powerbi"
PHASES = ["Powerplay", "Middle", "Death", "Super Over"]
BANDS, BAND_LAB = [0, 140, 160, 180, 200, 400], ["<140", "140-159", "160-179", "180-199", "200+"]


def build():
    A = adv.Adv()
    D, mc, dc = A.D, A.mc, A.D.dc
    tl = D.team_long

    # ------------------------------------------------------------- dimensions
    teams = sorted(set(mc.team1) | set(mc.team2))
    fm = pd.read_csv(cfg.FRANCHISE_MAPPING_CSV)[["franchise", "franchise_short"]].drop_duplicates()
    tstats = tl.groupby("team").agg(first_season=("season_year", "min"), last_season=("season_year", "max"),
                                    seasons=("season_year", "nunique"))
    dim_team = pd.DataFrame({"team_key": range(1, len(teams) + 1), "franchise": teams})
    dim_team = dim_team.merge(fm, left_on="franchise", right_on="franchise", how="left").join(tstats, on="franchise")
    dim_team["is_established"] = (dim_team.seasons >= 10).astype(int)
    tkey = dict(zip(dim_team.franchise, dim_team.team_key))

    V = eda.venue_table(D)
    venues = sorted(mc.venue.unique())
    dim_venue = pd.DataFrame({"venue_key": range(1, len(venues) + 1), "venue": venues})
    dim_venue["city"] = dim_venue.venue.map(mc.groupby("venue").city.first())
    dim_venue = dim_venue.merge(V[["venue", "full_matches", "decided"]], on="venue", how="left").fillna({"full_matches": 0, "decided": 0})
    dim_venue["qualifies_20"] = ((dim_venue.full_matches >= 20) & (dim_venue.decided >= 20)).astype(int)
    vkey = dict(zip(dim_venue.venue, dim_venue.venue_key))

    names = sorted(pd.unique(pd.concat([dc.batter, dc.non_striker, dc.bowler, dc.player_dismissed.dropna(),
                                        dc.fielder.dropna(), mc.player_of_match.dropna()])))
    dim_player = pd.DataFrame({"player_key": range(1, len(names) + 1), "player": names})
    pkey = dict(zip(dim_player.player, dim_player.player_key))

    dim_season = pd.DataFrame({"season_year": sorted(mc.season_year.unique())})
    dim_season["season_label"] = dim_season.season_year.astype(str)
    dim_season["era"] = dim_season.season_year.map(adv.era_of)
    dim_season["period"] = np.where(dim_season.season_year >= 2023, "2023-24", "2008-22")

    dim_phase = pd.DataFrame({"phase": PHASES, "phase_sort": [1, 2, 3, 4], "overs": ["1-6", "7-15", "16-20", "Super over"]})

    # ------------------------------------------------------------- FactMatch
    close = A.close_ids
    fmx = pd.DataFrame({
        "match_id": mc.match_id, "season_year": mc.season_year, "venue_key": mc.venue.map(vkey),
        "match_date": mc.match_date, "match_type": mc.match_type, "is_playoff": mc.is_playoff,
        "is_final": (mc.match_type == "Final").astype(int),
        "batting_first_team_key": mc.batting_first_team.map(tkey), "chasing_team_key": mc.chasing_team.map(tkey),
        "winner_team_key": mc.winner.map(tkey).astype("Int64"), "toss_winner_team_key": mc.toss_winner.map(tkey),
        "toss_decision": mc.toss_decision, "toss_winner_won": mc.toss_winner_won,
        "result": mc.result, "win_type": mc.win_type, "result_for": mc.result_for, "result_margin": mc.result_margin,
        "is_super_over": mc.is_super_over, "is_no_result": mc.is_no_result, "is_dls": mc.is_dls,
        "target_overs": mc.target_overs, "inn1_runs": mc.inn1_runs, "inn2_runs": mc.inn2_runs,
    })
    fmx["is_full_match"] = ((mc.is_no_result == 0) & (mc.target_overs == 20)).astype(int).values
    fmx["is_chase_base"] = mc.match_id.isin(A.chase_matches.match_id).astype(int).values
    fmx["chase_won"] = (mc.result_for == "chasing").astype(int).values
    fmx["is_decided_bf_chase"] = mc.result_for.isin(["batting first", "chasing"]).astype(int).values
    fmx["is_close_match"] = mc.match_id.isin(close).astype(int).values
    fmx["first_innings_band"] = pd.cut(mc.inn1_runs, BANDS, right=False, labels=BAND_LAB).astype(str).values
    fmx["first_innings_band_sort"] = pd.cut(mc.inn1_runs, BANDS, right=False, labels=False).astype(int).values + 1

    # ------------------------------------------------------------- FactTeamMatch
    ftm = pd.DataFrame({
        "match_id": tl.match_id, "team_key": tl.team.map(tkey), "opponent_team_key": tl.opponent.map(tkey),
        "season_year": tl.season_year, "venue_key": tl.venue.map(vkey), "batted_first": tl.batted_first,
        "won": tl.won, "lost": tl.lost, "decided": tl.decided, "result_for": tl.result_for,
        "is_super_over": tl.is_super_over, "is_no_result": tl.is_no_result, "is_dls": tl.is_dls,
        "is_playoff": (tl.match_type != "League").astype(int), "is_final": (tl.match_type == "Final").astype(int),
        "won_toss": (tl.toss_winner == tl.team).astype(int),
    })
    ftm["is_close_match"] = ftm.match_id.isin(close).astype(int)
    ftm["is_decided_bf_chase"] = ftm.result_for.isin(["batting first", "chasing"]).astype(int)

    # ------------------------------------------------------------- FactBattingInnings
    bi = A.bi
    fbi = pd.DataFrame({
        "match_id": bi.match_id, "inning": bi.inning, "player_key": bi.player.map(pkey), "team_key": bi.team.map(tkey),
        "opponent_team_key": bi.opponent.map(tkey), "season_year": bi.season_year,
        "venue_key": bi.match_id.map(mc.set_index("match_id").venue).map(vkey),
        "runs": bi.runs, "balls": bi.balls, "fours": bi.fours, "sixes": bi.sixes, "is_out": bi.out,
    })
    fbi["is_30_plus"] = (fbi.runs >= 30).astype(int)
    fbi["is_50_plus"] = (fbi.runs >= 50).astype(int)
    fbi["is_100_plus"] = (fbi.runs >= 100).astype(int)

    # ------------------------------------------------------------- FactDelivery (all balls incl. super overs, flagged)
    reg_extra = A.reg.set_index("delivery_id")[["wkts_before", "lg_rpb", "lg_bowler_rpb", "lg_wpb"]]
    d = dc.join(reg_extra, on="delivery_id")
    fd = pd.DataFrame({
        "delivery_id": d.delivery_id, "match_id": d.match_id, "season_year": d.season_year,
        "venue_key": d.match_id.map(mc.set_index("match_id").venue).map(vkey), "inning": d.inning,
        "is_super_over": d.is_super_over, "phase": d.phase, "over_number": d.over_number,
        "batting_team_key": d.batting_team.map(tkey), "bowling_team_key": d.bowling_team.map(tkey),
        "batter_key": d.batter.map(pkey), "bowler_key": d.bowler.map(pkey),
        "batsman_runs": d.batsman_runs, "extra_runs": d.extra_runs, "total_runs": d.total_runs,
        "bowler_runs_conceded": d.bowler_runs_conceded, "is_legal_delivery": d.is_legal_delivery,
        "is_ball_faced": d.is_ball_faced, "is_dot_ball": d.is_dot_ball, "is_four": d.is_four, "is_six": d.is_six,
        "is_wide": d.is_wide, "is_noball": d.is_noball, "is_wicket_raw": d.is_wicket, "is_player_out": d.is_player_out,
        "is_bowler_wicket": d.is_bowler_wicket, "is_seven_ball_over": d.is_seven_ball_over,
    })
    fd["is_batter_dot"] = ((d.is_ball_faced == 1) & (d.batsman_runs == 0)).astype(int).values
    fd["wkts_before"] = d.wkts_before.astype("Int64").values  # NULL for super-over balls (not used)
    fd["wkts_lost_band"] = pd.cut(d.wkts_before, [-1, 1, 3, 5, 10], labels=["0-1", "2-3", "4-5", "6+"]).astype(str) \
        .replace("nan", "").values
    fd["is_close_match"] = d.match_id.isin(close).astype(int).values
    # league expectations for season x phase (regulation only) -> season-adjusted measures in DAX
    fd["exp_runs"] = (d.is_legal_delivery * d.lg_rpb).fillna(0).round(10).values
    fd["exp_bowler_runs"] = (d.is_legal_delivery * d.lg_bowler_rpb).fillna(0).round(10).values
    fd["exp_bowler_wkts"] = (d.is_legal_delivery * d.lg_wpb).fillna(0).round(10).values

    tables = {"DimSeason": dim_season, "DimTeam": dim_team, "DimVenue": dim_venue, "DimPlayer": dim_player,
              "DimPhase": dim_phase, "FactMatch": fmx, "FactTeamMatch": ftm, "FactBattingInnings": fbi,
              "FactDelivery": fd}
    return A, tables


def validate(A, T) -> pd.DataFrame:
    rows = []

    def add(cid, check, expected, actual, ok):
        rows.append({"check_id": cid, "check": check, "expected": str(expected), "actual": str(actual),
                     "status": "PASS" if bool(ok) else "FAIL"})

    fd, fbi, ftm, fmx = T["FactDelivery"], T["FactBattingInnings"], T["FactTeamMatch"], T["FactMatch"]
    reg = fd[fd.is_super_over == 0]
    add("X01", "Row counts: matches / deliveries / team-match", "1095 / 260920 / 2190",
        f"{len(fmx)} / {len(fd)} / {len(ftm)}", len(fmx) == 1095 and len(fd) == 260920 and len(ftm) == 2190)
    add("X02", "Regulation runs / legal balls / bowler wickets (Phase 3)", "347470 / 251319 / 11795",
        f"{reg.total_runs.sum()} / {reg.is_legal_delivery.sum()} / {reg.is_bowler_wicket.sum()}",
        reg.total_runs.sum() == 347470 and reg.is_legal_delivery.sum() == 251319 and reg.is_bowler_wicket.sum() == 11795)
    add("X03", "Super-over balls retained and flagged", 161, int(fd.is_super_over.sum()), fd.is_super_over.sum() == 161)
    add("X04", "Batting innings: runs / outs equal Phase 3 batter careers", f"{A.D.batters.runs.sum()} / {A.D.batters.outs.sum()}",
        f"{fbi.runs.sum()} / {fbi.is_out.sum()}", fbi.runs.sum() == A.D.batters.runs.sum() and fbi.is_out.sum() == A.D.batters.outs.sum())
    keys = {"DimSeason": ["season_year"], "DimTeam": ["team_key"], "DimVenue": ["venue_key"], "DimPlayer": ["player_key"],
            "DimPhase": ["phase"], "FactMatch": ["match_id"], "FactTeamMatch": ["match_id", "team_key"],
            "FactBattingInnings": ["match_id", "inning", "player_key"], "FactDelivery": ["delivery_id"]}
    dup = {t: int(T[t].duplicated(k).sum() + T[t][k].isna().sum().sum()) for t, k in keys.items()}
    add("X05", "Primary keys unique and non-null in all 9 tables", "0", str(dup), sum(dup.values()) == 0)
    fk = {
        "FactDelivery.batter_key": fd.batter_key.isin(T["DimPlayer"].player_key).all(),
        "FactDelivery.bowler_key": fd.bowler_key.isin(T["DimPlayer"].player_key).all(),
        "FactDelivery.batting_team_key": fd.batting_team_key.isin(T["DimTeam"].team_key).all(),
        "FactDelivery.bowling_team_key": fd.bowling_team_key.isin(T["DimTeam"].team_key).all(),
        "FactDelivery.venue_key": fd.venue_key.isin(T["DimVenue"].venue_key).all(),
        "FactDelivery.season_year": fd.season_year.isin(T["DimSeason"].season_year).all(),
        "FactDelivery.phase": fd.phase.isin(T["DimPhase"].phase).all(),
        "FactBattingInnings.player_key": fbi.player_key.isin(T["DimPlayer"].player_key).all(),
        "FactBattingInnings.team_key": fbi.team_key.isin(T["DimTeam"].team_key).all(),
        "FactTeamMatch.team_key": ftm.team_key.isin(T["DimTeam"].team_key).all(),
        "FactMatch.venue_key": fmx.venue_key.isin(T["DimVenue"].venue_key).all(),
    }
    add("X06", "Every foreign key resolves to its dimension (11 FKs)", "11/11", f"{sum(fk.values())}/11", all(fk.values()))
    add("X07", "Season-phase expected runs sum to regulation runs (unbiased adjustment)", 347470,
        round(float(reg.exp_runs.sum()), 4), abs(reg.exp_runs.sum() - 347470) < 1e-3)
    add("X08", "Chase base / chases won (Phase 5)", "1047 / 566", f"{fmx.is_chase_base.sum()} / {fmx[fmx.is_chase_base == 1].chase_won.sum()}",
        fmx.is_chase_base.sum() == 1047 and fmx[fmx.is_chase_base == 1].chase_won.sum() == 566)
    add("X09", "Close matches (Phase 3/5 definition)", 391, int(fmx.is_close_match.sum()), fmx.is_close_match.sum() == 391)
    p3 = A.D.full  # Phase 3 full-match base, computed live (no typed constants)
    add("X10", "Full matches / avg first innings equal Phase 3", f"{len(p3)} / {p3.inn1_runs.mean():.4f}",
        f"{fmx.is_full_match.sum()} / {fmx[fmx.is_full_match == 1].inn1_runs.mean():.4f}",
        fmx.is_full_match.sum() == len(p3) and abs(fmx[fmx.is_full_match == 1].inn1_runs.mean() - p3.inn1_runs.mean()) < 1e-9)
    add("X11", "Team wins sum to decided matches (1090)", 1090, int(ftm.won.sum()), ftm.won.sum() == 1090)
    add("X12", "wkts_before present for every regulation ball", 0, int(reg.wkts_before.isna().sum()), reg.wkts_before.isna().sum() == 0)
    try:
        import mysql_utils as mu
        c = mu.connect()
        q = mu.query_df(c, """SELECT (SELECT COUNT(*) FROM matches) m, (SELECT COUNT(*) FROM deliveries) d,
                                     (SELECT SUM(total_runs) FROM v_reg_deliveries) r, (SELECT SUM(is_bowler_wicket) FROM v_reg_deliveries) w,
                                     (SELECT SUM(runs) FROM v_batter_career) br, (SELECT SUM(won) FROM v_team_match) tw""").iloc[0]
        ok = (q.m == len(fmx) and q.d == len(fd) and q.r == reg.total_runs.sum() and q.w == reg.is_bowler_wicket.sum()
              and q.br == fbi.runs.sum() and q.tw == ftm.won.sum())
        add("X13", "MySQL: matches, deliveries, runs, bowler wickets, batter runs, team wins equal extracts", "6 equal",
            "6 equal" if ok else str(q.to_dict()), ok)
        c.close()
    except Exception as e:
        add("X13", "MySQL reconciliation executed", "connection", f"ERROR {type(e).__name__}: {e}", False)
    return pd.DataFrame(rows)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    REP.mkdir(parents=True, exist_ok=True)
    A, T = build()
    for name, df in T.items():
        df.to_csv(OUT / f"{name}.csv", index=False)
        print(f"  {name:20s} {df.shape[0]:>8,} rows x {df.shape[1]:>2} cols")
    val = validate(A, T)
    val.to_csv(REP / "export_validation_checks.csv", index=False)
    print(val.to_string(index=False, max_colwidth=70))
    if (val.status != "PASS").any():
        sys.exit(1)


if __name__ == "__main__":
    main()
