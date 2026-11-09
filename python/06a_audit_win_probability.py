"""
Phase 6a - Publication audit of the Phase 5 in-chase win-probability model
==========================================================================

Decides whether the model may appear on the Power BI dashboard. Audit items:
  1. Feature availability at prediction time (rebuild states using ONLY balls bowled so far).
  2. Target leakage (features exclude outcome fields; no future balls used).
  3. Evaluation on unseen seasons (train <= 2021, test >= 2022, no shared match).
  4. Calibration on held-out matches (deciles, calibration-in-the-large per test season, ECE).
  5. Uncertainty that respects within-match correlation: cluster (match-level) bootstrap.
  6. Independence check: evaluate on ONE state per match (end of over 10).

Outputs: reports/powerbi/win_probability_audit.md, reports/powerbi/win_probability_audit_checks.csv
Run:     python python/06a_audit_win_probability.py
"""
from __future__ import annotations

import sys
from datetime import datetime
from importlib import import_module
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, roc_auc_score

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ipl_config as cfg  # noqa: E402

adv = import_module("05_advanced_analytics")
md_table = import_module("01_data_profiling").md_table
OUT = cfg.REPORTS_DIR / "powerbi"
FEATS = ["rrr", "wickets_in_hand", "log_balls_left", "runs_needed"]
OUTCOME_FIELDS = {"chase_won", "winner", "result", "result_for", "result_margin", "win_type", "inn2_runs",
                  "inn2_wickets", "inn2_legal_balls"}
RNG = np.random.default_rng(6)
B = 1000


def prep(st):
    st = st[st.over_number <= 19].copy()
    st["rrr"] = st.rrr.clip(upper=36)
    st["log_balls_left"] = np.log(st.balls_left)
    return st


