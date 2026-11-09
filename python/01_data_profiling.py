"""
Phase 1 - Dataset Understanding & Profiling
===========================================

Reads the RAW IPL files (never modifies them), profiles their structure and
runs data-quality / relationship checks. Nothing in here cleans or transforms
data - it only measures and reports.

Outputs
-------
reports/profiling/column_profile_matches.csv
reports/profiling/column_profile_deliveries.csv
reports/profiling/season_coverage.csv
reports/profiling/team_name_eras.csv
reports/profiling/venue_name_variants.csv
reports/profiling/dataset_profiling_report.md
reports/validation/phase1_data_quality_checks.csv
reports/validation/phase1_initial_data_quality_report.md

Run from the project root:
    python python/01_data_profiling.py
"""
from __future__ import annotations

import hashlib
import re
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ipl_config as cfg  # noqa: E402


# --------------------------------------------------------------------------- #
# Loading
# --------------------------------------------------------------------------- #
def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def verify_raw_files() -> dict:
    """Confirm raw files exist and are byte-identical to the recorded source."""
    out = {}
    for name, expected in cfg.RAW_SHA256.items():
        p = cfg.RAW_DIR / name
        if not p.exists():
            raise FileNotFoundError(f"Raw file missing: {p}")
        actual = sha256(p)
        if actual != expected:
            raise ValueError(f"Raw file {name} hash changed! expected {expected}, got {actual}")
        out[name] = {"path": str(p.relative_to(cfg.PROJECT_ROOT)), "bytes": p.stat().st_size, "sha256": actual}
    return out


def load_raw() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Load raw CSVs with pandas defaults (the literal 'NA' is parsed as missing)."""
    matches = pd.read_csv(cfg.RAW_MATCHES)
    deliveries = pd.read_csv(cfg.RAW_DELIVERIES)
    return matches, deliveries


def load_raw_as_text() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Load raw CSVs as pure text to see exactly how missing values are encoded."""
    kw = dict(dtype=str, keep_default_na=False)
    return pd.read_csv(cfg.RAW_MATCHES, **kw), pd.read_csv(cfg.RAW_DELIVERIES, **kw)


# --------------------------------------------------------------------------- #
# Column profile
# --------------------------------------------------------------------------- #
def column_profile(df: pd.DataFrame, df_text: pd.DataFrame) -> pd.DataFrame:
    rows = []
    n = len(df)
    for c in df.columns:
        s, t = df[c], df_text[c]
        row = {
            "column": c,
            "pandas_dtype": str(s.dtype),
            "non_null": int(s.notna().sum()),
            "missing": int(s.isna().sum()),
            "missing_pct": round(s.isna().mean() * 100, 3),
            "encoded_as_literal_NA": int((t == "NA").sum()),
            "encoded_as_blank": int((t == "").sum()),
            "unique_values": int(s.nunique(dropna=True)),
            "min": s.min() if pd.api.types.is_numeric_dtype(s) else None,
            "max": s.max() if pd.api.types.is_numeric_dtype(s) else None,
            "top_values": " | ".join(f"{k} ({v})" for k, v in s.value_counts().head(5).items()),
        }
        rows.append(row)
    out = pd.DataFrame(rows)
    out.insert(1, "row_count", n)
    return out


# --------------------------------------------------------------------------- #
# Derived helper frames (used only for checking, not saved as data)
# --------------------------------------------------------------------------- #
def innings_summary(d: pd.DataFrame) -> pd.DataFrame:
    """Per match: runs & batting team for regulation innings 1 and 2."""
    reg = d[d["inning"] <= 2]
    it = (reg.groupby(["match_id", "inning"])
             .agg(runs=("total_runs", "sum"), bat=("batting_team", "first"))
             .unstack())
    it.columns = [f"{a}{b}" for a, b in it.columns]
    return it


# --------------------------------------------------------------------------- #
# Data-quality checks
# --------------------------------------------------------------------------- #
class CheckLog:
    def __init__(self):
        self.rows = []

    def add(self, cid, area, check, value, status, note=""):
        self.rows.append({"check_id": cid, "area": area, "check": check,
                          "observed": value, "status": status, "note": note})

    def frame(self):
        return pd.DataFrame(self.rows)


