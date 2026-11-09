"""
Phase 2b - Data Cleaning & Feature Engineering
==============================================

Reads the raw files (hash-verified, never modified) plus the approved reference
mappings, and writes cleaned, analysis-ready datasets to data/processed/.

Principles
----------
* Row-preserving: no match and no delivery is dropped. Unusual records
  (super overs, retired hurt, 7-legal-ball overs, no-results, DLS) are FLAGGED.
* Every original value that is standardised is kept in an *_original column.
* Every transformation is written to a transformation log with rows affected.

Outputs
-------
data/processed/matches_clean.csv
data/processed/deliveries_clean.csv
reports/validation/phase2_transformation_log.csv

Run from the project root (after 02a):
    python python/02b_clean_data.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ipl_config as cfg  # noqa: E402
from importlib import import_module  # noqa: E402

profiling = import_module("01_data_profiling")


# --------------------------------------------------------------------------- #
class TransformLog:
    def __init__(self):
        self.rows = []

    def add(self, table, column, action, rows_affected, detail=""):
        self.rows.append({"step": len(self.rows) + 1, "table": table, "column": column,
                          "action": action, "rows_affected": int(rows_affected), "detail": detail})

    def frame(self):
        return pd.DataFrame(self.rows)


def load_mappings():
    fm = pd.read_csv(cfg.FRANCHISE_MAPPING_CSV)
    vm = pd.read_csv(cfg.VENUE_MAPPING_CSV)
    team_map = dict(zip(fm.team_original, fm.franchise))
    venue_map = dict(zip(vm.venue_original, vm.venue_standardized))
    city_map = dict(zip(vm.venue_standardized, vm.city_standardized))
    return team_map, venue_map, city_map


def map_strict(s: pd.Series, mapping: dict, what: str) -> pd.Series:
    """Map values; fail loudly if any non-null value has no mapping."""
    out = s.map(mapping)
    missing = s.notna() & out.isna()
    if missing.any():
        raise ValueError(f"Unmapped {what}: {sorted(s[missing].unique())}")
    return out


# --------------------------------------------------------------------------- #
# Matches - stage 1 (attributes only)
# --------------------------------------------------------------------------- #
def clean_matches(m: pd.DataFrame, team_map, venue_map, city_map, log: TransformLog) -> pd.DataFrame:
    T = "matches"
    out = pd.DataFrame({"match_id": m["id"].astype(int)})

    # --- season / date
    dt = pd.to_datetime(m["date"], format="%Y-%m-%d", errors="raise")
    out["match_date"] = dt.dt.strftime("%Y-%m-%d")
    out["season_year"] = dt.dt.year.astype(int)
    out["season_label_original"] = m["season"]
    log.add(T, "season_year", "derive from match date", len(m),
            f"{int((m['season'] != out['season_year'].astype(str)).sum())} rows whose label differs "
            "from play year ('2007/08','2009/10','2020/21')")

    out["match_type"] = m["match_type"]
    out["is_playoff"] = (m["match_type"] != "League").astype(int)
    log.add(T, "is_playoff", "flag non-League matches", out["is_playoff"].sum())

    # --- venue & city
    out["venue_original"] = m["venue"]
    out["venue"] = map_strict(m["venue"], venue_map, "venue")
    log.add(T, "venue", "standardise via venue_mapping.csv",
            (out["venue"] != out["venue_original"]).sum(),
            f"{m['venue'].nunique()} raw strings -> {out['venue'].nunique()} grounds")
    out["city_original"] = m["city"]
    out["city"] = map_strict(out["venue"], city_map, "city for venue")
    out["is_city_imputed"] = m["city"].isna().astype(int)
    log.add(T, "city", "fill missing city from same venue's recorded city", out["is_city_imputed"].sum(),
            str(out.loc[out.is_city_imputed == 1, "city"].value_counts().to_dict()))
    changed = m["city"].notna() & (out["city"] != m["city"])
    log.add(T, "city", "standardise city spelling per ground (approved)", changed.sum(),
            str(pd.Series(list(zip(m.loc[changed, "city"], out.loc[changed, "city"]))).value_counts().to_dict()))

    # --- teams
    for col in ["team1", "team2", "toss_winner", "winner"]:
        out[f"{col}_original"] = m[col]
        out[col] = map_strict(m[col], team_map, col)
        log.add(T, col, "standardise franchise via franchise_mapping.csv",
                (m[col].notna() & (out[col] != m[col])).sum())
    out["toss_decision"] = m["toss_decision"]

    # --- result
    out["result"] = m["result"]
    out["result_margin"] = m["result_margin"]
    out["is_super_over"] = (m["super_over"] == "Y").astype(int)
    out["is_no_result"] = (m["result"] == "no result").astype(int)
    out["is_dls"] = m["method"].notna().astype(int)
    out["method"] = m["method"]
    out["win_type"] = np.select(
        [m["result"] == "runs", m["result"] == "wickets", m["result"] == "tie", m["result"] == "no result"],
        ["runs", "wickets", "super over", "no result"], default="UNKNOWN")
    if (out["win_type"] == "UNKNOWN").any():
        raise ValueError("Unexpected result value")
    log.add(T, "win_type", "derive: runs / wickets / super over (tie) / no result", len(m))

    out["target_runs"] = m["target_runs"]
    out["target_overs"] = m["target_overs"]
    # 9.2 in cricket notation = 9 overs + 2 balls -> 56 balls
    whole = np.floor(m["target_overs"])
    out["target_balls"] = (whole * 6 + np.round((m["target_overs"] - whole) * 10)).astype("Int64")
    log.add(T, "target_balls", "convert cricket overs notation (x.y) to balls", m["target_overs"].notna().sum(),
            f"{int((m['target_overs'] % 1 != 0).sum())} fractional value(s)")

    out["player_of_match"] = m["player_of_match"]
    out["umpire1"], out["umpire2"] = m["umpire1"], m["umpire2"]
    return out


# --------------------------------------------------------------------------- #
# Deliveries
# --------------------------------------------------------------------------- #
def phase_of(over_number: pd.Series, is_so: pd.Series) -> pd.Series:
    cond = [is_so == 1] + [(over_number >= a) & (over_number <= b) for _, a, b in cfg.PHASES]
    names = ["Super Over"] + [n for n, _, _ in cfg.PHASES]
    return pd.Series(np.select(cond, names, default="UNKNOWN"), index=over_number.index)


def clean_deliveries(d: pd.DataFrame, matches_clean: pd.DataFrame, team_map, log: TransformLog) -> pd.DataFrame:
    T = "deliveries"
    out = pd.DataFrame({"delivery_id": np.arange(1, len(d) + 1)})  # = raw file row number (lineage)
    log.add(T, "delivery_id", "surrogate key = raw row number (1-based)", len(d))
    out["match_id"] = d["match_id"].astype(int).values
    out["season_year"] = out["match_id"].map(matches_clean.set_index("match_id")["season_year"])
    out["inning"] = d["inning"].values
    out["is_super_over"] = (d["inning"] >= 3).astype(int).values
    out["super_over_number"] = np.where(d["inning"] >= 3, (d["inning"] - 1) // 2, 0)
    log.add(T, "is_super_over", "flag innings >= 3 as super over (rows retained)", out["is_super_over"].sum(),
            f"super_over_number: {pd.Series(out['super_over_number']).value_counts().sort_index().to_dict()}")

    for col in ["batting_team", "bowling_team"]:
        out[f"{col}_original"] = d[col].values
        out[col] = map_strict(d[col], team_map, col).values
        log.add(T, col, "standardise franchise via franchise_mapping.csv", (out[col] != out[f"{col}_original"]).sum())

    out["over"] = d["over"].values
    out["over_number"] = d["over"].values + 1
    out["ball"] = d["ball"].values
    log.add(T, "over_number", "derive 1-based over number (over + 1); raw 0-based 'over' kept", len(d))

    et = d["extras_type"]
    for flag, kind in [("is_wide", "wides"), ("is_noball", "noballs"), ("is_bye", "byes"),
                       ("is_legbye", "legbyes"), ("is_penalty", "penalty")]:
        out[flag] = (et == kind).astype(int).values
    out["is_legal_delivery"] = (~et.isin(cfg.ILLEGAL_DELIVERY_EXTRAS)).astype(int).values
    log.add(T, "is_legal_delivery", "1 unless wide or no-ball", out["is_legal_delivery"].sum(),
            f"illegal = {int((1 - out['is_legal_delivery']).sum())}")
    key = [out["match_id"], out["inning"], out["over"]]
    out["legal_ball_in_over"] = out.groupby(key)["is_legal_delivery"].cumsum()
    out["over_legal_balls"] = out.groupby(key)["is_legal_delivery"].transform("sum")
    out["is_seven_ball_over"] = (out["over_legal_balls"] > 6).astype(int)
    log.add(T, "is_seven_ball_over", "flag overs with >6 legal balls (kept as recorded)", out["is_seven_ball_over"].sum(),
            f"{out.loc[out.is_seven_ball_over == 1, ['match_id', 'inning', 'over']].drop_duplicates().shape[0]} overs")
    out["phase"] = phase_of(out["over_number"], out["is_super_over"])
    if (out["phase"] == "UNKNOWN").any():
        raise ValueError("Unassigned phase")
    log.add(T, "phase", "Powerplay 1-6 / Middle 7-15 / Death 16-20 / Super Over", len(d),
            str(out["phase"].value_counts().to_dict()))

    out["batter"], out["non_striker"], out["bowler"] = d["batter"].values, d["non_striker"].values, d["bowler"].values

    # --- runs
    out["batsman_runs"] = d["batsman_runs"].values
    out["extra_runs"] = d["extra_runs"].values
    out["total_runs"] = d["total_runs"].values
    out["extras_type"] = et.values
    for col, flag in [("wide_runs", "is_wide"), ("noball_runs", "is_noball"), ("bye_runs", "is_bye"),
                      ("legbye_runs", "is_legbye"), ("penalty_runs", "is_penalty")]:
        out[col] = out["extra_runs"] * out[flag]
    out["bowler_runs_conceded"] = out["batsman_runs"] + out["wide_runs"] + out["noball_runs"]
    log.add(T, "bowler_runs_conceded", "batter runs + wides + no-balls (excludes byes, leg-byes, penalty)", len(d))
    out["is_ball_faced"] = (out["is_wide"] == 0).astype(int)
    log.add(T, "is_ball_faced", "ball counts as faced by batter unless wide (no-balls ARE faced)", out["is_ball_faced"].sum())
    out["is_dot_ball"] = ((out["is_legal_delivery"] == 1) & (out["total_runs"] == 0)).astype(int)
    out["is_four"] = (out["batsman_runs"] == 4).astype(int)
    out["is_six"] = (out["batsman_runs"] == 6).astype(int)
    log.add(T, "is_four/is_six", "batsman_runs == 4 / 6 (no boundary flag in source)", out["is_four"].sum() + out["is_six"].sum())

    # --- wickets (original fields preserved untouched)
    out["is_wicket"] = d["is_wicket"].values
    out["player_dismissed"] = d["player_dismissed"].values
    out["dismissal_kind"] = d["dismissal_kind"].values
    out["fielder"] = d["fielder"].values
    dk = d["dismissal_kind"]
    out["is_retired_hurt"] = (dk == "retired hurt").astype(int).values
    out["is_player_out"] = ((d["is_wicket"] == 1) & ~dk.isin(cfg.NOT_OUT_DISMISSALS)).astype(int).values
    out["is_bowler_wicket"] = dk.isin(cfg.BOWLER_WICKET_KINDS).astype(int).values
    out["is_run_out"] = (dk == "run out").astype(int).values
    log.add(T, "is_player_out", "is_wicket excluding retired hurt", out["is_player_out"].sum(),
            f"{int(out['is_retired_hurt'].sum())} retired-hurt rows set to not out")
    log.add(T, "is_bowler_wicket", f"dismissal_kind in {sorted(cfg.BOWLER_WICKET_KINDS)}", out["is_bowler_wicket"].sum())
    return out


# --------------------------------------------------------------------------- #
# Matches - stage 2 (innings facts derived from cleaned deliveries)
# --------------------------------------------------------------------------- #
def add_innings_facts(mc: pd.DataFrame, dc: pd.DataFrame, log: TransformLog) -> pd.DataFrame:
    reg = dc[dc.is_super_over == 0]
    inn = reg.groupby(["match_id", "inning"]).agg(
        team=("batting_team", "first"), runs=("total_runs", "sum"),
        wickets=("is_player_out", "sum"), legal_balls=("is_legal_delivery", "sum")).unstack()
    inn.columns = [f"inn{b}_{a}" for a, b in inn.columns]
    mc = mc.merge(inn, left_on="match_id", right_index=True, how="left", validate="1:1")

    mc["batting_first_team"] = mc["inn1_team"]
    mc["chasing_team"] = np.where(mc["batting_first_team"] == mc["team1"], mc["team2"], mc["team1"])
    mc = mc.drop(columns=["inn1_team", "inn2_team"])
    log.add("matches", "batting_first_team / chasing_team", "derive from innings-1 batting team in deliveries", len(mc))
    for c in ["inn1_runs", "inn1_wickets", "inn1_legal_balls", "inn2_runs", "inn2_wickets", "inn2_legal_balls"]:
        mc[c] = mc[c].astype("Int64")
    log.add("matches", "inn1_* / inn2_*", "regulation-innings runs, wickets (excl. retired hurt), legal balls",
            len(mc), f"{int(mc.inn2_runs.isna().sum())} matches without a 2nd innings (no result)")

    mc["toss_winner_batted_first"] = (mc["toss_winner"] == mc["batting_first_team"]).astype(int)
    decided = mc["winner"].notna()
    mc["toss_winner_won"] = pd.Series(np.where(decided, (mc["toss_winner"] == mc["winner"]).astype(int), np.nan),
                                      index=mc.index).astype("Int64")
    mc["result_for"] = np.select(
        [mc.win_type == "no result", mc.win_type == "super over",
         mc.winner == mc.batting_first_team, mc.winner == mc.chasing_team],
        ["no result", "super over", "batting first", "chasing"], default="UNKNOWN")
    if (mc.result_for == "UNKNOWN").any():
        raise ValueError("Could not classify result_for")
    log.add("matches", "result_for", "batting first / chasing / super over / no result", len(mc),
            str(mc.result_for.value_counts().to_dict()))
    return mc


MATCH_COLS = [
    "match_id", "season_year", "season_label_original", "match_date", "match_type", "is_playoff",
    "venue", "venue_original", "city", "city_original", "is_city_imputed",
    "team1", "team1_original", "team2", "team2_original",
    "toss_winner", "toss_winner_original", "toss_decision", "toss_winner_batted_first",
    "batting_first_team", "chasing_team",
    "winner", "winner_original", "result", "result_margin", "win_type", "result_for", "toss_winner_won",
    "is_super_over", "is_no_result", "is_dls", "method", "target_runs", "target_overs", "target_balls",
    "inn1_runs", "inn1_wickets", "inn1_legal_balls", "inn2_runs", "inn2_wickets", "inn2_legal_balls",
    "player_of_match", "umpire1", "umpire2",
]


def main():
    cfg.PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    profiling.verify_raw_files()
    m, d = profiling.load_raw()
    team_map, venue_map, city_map = load_mappings()
    log = TransformLog()
    print(f"[ok] raw verified; matches {m.shape}, deliveries {d.shape}")

    mc = clean_matches(m, team_map, venue_map, city_map, log)
    dc = clean_deliveries(d, mc, team_map, log)
    mc = add_innings_facts(mc, dc, log)[MATCH_COLS]

    # hard row-count guards
    assert len(mc) == len(m), "match rows changed!"
    assert len(dc) == len(d), "delivery rows changed!"

    mc.to_csv(cfg.CLEAN_MATCHES, index=False)
    dc.to_csv(cfg.CLEAN_DELIVERIES, index=False)
    lg = log.frame()
    lg.to_csv(cfg.VALIDATION_DIR / "phase2_transformation_log.csv", index=False)
    print(f"[ok] matches_clean.csv    {mc.shape}")
    print(f"[ok] deliveries_clean.csv {dc.shape}")
    print(lg[["step", "table", "column", "rows_affected"]].to_string(index=False))


if __name__ == "__main__":
    main()
