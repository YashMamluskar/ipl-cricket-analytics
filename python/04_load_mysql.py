"""
Phase 4a - Create the MySQL database and load the approved cleaned data
=======================================================================

Sequence (safe to rerun):
  1. sql/01_create_database.sql   CREATE DATABASE IF NOT EXISTS
  2. sql/02_create_tables.sql     CREATE TABLE IF NOT EXISTS
  3. Load in ONE transaction:     DELETE existing rows (child -> parent), INSERT dimensions,
                                  matches, deliveries, then verify counts & totals against the
                                  CSVs BEFORE committing. Any mismatch -> ROLLBACK.
  4. sql/03_create_indexes.sql    (existing indexes skipped)
  5. sql/04_create_views.sql      CREATE OR REPLACE VIEW

Inputs (read-only): data/processed/*.csv, data/reference/*.csv
Run from the project root:
    python python/04_load_mysql.py
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ipl_config as cfg  # noqa: E402
import mysql_utils as mu  # noqa: E402

BATCH = 5000


def native(v):
    """numpy/pandas scalar -> plain Python value (NaN/NA -> None)."""
    if v is None or (isinstance(v, float) and np.isnan(v)) or v is pd.NA:
        return None
    if isinstance(v, np.integer):
        return int(v)
    if isinstance(v, np.floating):
        return float(v)
    return v


def rows(df: pd.DataFrame) -> list[tuple]:
    return [tuple(native(v) for v in r) for r in df.itertuples(index=False, name=None)]


def insert(cur, table: str, df: pd.DataFrame):
    cols = ", ".join(f"`{c}`" for c in df.columns)
    ph = ", ".join(["%s"] * len(df.columns))
    sql = f"INSERT INTO `{table}` ({cols}) VALUES ({ph})"
    data = rows(df)
    for i in range(0, len(data), BATCH):
        cur.executemany(sql, data[i:i + BATCH])
    return len(data)


def build_frames():
    m = pd.read_csv(cfg.CLEAN_MATCHES)
    d = pd.read_csv(cfg.CLEAN_DELIVERIES)
    fm = pd.read_csv(cfg.FRANCHISE_MAPPING_CSV)
    vm = pd.read_csv(cfg.VENUE_MAPPING_CSV)

    # ---- dimensions (deterministic ids: alphabetical order -> stable across reruns)
    team = (fm[["franchise", "franchise_short"]].drop_duplicates().sort_values("franchise")
              .reset_index(drop=True))
    team.insert(0, "team_id", range(1, len(team) + 1))
    team = team.rename(columns={"franchise": "franchise_name"})
    tid = dict(zip(team.franchise_name, team.team_id))
    alias = pd.DataFrame({"team_name_original": fm.team_original, "team_id": fm.franchise.map(tid),
                          "mapping_type": fm.mapping_type, "decision_status": fm.decision_status,
                          "first_year": fm.first_year, "last_year": fm.last_year})

    venue = (vm[["venue_standardized", "city_standardized"]].drop_duplicates().sort_values("venue_standardized")
               .reset_index(drop=True))
    venue.insert(0, "venue_id", range(1, len(venue) + 1))
    venue = venue.rename(columns={"venue_standardized": "venue_name", "city_standardized": "city"})
    vid = dict(zip(venue.venue_name, venue.venue_id))
    valias = pd.DataFrame({"venue_original": vm.venue_original, "venue_id": vm.venue_standardized.map(vid),
                           "mapping_type": vm.mapping_type, "reason": vm.reason,
                           "verification_status": vm.verification_status, "owner_approval": vm.owner_approval,
                           "city_values_raw": vm.city_values_raw, "matches": vm.matches})

    names = sorted(pd.unique(pd.concat([d.batter, d.non_striker, d.bowler, d.player_dismissed.dropna(),
                                        d.fielder.dropna(), m.player_of_match.dropna()])))
    player = pd.DataFrame({"player_id": range(1, len(names) + 1), "player_name": names})
    pid = dict(zip(player.player_name, player.player_id))

    def strict_map(s, mapping, what):
        out = s.map(mapping)
        bad = s.notna() & out.isna()
        if bad.any():
            raise ValueError(f"Unmapped {what}: {sorted(s[bad].unique())[:5]}")
        return out.astype("Int64")

    # ---- matches
    mt = pd.DataFrame({
        "match_id": m.match_id, "season_year": m.season_year, "season_label_original": m.season_label_original,
        "match_date": m.match_date, "match_type": m.match_type, "is_playoff": m.is_playoff,
        "venue_id": strict_map(m.venue, vid, "venue"), "venue_original": m.venue_original,
        "city": m.city, "city_original": m.city_original, "is_city_imputed": m.is_city_imputed,
        "team1_id": strict_map(m.team1, tid, "team1"), "team1_original": m.team1_original,
        "team2_id": strict_map(m.team2, tid, "team2"), "team2_original": m.team2_original,
        "toss_winner_id": strict_map(m.toss_winner, tid, "toss"), "toss_winner_original": m.toss_winner_original,
        "toss_decision": m.toss_decision, "toss_winner_batted_first": m.toss_winner_batted_first,
        "batting_first_team_id": strict_map(m.batting_first_team, tid, "batting_first"),
        "chasing_team_id": strict_map(m.chasing_team, tid, "chasing"),
        "winner_id": strict_map(m.winner, tid, "winner"), "winner_original": m.winner_original,
        "result": m.result, "result_margin": m.result_margin.astype("Int64"), "win_type": m.win_type,
        "result_for": m.result_for, "toss_winner_won": m.toss_winner_won.astype("Int64"),
        "is_super_over": m.is_super_over, "is_no_result": m.is_no_result, "is_dls": m.is_dls, "method": m.method,
        "target_runs": m.target_runs.astype("Int64"), "target_overs": m.target_overs,
        "target_balls": m.target_balls.astype("Int64"),
        "inn1_runs": m.inn1_runs, "inn1_wickets": m.inn1_wickets, "inn1_legal_balls": m.inn1_legal_balls,
        "inn2_runs": m.inn2_runs.astype("Int64"), "inn2_wickets": m.inn2_wickets.astype("Int64"),
        "inn2_legal_balls": m.inn2_legal_balls.astype("Int64"),
        "player_of_match_id": strict_map(m.player_of_match, pid, "player_of_match"),
        "umpire1": m.umpire1, "umpire2": m.umpire2,
    })

    # ---- deliveries
    dt = pd.DataFrame({
        "delivery_id": d.delivery_id, "match_id": d.match_id, "inning": d.inning, "is_super_over": d.is_super_over,
        "super_over_number": d.super_over_number,
        "batting_team_id": strict_map(d.batting_team, tid, "batting_team"),
        "bowling_team_id": strict_map(d.bowling_team, tid, "bowling_team"),
        "batting_team_original": d.batting_team_original, "bowling_team_original": d.bowling_team_original,
        "over_raw": d["over"], "over_number": d.over_number, "ball": d.ball,
    })
    for c in ["is_wide", "is_noball", "is_bye", "is_legbye", "is_penalty", "is_legal_delivery", "legal_ball_in_over",
              "over_legal_balls", "is_seven_ball_over", "phase"]:
        dt[c] = d[c]
    dt["batter_id"] = strict_map(d.batter, pid, "batter")
    dt["non_striker_id"] = strict_map(d.non_striker, pid, "non_striker")
    dt["bowler_id"] = strict_map(d.bowler, pid, "bowler")
    for c in ["batsman_runs", "extra_runs", "total_runs", "extras_type", "wide_runs", "noball_runs", "bye_runs",
              "legbye_runs", "penalty_runs", "bowler_runs_conceded", "is_ball_faced", "is_dot_ball", "is_four",
              "is_six", "is_wicket"]:
        dt[c] = d[c]
    dt["player_dismissed_id"] = strict_map(d.player_dismissed, pid, "player_dismissed")
    dt["dismissal_kind"] = d.dismissal_kind
    dt["fielder_id"] = strict_map(d.fielder, pid, "fielder")
    for c in ["is_retired_hurt", "is_player_out", "is_bowler_wicket", "is_run_out"]:
        dt[c] = d[c]
    return {"team": team, "team_name_alias": alias, "venue": venue, "venue_alias": valias,
            "player": player, "matches": mt, "deliveries": dt}, m, d


# Totals verified inside the transaction before COMMIT
def expected_totals(m, d):
    return {
        "matches": len(m), "deliveries": len(d),
        "SUM(total_runs)": int(d.total_runs.sum()), "SUM(extra_runs)": int(d.extra_runs.sum()),
        "SUM(batsman_runs)": int(d.batsman_runs.sum()), "SUM(is_super_over)": int(d.is_super_over.sum()),
        "SUM(is_bowler_wicket)": int(d.is_bowler_wicket.sum()), "SUM(is_legal_delivery)": int(d.is_legal_delivery.sum()),
        "SUM(inn1_runs)": int(m.inn1_runs.sum()),
    }


def actual_totals(cur):
    out = {}
    for k, q in [("matches", "SELECT COUNT(*) FROM matches"), ("deliveries", "SELECT COUNT(*) FROM deliveries"),
                 ("SUM(total_runs)", "SELECT SUM(total_runs) FROM deliveries"),
                 ("SUM(extra_runs)", "SELECT SUM(extra_runs) FROM deliveries"),
                 ("SUM(batsman_runs)", "SELECT SUM(batsman_runs) FROM deliveries"),
                 ("SUM(is_super_over)", "SELECT SUM(is_super_over) FROM deliveries"),
                 ("SUM(is_bowler_wicket)", "SELECT SUM(is_bowler_wicket) FROM deliveries"),
                 ("SUM(is_legal_delivery)", "SELECT SUM(is_legal_delivery) FROM deliveries"),
                 ("SUM(inn1_runs)", "SELECT SUM(inn1_runs) FROM matches")]:
        cur.execute(q)
        out[k] = int(cur.fetchone()[0])
    return out


def main():
    t0 = time.time()
    frames, m, d = build_frames()
    print(f"[ok] frames built: " + ", ".join(f"{k}={len(v):,}" for k, v in frames.items()))

    conn = mu.connect(with_database=False)
    print(f"[ok] connected: {mu.describe_connection(conn)}")
    mu.run_sql_file(conn, "01_create_database.sql")
    conn.database = mu.DB_NAME
    mu.run_sql_file(conn, "02_create_tables.sql")
    print("[ok] database and tables ensured")

    cur = conn.cursor()
    try:
        conn.start_transaction()
        for t in ["deliveries", "matches", "player", "venue_alias", "venue", "team_name_alias", "team"]:
            cur.execute(f"DELETE FROM `{t}`")  # DELETE (not TRUNCATE) keeps this inside the transaction
        loaded = {}
        for t in ["team", "team_name_alias", "venue", "venue_alias", "player", "matches", "deliveries"]:
            loaded[t] = insert(cur, t, frames[t])
            print(f"   inserted {t:16s} {loaded[t]:>8,}")
        exp, act = expected_totals(m, d), actual_totals(cur)
        bad = {k: (exp[k], act[k]) for k in exp if exp[k] != act[k]}
        if bad:
            raise RuntimeError(f"Post-load verification failed (expected, actual): {bad}")
        conn.commit()
        print("[ok] COMMIT - all totals verified:", act)
    except Exception:
        conn.rollback()
        print("[FAIL] ROLLBACK - database left unchanged")
        raise
    finally:
        cur.close()

    n_ix = mu.run_sql_file(conn, "03_create_indexes.sql", skip_existing_indexes=True)
    print(f"[ok] indexes created this run: {n_ix - 1} (existing ones skipped)")
    n_v = mu.run_sql_file(conn, "04_create_views.sql")
    print(f"[ok] views script executed ({n_v} statements)")
    conn.close()
    print(f"[done] {time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()