def run_checks(m: pd.DataFrame, d: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    log, ev = CheckLog(), {}
    PASS, FLAG, INFO = "PASS", "FLAG", "INFO"

    # ---- Structure / keys ----
    log.add("S01", "Keys", "matches.id is unique", f"{m['id'].nunique()} unique of {len(m)}",
            PASS if m["id"].is_unique else FLAG)
    log.add("S02", "Duplicates", "Fully duplicated rows in matches", int(m.duplicated().sum()),
            PASS if m.duplicated().sum() == 0 else FLAG)
    log.add("S03", "Duplicates", "Fully duplicated rows in deliveries", int(d.duplicated().sum()),
            PASS if d.duplicated().sum() == 0 else FLAG)
    k = d.duplicated(["match_id", "inning", "over", "ball"]).sum()
    log.add("S04", "Keys", "(match_id, inning, over, ball) is unique in deliveries", int(k),
            PASS if k == 0 else FLAG, "Natural composite key for a delivery")
    dup_fixture = m.duplicated(["date", "team1", "team2"]).sum()
    log.add("S05", "Duplicates", "Same date + same teams appearing twice in matches", int(dup_fixture),
            PASS if dup_fixture == 0 else FLAG)

    # ---- Relationship ----
    orphan = (~d["match_id"].isin(m["id"])).sum()
    childless = (~m["id"].isin(d["match_id"])).sum()
    log.add("R01", "Relationship", "Deliveries whose match_id is not in matches (orphans)", int(orphan),
            PASS if orphan == 0 else FLAG)
    log.add("R02", "Relationship", "Matches with no deliveries", int(childless),
            PASS if childless == 0 else FLAG)
    joined = d[["match_id", "batting_team", "bowling_team"]].merge(
        m[["id", "team1", "team2"]], left_on="match_id", right_on="id")
    wrong = ~(((joined.batting_team == joined.team1) & (joined.bowling_team == joined.team2)) |
              ((joined.batting_team == joined.team2) & (joined.bowling_team == joined.team1)))
    log.add("R03", "Relationship", "Delivery batting/bowling teams not matching match team1/team2", int(wrong.sum()),
            PASS if wrong.sum() == 0 else FLAG)
    same = (d["batting_team"] == d["bowling_team"]).sum()
    log.add("R04", "Relationship", "Deliveries where batting_team == bowling_team", int(same),
            PASS if same == 0 else FLAG)
    pom_missing = set(m["player_of_match"].dropna()) - set(d["batter"]) - set(d["bowler"]) - set(d["non_striker"])
    log.add("R05", "Relationship", "player_of_match names not found in deliveries", len(pom_missing),
            PASS if not pom_missing else FLAG)

    # ---- Match-level consistency ----
    toss_bad = (~((m.toss_winner == m.team1) | (m.toss_winner == m.team2))).sum()
    log.add("M01", "Match", "toss_winner not one of the two teams", int(toss_bad), PASS if toss_bad == 0 else FLAG)
    win_bad = (m.winner.notna() & ~((m.winner == m.team1) | (m.winner == m.team2))).sum()
    log.add("M02", "Match", "winner not one of the two teams", int(win_bad), PASS if win_bad == 0 else FLAG)
    nr = m[m.winner.isna()]
    log.add("M03", "Match", "Matches with no winner -> all have result == 'no result'",
            f"{len(nr)} missing winner; results={nr.result.unique().tolist()}",
            PASS if (nr.result == "no result").all() else FLAG)
    pom_na = m[m.player_of_match.isna()]
    log.add("M04", "Match", "Missing player_of_match only in no-result matches", len(pom_na),
            PASS if (pom_na.result == "no result").all() else FLAG)
    rm_na = m[m.result_margin.isna()]
    log.add("M05", "Match", "Missing result_margin only for tie / no result",
            str(rm_na.result.value_counts().to_dict()),
            PASS if rm_na.result.isin(["tie", "no result"]).all() else FLAG)
    so_flag = set(m.loc[m.super_over == "Y", "id"])
    so_del = set(d.loc[d.inning >= 3, "match_id"])
    log.add("M06", "Match", "super_over == 'Y' exactly matches matches with innings >= 3",
            f"flagged={len(so_flag)}, with inning>=3={len(so_del)}, diff={len(so_flag ^ so_del)}",
            PASS if so_flag == so_del else FLAG)
    ties = m[m.result == "tie"]
    log.add("M07", "Match", "Every tie went to a super over and has a winner",
            f"ties={len(ties)}, super_over Y={int((ties.super_over == 'Y').sum())}, winner present={int(ties.winner.notna().sum())}",
            PASS if (ties.super_over == "Y").all() and ties.winner.notna().all() else FLAG)
    city_na = m[m.city.isna()]
    log.add("M08", "Match", "Missing city", f"{len(city_na)} rows; venues={city_na.venue.value_counts().to_dict()}",
            FLAG, "Recoverable from venue name (UAE venues)")

    # season label vs date
    m_dates = pd.to_datetime(m["date"], format="%Y-%m-%d", errors="coerce")
    log.add("M09", "Format", "Unparseable dates (YYYY-MM-DD)", int(m_dates.isna().sum()),
            PASS if m_dates.isna().sum() == 0 else FLAG)
    yrs = m.assign(y=m_dates.dt.year).groupby("season")["y"].agg(lambda s: sorted(s.unique()))
    multi = yrs[yrs.map(len) > 1]
    mismatched = [s for s, y in yrs.items() if str(y[0]) != s]
    log.add("M10", "Format", "Each season label maps to exactly one calendar year", f"{len(multi)} labels span >1 year",
            PASS if len(multi) == 0 else FLAG)
    log.add("M11", "Format", "Season labels that differ from the calendar year of play",
            ", ".join(f"'{s}'->{yrs[s][0]}" for s in mismatched), FLAG if mismatched else PASS,
            "Season must be derived from date in Phase 2")

    # ---- Reconciliation of matches vs deliveries ----
    it = innings_summary(d)
    mm = m.set_index("id").join(it)
    x = mm[mm.target_runs.notna()]
    tgt_ok = x.target_runs == x.runs1 + 1
    non_dl = x[x.method.isna()]
    log.add("C01", "Reconciliation", "target_runs == 1st-innings runs + 1 (non-DLS matches)",
            f"{int((non_dl.target_runs == non_dl.runs1 + 1).sum())} of {len(non_dl)}",
            PASS if (non_dl.target_runs == non_dl.runs1 + 1).all() else FLAG)
    dl = x[x.method.notna()]
    log.add("C02", "Reconciliation", "DLS matches: target_runs revised (differs from 1st-innings + 1)",
            f"{int((dl.target_runs != dl.runs1 + 1).sum())} of {len(dl)}", INFO,
            "Expected under Duckworth-Lewis-Stern")
    n = mm[mm.result.isin(["runs", "wickets"]) & mm.method.isna()]
    comp_winner = np.where(n.runs2 > n.runs1, n.bat2, n.bat1)
    wm = int((comp_winner != n.winner).sum())
    log.add("C03", "Reconciliation", "Winner recomputed from delivery runs == recorded winner (non-DLS, decided)",
            f"{len(n) - wm} of {len(n)} agree", PASS if wm == 0 else FLAG)
    rr = n[n.result == "runs"]
    rbad = int((rr.result_margin != rr.runs1 - rr.runs2).sum())
    log.add("C04", "Reconciliation", "'runs' margin == inn1 runs - inn2 runs (non-DLS)",
            f"{len(rr) - rbad} of {len(rr)} agree", PASS if rbad == 0 else FLAG)
    wk2 = d[(d.inning == 2) & (d.is_wicket == 1) & (~d.dismissal_kind.isin(cfg.NOT_OUT_DISMISSALS))] \
        .groupby("match_id").size()
    nw = n[n.result == "wickets"]
    calc = 10 - wk2.reindex(nw.index).fillna(0)
    wbad = int((calc != nw.result_margin).sum())
    log.add("C05", "Reconciliation", "'wickets' margin == 10 - wickets lost in chase (excl. retired hurt)",
            f"{len(nw) - wbad} of {len(nw)} agree", PASS if wbad == 0 else FLAG)
    k = mm.bat1.notna()
    exp_bat1 = pd.Series(np.where(mm.toss_decision == "bat", mm.toss_winner,
                                  np.where(mm.toss_winner == mm.team1, mm.team2, mm.team1)), index=mm.index)
    tbad = int((exp_bat1[k] != mm.bat1[k]).sum())
    log.add("C06", "Reconciliation", "Team batting first implied by toss == batting team of innings 1",
            f"{int(k.sum()) - tbad} of {int(k.sum())} agree", PASS if tbad == 0 else FLAG)
    share = (mm.team1[k] == mm.bat1[k]).mean()
    log.add("C07", "Semantics", "team1 column always = team batting first?", f"only {share:.1%} of matches",
            FLAG, "team1/team2 are NOT batting order; derive batting-first team from deliveries")
    ev["team1_bats_first_share"] = share

    # ---- Delivery-level consistency ----
    tbad = int((d.total_runs != d.batsman_runs + d.extra_runs).sum())
    log.add("D01", "Runs", "total_runs == batsman_runs + extra_runs", f"{tbad} mismatches", PASS if tbad == 0 else FLAG)
    ex_none_bad = int(((d.extras_type.isna()) & (d.extra_runs != 0)).sum())
    ex_zero_bad = int(((d.extras_type.notna()) & (d.extra_runs == 0)).sum())
    log.add("D02", "Runs", "extra_runs > 0 exactly when extras_type is present",
            f"{ex_none_bad} extras w/o type, {ex_zero_bad} type w/o runs", PASS if ex_none_bad + ex_zero_bad == 0 else FLAG)
    wb = int(((d.extras_type == "wides") & (d.batsman_runs > 0)).sum())
    log.add("D03", "Runs", "No batter runs credited on wides", wb, PASS if wb == 0 else FLAG)
    byes_bat = int((d.extras_type.isin(["byes", "legbyes"]) & (d.batsman_runs > 0)).sum())
    log.add("D04", "Runs", "No batter runs on bye/leg-bye deliveries", byes_bat, PASS if byes_bat == 0 else FLAG)
    nb_bat = int(((d.extras_type == "noballs") & (d.batsman_runs > 0)).sum())
    log.add("D05", "Runs", "No-balls where the batter also scored off the bat", nb_bat, INFO,
            "Legitimate: runs off a no-ball count for the batter")
    pen = d[d.extras_type == "penalty"]
    log.add("D06", "Runs", "Penalty-run deliveries", len(pen), INFO,
            "Penalty runs go to team total only - not batter, not bowler")
    five = int((d.batsman_runs == 5).sum())
    log.add("D07", "Runs", "Deliveries with batsman_runs == 5", five, INFO,
            "Plausible (e.g. 1 run + 4 overthrows); keep")
    wk_bad = int(((d.is_wicket == 1) != d.player_dismissed.notna()).sum())
    log.add("D08", "Wickets", "is_wicket == 1 exactly when player_dismissed present", wk_bad, PASS if wk_bad == 0 else FLAG)
    dk_bad = int(((d.is_wicket == 1) != d.dismissal_kind.notna()).sum())
    log.add("D09", "Wickets", "is_wicket == 1 exactly when dismissal_kind present", dk_bad, PASS if dk_bad == 0 else FLAG)
    w = d[d.is_wicket == 1]
    off = int((~((w.player_dismissed == w.batter) | (w.player_dismissed == w.non_striker))).sum())
    log.add("D10", "Wickets", "Dismissed player is the striker or non-striker", f"{off} exceptions", PASS if off == 0 else FLAG)
    nonbowl = int(w.dismissal_kind.isin(cfg.NON_BOWLER_DISMISSALS).sum())
    log.add("D11", "Wickets", "is_wicket rows that are NOT bowler wickets (run out, retired, obstructing)", nonbowl, INFO,
            "is_wicket cannot be summed directly for bowler wickets")
    rh = int((d.dismissal_kind == "retired hurt").sum())
    log.add("D12", "Wickets", "'retired hurt' flagged as is_wicket = 1", rh, FLAG if rh else PASS,
            "Retired hurt is NOT a dismissal (batter is not out)")
    cw = int(((d.dismissal_kind.isin(["caught", "stumped"])) & d.fielder.isna()).sum())
    log.add("D13", "Wickets", "Caught/stumped dismissals missing fielder", cw, PASS if cw == 0 else FLAG)
    wi = d[~d.dismissal_kind.isin(cfg.NOT_OUT_DISMISSALS)].groupby(["match_id", "inning"]).is_wicket.sum()
    log.add("D14", "Wickets", "Innings with more than 10 wickets", int((wi > 10).sum()), PASS if (wi > 10).sum() == 0 else FLAG)

    # ---- Over / ball structure ----
    log.add("O01", "Overs", "over range (0-indexed)", f"{d.over.min()}..{d.over.max()}",
            PASS if d.over.between(0, 19).all() else FLAG, "over 0 = 1st over")
    log.add("O02", "Overs", "ball range (delivery sequence within over incl. extras)", f"{d.ball.min()}..{d.ball.max()}", INFO,
            "ball > 6 occurs because wides/no-balls are re-bowled")
    bc = d.groupby(["match_id", "inning", "over"]).agg(n=("ball", "size"), mx=("ball", "max"))
    gaps = int((bc.n != bc.mx).sum())
    log.add("O03", "Overs", "Ball numbering continuous within every over (1..n)", f"{gaps} overs with gaps", PASS if gaps == 0 else FLAG)
    og = d[d.inning <= 2].groupby(["match_id", "inning"]).over.agg(["nunique", "max"])
    og_bad = int((og["nunique"] != og["max"] + 1).sum())
    log.add("O04", "Overs", "No missing overs within regulation innings", og_bad, PASS if og_bad == 0 else FLAG)
    legal = ~d.extras_type.isin(cfg.ILLEGAL_DELIVERY_EXTRAS)
    po = d.assign(legal=legal).groupby(["match_id", "inning", "over"]).legal.sum()
    ev["legal_balls_per_over"] = po.value_counts().sort_index().to_dict()
    seven = po[po > 6]
    log.add("O05", "Overs", "Overs with more than 6 legal deliveries", len(seven), FLAG if len(seven) else PASS,
            "Source shows 7 legal balls; likely umpire miscount or scoring error - keep as recorded, document")
    ev["seven_ball_overs"] = seven.reset_index()[["match_id", "inning", "over"]]
    zero = po[po == 0]
    log.add("O06", "Overs", "Overs containing zero legal deliveries", len(zero), INFO,
            "Final over of a chase ended by a wide/no-ball")
    inn = d.groupby("match_id").inning.max().value_counts().sort_index().to_dict()
    log.add("O07", "Innings", "Max inning per match (1=abandoned early, 2=normal, 4/6=super over(s))", str(inn), INFO)

    # ---- Names / standardisation ----
    teams = sorted(set(m.team1) | set(m.team2))
    log.add("N01", "Names", "Distinct team-name strings", len(teams), FLAG,
            "Includes renamed franchises and spelling variants - see team_name_eras.csv")
    log.add("N02", "Names", "Distinct venue strings", m.venue.nunique(), FLAG,
            "Same ground appears under several names - see venue_name_variants.csv")
    cities = set(m.city.dropna())
    log.add("N03", "Names", "City spelling variants (Bangalore/Bengaluru)",
            str(sorted(c for c in cities if c in {"Bangalore", "Bengaluru"})), FLAG if {"Bangalore", "Bengaluru"} <= cities else PASS)
    people = pd.unique(pd.concat([d.batter, d.bowler, d.non_striker, d.player_dismissed.dropna(),
                                  d.fielder.dropna(), m.player_of_match.dropna()]))
    norm = pd.Series(people).map(lambda s: re.sub(r"[^a-z]", "", s.lower()))
    coll = pd.Series(people).groupby(norm).agg(list)
    coll = coll[coll.map(len) > 1].tolist()
    log.add("N04", "Names", "Player names differing only by case/punctuation/digits", str(coll), INFO,
            "'Arshad Khan (2)' is the source's deliberate disambiguation of a different player - do NOT merge")
    ws = sum(p != p.strip() or "  " in p for p in people)
    log.add("N05", "Names", "Player names with stray whitespace", ws, PASS if ws == 0 else FLAG)
    subs = sorted(set(d.fielder.dropna()) - set(d.batter) - set(d.bowler) - set(d.non_striker))
    log.add("N06", "Names", "Fielders who never batted or bowled (substitute fielders)", len(subs), INFO, ", ".join(subs))
    ev["people"] = len(people)
    return log.frame(), ev


# --------------------------------------------------------------------------- #
# Coverage tables
# --------------------------------------------------------------------------- #
def season_coverage(m: pd.DataFrame, d: pd.DataFrame) -> pd.DataFrame:
    dt = pd.to_datetime(m["date"])
    balls = d.groupby("match_id").size()
    cov = (m.assign(date=dt, year=dt.dt.year, balls=m["id"].map(balls))
             .groupby("season", sort=False)
             .agg(calendar_year=("year", "first"), matches=("id", "size"),
                  first_match=("date", "min"), last_match=("date", "max"),
                  teams=("team1", lambda s: len(set(s) | set(m.loc[s.index, "team2"]))),
                  venues=("venue", "nunique"), deliveries=("balls", "sum"),
                  no_result=("result", lambda s: int((s == "no result").sum())),
                  ties_super_over=("super_over", lambda s: int((s == "Y").sum())),
                  dls_matches=("method", lambda s: int(s.notna().sum())))
             .sort_values("calendar_year").reset_index())
    for c in ["first_match", "last_match"]:
        cov[c] = cov[c].dt.date
    return cov


def team_eras(m: pd.DataFrame) -> pd.DataFrame:
    dt = pd.to_datetime(m["date"]).dt.year
    long = pd.concat([pd.DataFrame({"team": m.team1, "year": dt, "id": m.id}),
                      pd.DataFrame({"team": m.team2, "year": dt, "id": m.id})])
    return (long.groupby("team").agg(first_year=("year", "min"), last_year=("year", "max"),
                                     matches=("id", "nunique"))
                .sort_values(["first_year", "team"]).reset_index())


def venue_variants(m: pd.DataFrame) -> pd.DataFrame:
    """Group venue strings by their base name (text before the first comma, normalised)."""
    base = (m.venue.str.split(",").str[0].str.replace(".", " ", regex=False)
            .str.replace(r"\s+", " ", regex=True).str.strip().str.lower())
    g = (m.assign(base=base).groupby(["base", "venue"]).agg(matches=("id", "size"),
                                                         cities=("city", lambda s: ", ".join(sorted(s.dropna().unique()))))
          .reset_index())
    g["variants_for_base"] = g.groupby("base")["venue"].transform("size")
    return g.sort_values(["variants_for_base", "base"], ascending=[False, True])


# --------------------------------------------------------------------------- #
# Report writers
# --------------------------------------------------------------------------- #
def md_table(df: pd.DataFrame) -> str:
    """Render a DataFrame as a GitHub markdown table (no extra dependency)."""
    def cell(v):
        if v is None or (isinstance(v, float) and np.isnan(v)):
            return ""
        return str(v).replace("|", "\\|").replace("\n", " ")
    cols = [str(c) for c in df.columns]
    out = ["| " + " | ".join(cols) + " |", "|" + "|".join(["---"] * len(cols)) + "|"]
    out += ["| " + " | ".join(cell(v) for v in row) + " |" for row in df.itertuples(index=False)]
    return "\n".join(out)


def write_profiling_report(m, d, prof_m, prof_d, cov, eras, venues, files, ev):
    dt = pd.to_datetime(m["date"])
    reg = d[d.inning <= 2]
    legal = ~reg.extras_type.isin(cfg.ILLEGAL_DELIVERY_EXTRAS)
    lines = [
        "# Phase 1 - Dataset Profiling Report",
        "",
        f"_Generated by `python/01_data_profiling.py` on {datetime.now():%Y-%m-%d %H:%M}. "
        "All numbers below are computed directly from the raw files; nothing is hand-typed._",
        "",
        "## 1. Source files",
        "",
        md_table(pd.DataFrame([{"file": k, **v} for k, v in files.items()])),
        "",
        "## 2. Shape",
        "",
        md_table(pd.DataFrame([
            {"dataset": "matches.csv", "rows": len(m), "columns": m.shape[1], "grain": "one row per match"},
            {"dataset": "deliveries.csv", "rows": len(d), "columns": d.shape[1], "grain": "one row per ball bowled (incl. wides/no-balls and super-over balls)"},
        ])),
        "",
        "## 3. Coverage",
        "",
        f"- **Date range:** {dt.min().date()} to {dt.max().date()}",
        f"- **Seasons:** {m.season.nunique()} (IPL {dt.dt.year.min()} - {dt.dt.year.max()})",
        f"- **Matches:** {m.id.nunique()} (all with ball-by-ball data)",
        f"- **Franchise name strings:** {len(set(m.team1) | set(m.team2))} (see section 6 - fewer real franchises)",
        f"- **Venue strings:** {m.venue.nunique()} | **City strings:** {m.city.nunique()} (+{int(m.city.isna().sum())} missing)",
        f"- **Distinct people in ball-by-ball data:** {ev['people']} "
        f"(batters {d.batter.nunique()}, bowlers {d.bowler.nunique()})",
        f"- **Umpires:** {pd.concat([m.umpire1, m.umpire2]).nunique()}",
        f"- **Regulation-innings deliveries:** {len(reg):,} ({int(legal.sum()):,} legal) | "
        f"**super-over deliveries:** {int((d.inning > 2).sum())}",
        f"- **Total runs (regulation innings):** {int(reg.total_runs.sum()):,}",
        "",
        "### Season coverage",
        "",
        md_table(cov),
        "",
        "## 4. Column profile - matches.csv",
        "",
        md_table(prof_m.drop(columns=["row_count"])),
        "",
        "## 5. Column profile - deliveries.csv",
        "",
        md_table(prof_d.drop(columns=["row_count"])),
        "",
        "## 6. Team-name strings and the years they appear",
        "",
        md_table(eras),
        "",
        "## 7. Venue strings grouped by base name",
        "",
        "Only base names with more than one spelling are shown.",
        "",
        md_table(venues[venues.variants_for_base > 1].drop(columns=["variants_for_base"])),
        "",
        "## 8. Categorical value distributions",
        "",
    ]
    for col, df in [("match_type", m), ("result", m), ("toss_decision", m), ("super_over", m), ("method", m)]:
        lines += [f"**matches.{col}**", "", md_table(df[col].value_counts(dropna=False).rename_axis(col).reset_index()), ""]
    for col in ["inning", "extras_type", "dismissal_kind", "batsman_runs", "extra_runs"]:
        lines += [f"**deliveries.{col}**", "", md_table(d[col].value_counts(dropna=False).sort_index().rename_axis(col).reset_index()), ""]
    lines += ["**Legal deliveries per over (all innings)**", "",
              md_table(pd.Series(ev["legal_balls_per_over"]).rename_axis("legal_balls").rename("overs").reset_index()), ""]
    (cfg.PROFILING_DIR / "dataset_profiling_report.md").write_text("\n".join(lines), encoding="utf-8")


def write_quality_report(checks: pd.DataFrame, ev: dict):
    counts = checks.status.value_counts().to_dict()
    lines = [
        "# Phase 1 - Initial Data-Quality Report",
        "",
        f"_Generated by `python/01_data_profiling.py` on {datetime.now():%Y-%m-%d %H:%M}._",
        "",
        "Status meaning: **PASS** = rule holds on every row; **FLAG** = issue to resolve or document in Phase 2; "
        "**INFO** = legitimate cricket behaviour that analysis must account for.",
        "",
        f"**Summary:** {counts.get('PASS', 0)} PASS | {counts.get('FLAG', 0)} FLAG | {counts.get('INFO', 0)} INFO "
        f"(total {len(checks)} checks)",
        "",
        md_table(checks),
        "",
        "## Overs recorded with 7 legal deliveries",
        "",
        md_table(ev["seven_ball_overs"]),
        "",
    ]
    (cfg.VALIDATION_DIR / "phase1_initial_data_quality_report.md").write_text("\n".join(lines), encoding="utf-8")


# --------------------------------------------------------------------------- #
def main():
    for p in [cfg.PROFILING_DIR, cfg.VALIDATION_DIR]:
        p.mkdir(parents=True, exist_ok=True)

    files = verify_raw_files()
    print("[ok] raw files present and SHA-256 verified")

    m, d = load_raw()
    mt, dt_ = load_raw_as_text()
    print(f"[ok] loaded matches {m.shape}, deliveries {d.shape}")

    prof_m, prof_d = column_profile(m, mt), column_profile(d, dt_)
    prof_m.to_csv(cfg.PROFILING_DIR / "column_profile_matches.csv", index=False)
    prof_d.to_csv(cfg.PROFILING_DIR / "column_profile_deliveries.csv", index=False)

    cov, eras, venues = season_coverage(m, d), team_eras(m), venue_variants(m)
    cov.to_csv(cfg.PROFILING_DIR / "season_coverage.csv", index=False)
    eras.to_csv(cfg.PROFILING_DIR / "team_name_eras.csv", index=False)
    venues.to_csv(cfg.PROFILING_DIR / "venue_name_variants.csv", index=False)

    checks, ev = run_checks(m, d)
    checks.to_csv(cfg.VALIDATION_DIR / "phase1_data_quality_checks.csv", index=False)

    write_profiling_report(m, d, prof_m, prof_d, cov, eras, venues, files, ev)
    write_quality_report(checks, ev)

    print(checks.status.value_counts().to_string())
    flags = checks[checks.status == "FLAG"]
    print("\nFLAGGED checks:")
    print(flags[["check_id", "check", "observed"]].to_string(index=False))
    print("\n[ok] reports written to reports/profiling and reports/validation")


if __name__ == "__main__":
    main()