def ece(p, y, bins=10):
    df = pd.DataFrame({"p": p, "y": y})
    df["b"] = pd.cut(df.p, np.linspace(0, 1, bins + 1), include_lowest=True)
    g = df.groupby("b", observed=True).agg(n=("y", "size"), p=("p", "mean"), y=("y", "mean"))
    return float((g.n * (g.p - g.y).abs()).sum() / g.n.sum())


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    A = adv.Adv()
    st = prep(A.states)
    checks = []

    def add(cid, item, check, result, ok, note=""):
        checks.append({"check_id": cid, "audit_item": item, "check": check, "result": result,
                       "status": "PASS" if ok else "FAIL", "note": note})

    # 1. feature availability: rebuild 300 random states from balls bowled up to that point only
    reg = A.reg[(A.reg.inning == 2)].sort_values("delivery_id")
    sample = st.sample(300, random_state=1)
    mism = 0
    for _, s in sample.iterrows():
        balls = reg[(reg.match_id == s.match_id) & (reg.over_number <= s.over_number)]
        runs, legal, outs = balls.total_runs.sum(), balls.is_legal_delivery.sum(), balls.is_player_out.sum()
        if not (s.target_runs - runs == s.runs_needed and max(0, 120 - legal) == s.balls_left and 10 - outs == s.wickets_in_hand):
            mism += 1
    add("W01", "Prediction-time availability", "300 random states rebuilt from balls bowled so far (no later balls)",
        f"{300 - mism}/300 identical", mism == 0)
    add("W02", "Prediction-time availability", "Target known at chase start (target_runs = inn1 runs + 1, non-D/L)",
        "all states non-D/L, target fixed", bool((A.chase_matches.target_runs == A.chase_matches.inn1_runs + 1).all()))
    # 2. leakage
    leak = sorted(set(FEATS) & OUTCOME_FIELDS)
    add("W03", "Target leakage", "Model features contain no outcome fields", f"features = {FEATS}; overlap = {leak}", not leak)
    add("W04", "Target leakage", "States after the chase is decided excluded (runs needed > 0, wickets > 0, balls > 0)",
        f"{len(st):,} live states", bool((st.runs_needed > 0).all() and (st.wickets_in_hand > 0).all() and (st.balls_left > 0).all()))
    # 3. unseen seasons
    tr, te = st[st.season_year <= 2021], st[st.season_year >= 2022]
    shared = set(tr.match_id) & set(te.match_id)
    add("W05", "Unseen seasons", "Train 2008-21 / test 2022-24, no match in both", f"train {tr.match_id.nunique()} / test "
        f"{te.match_id.nunique()} matches; shared {len(shared)}", not shared)
    m = LogisticRegression(max_iter=2000).fit(tr[FEATS], tr.chase_won)
    te = te.assign(p=m.predict_proba(te[FEATS])[:, 1])
    te["bin"] = pd.cut(te.p, np.linspace(0, 1, 11), include_lowest=True)
    base = tr.chase_won.mean()
    # 4. calibration
    e = ece(te.p, te.chase_won)
    cil = te.groupby("season_year").agg(states=("p", "size"), mean_pred=("p", "mean"), observed=("chase_won", "mean"))
    cil["gap_pp"] = (cil.mean_pred - cil.observed) * 100
    add("W06", "Calibration", "Expected calibration error on held-out states (<= 0.05)", f"ECE = {e:.3f}", e <= 0.05)
    add("W07", "Calibration", "Calibration-in-the-large per test season within +/-5 pp",
        "; ".join(f"{y}: {g:+.1f} pp" for y, g in cil.gap_pp.items()), bool((cil.gap_pp.abs() <= 5).all()))
    # 5. cluster bootstrap by match
    ids = te.match_id.unique()
    by = {k: g for k, g in te.groupby("match_id")}
    stats_ = []
    for _ in range(B):
        samp = pd.concat([by[i] for i in RNG.choice(ids, len(ids), replace=True)])
        b_m = brier_score_loss(samp.chase_won, samp.p)
        b_0 = brier_score_loss(samp.chase_won, np.full(len(samp), base))
        stats_.append((b_m, b_0 - b_m, roc_auc_score(samp.chase_won, samp.p), ece(samp.p, samp.chase_won)))
    bs = pd.DataFrame(stats_, columns=["brier", "brier_gain_vs_base", "auc", "ece"])
    ci = bs.quantile([0.025, 0.975])
    point = {"brier": brier_score_loss(te.chase_won, te.p),
             "brier_gain_vs_base": brier_score_loss(te.chase_won, np.full(len(te), base)) - brier_score_loss(te.chase_won, te.p),
             "auc": roc_auc_score(te.chase_won, te.p), "ece": e}
    unc = pd.DataFrame({"metric": list(point), "point": list(point.values()),
                        "ci_low (match-cluster bootstrap)": ci.loc[0.025].values, "ci_high": ci.loc[0.975].values})
    add("W08", "Uncertainty (match-clustered)", f"Brier improvement over base rate: 95% cluster-bootstrap CI excludes 0 ({B} resamples)",
        f"{point['brier_gain_vs_base']:.3f} (CI {ci.loc[0.025, 'brier_gain_vs_base']:.3f} to {ci.loc[0.975, 'brier_gain_vs_base']:.3f})",
        ci.loc[0.025, "brier_gain_vs_base"] > 0)
    add("W09", "Uncertainty (match-clustered)", "Upper 95% bound of ECE <= 0.07",
        f"ECE CI {ci.loc[0.025, 'ece']:.3f}-{ci.loc[0.975, 'ece']:.3f}", ci.loc[0.975, "ece"] <= 0.07)
    # calibration deciles with cluster-bootstrap CIs of observed rate
    cal = te.groupby("bin", observed=True).agg(states=("p", "size"), matches=("match_id", "nunique"),
                                               mean_pred=("p", "mean"), observed=("chase_won", "mean")).reset_index()
    obs_boot = []
    for _ in range(300):
        samp = pd.concat([by[i] for i in RNG.choice(ids, len(ids), replace=True)])
        obs_boot.append(samp.groupby("bin", observed=True).chase_won.mean())
    ob = pd.concat(obs_boot, axis=1)
    cal["obs_ci_low"] = ob.quantile(0.025, axis=1).values
    cal["obs_ci_high"] = ob.quantile(0.975, axis=1).values
    cal["pred_inside_ci"] = (cal.mean_pred >= cal.obs_ci_low) & (cal.mean_pred <= cal.obs_ci_high)
    cal["bin"] = cal.bin.astype(str)
    add("W10", "Calibration", "Mean prediction inside the match-clustered 95% CI of the observed rate (deciles with >= 30 matches)",
        f"{int(cal[cal.matches >= 30].pred_inside_ci.sum())}/{int((cal.matches >= 30).sum())} deciles",
        bool(cal[cal.matches >= 30].pred_inside_ci.all()))
    # 6. one state per match
    o10 = te[te.over_number == 10]
    auc10, br10 = roc_auc_score(o10.chase_won, o10.p), brier_score_loss(o10.chase_won, o10.p)
    br10_base = brier_score_loss(o10.chase_won, np.full(len(o10), base))
    add("W11", "Independence", "One state per match (end of over 10): model beats base rate", f"n={len(o10)} matches; AUC {auc10:.3f}; "
        f"Brier {br10:.3f} vs base {br10_base:.3f}", br10 < br10_base)
    chk = pd.DataFrame(checks)
    chk.to_csv(OUT / "win_probability_audit_checks.csv", index=False)
    passed = (chk.status == "PASS").all()
    decision = ("APPROVED for dashboard publication as an illustrative, historically-calibrated chase win-probability "
                "visual (with caveats)." if passed else "NOT APPROVED - excluded from the dashboard; historical C2 analytics used instead.")
    lines = ["# Win-Probability Model - Publication Audit (Phase 6)", "",
             f"_Generated by `python/06a_audit_win_probability.py` on {datetime.now():%Y-%m-%d %H:%M}._", "",
             f"**Decision: {decision}**", "",
             f"Model: logistic regression on {FEATS}; trained on 2008-21 chase states ({len(tr):,} states, "
             f"{tr.match_id.nunique()} matches), tested on 2022-24 ({len(te):,} states, {te.match_id.nunique()} matches).", "",
             "## Audit checks", "", md_table(chk), "",
             "## Held-out performance with match-clustered 95% intervals", "", md_table(unc.round(4)), "",
             "## Calibration-in-the-large by test season", "", md_table(cil.reset_index().round(4)), "",
             "## Calibration deciles (held-out)", "", md_table(cal.round(3)), "",
             "## Conditions of use on the dashboard", "",
             "- Shown as an **illustrative historical estimate** for a user-chosen situation, never as a forecast of a real match.",
             "- Label: 'Share of comparable historical chases won (model-smoothed)'. No betting or selection use.",
             "- Only for full 20-over, non-D/L chases; ignores team, venue and player strength.",
             "- Re-run this audit before refreshing the model with new seasons (era shift risk).", ""]
    (OUT / "win_probability_audit.md").write_text("\n".join(lines), encoding="utf-8")
    print(chk[["check_id", "check", "result", "status"]].to_string(index=False, max_colwidth=70))
    print("\n" + unc.round(4).to_string(index=False))
    print("\n" + cil.round(4).to_string())
    print("\nDECISION:", decision)
    # coefficients for DAX/Power BI implementation (if approved)
    coef = pd.DataFrame({"term": ["intercept"] + FEATS, "value": [m.intercept_[0], *m.coef_[0]]})
    coef.to_csv(OUT / "win_probability_coefficients.csv", index=False)
    print(coef.to_string(index=False))


if __name__ == "__main__":
    main()
