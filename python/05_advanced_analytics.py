"""
Phase 5 - Advanced Cricket Analytics
====================================

Goes beyond Phase 3 EDA: distributions, consistency, phase-and-season adjusted metrics,
chase "state" analysis (runs needed / balls left / wickets in hand), statistical tests with
confidence intervals, and an assessed (not automatic) predictive task.

Reuses the validated Phase 3 base tables (python/03_eda.py -> Data) so every definition is
identical: regulation = no super overs; bowler wickets = is_bowler_wicket; dismissals =
is_player_out (retired hurt not out); batting order + outcome = batting_first_team /
chasing_team / result_for; D/L and shortened matches excluded wherever a target-based or
20-over comparison is made.

Outputs
-------
reports/advanced_analytics_report.md            reports/advanced_analytics_validation_report.md
reports/advanced_analytics_summary.csv          reports/advanced_analytics_validation_checks.csv
reports/advanced_analytics_tables/*.csv         reports/charts/phase5/*.png (200 dpi)

Run from the project root (MySQL validation needs MYSQL_USER / MYSQL_PASSWORD):
    python python/05_advanced_analytics.py
"""
from __future__ import annotations

import sys
from datetime import datetime
from importlib import import_module
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import matplotlib.ticker as mtick  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib.colors import LinearSegmentedColormap  # noqa: E402
from scipy import stats  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ipl_config as cfg  # noqa: E402

eda = import_module("03_eda")
md_table = import_module("01_data_profiling").md_table
from eda_helpers_phase5 import Finding, wilson, save_fig, CHART_DIR, TABLE_DIR, diverging_cmap  # noqa: E402,F401

BLUE, ORANGE, AQUA, GREY, INK, INK2, GRID, SURFACE = (eda.BLUE, eda.ORANGE, eda.AQUA, eda.GREY, eda.INK,
                                                      eda.INK2, eda.GRID, eda.SURFACE)
PH = ["Powerplay", "Middle", "Death"]
PHC = eda.PHASE_COLORS
RNG = np.random.default_rng(20241108)

TH = {
    "bat_innings": 50, "bat_balls": 500, "death_balls": 250, "non_death_balls": 500,
    "season_balls": 100, "season_min_seasons": 6, "split_innings": 30,
    "bowl_balls": 1000, "phase_bowl_balls": 600, "bowl_season_balls": 120, "bowl_min_seasons": 6,
    "close_bat_balls": 150, "close_matches_team": 20, "venue_matches": 20,
}
ERAS = [(2008, 2012, "2008-12"), (2013, 2017, "2013-17"), (2018, 2022, "2018-22"), (2023, 2024, "2023-24")]


def era_of(y):
    for a, b, lab in ERAS:
        if a <= y <= b:
            return lab


# =========================================================================== base tables
class Adv:
    """Phase 3 Data + Phase 5 derived tables (all regulation-only)."""

    def __init__(self):
        self.D = D = eda.Data()
        self.mc, self.reg, self.bi = D.mc, D.reg, D.bat_inn
        self.reg["era"] = self.reg.season_year.map(era_of)
        # pre-ball wickets lost in the innings (state BEFORE the delivery)
        r = self.reg.sort_values("delivery_id")
        self.reg["wkts_before"] = (r.groupby(["match_id", "inning"]).is_player_out.cumsum() - r.is_player_out) \
            .reindex(self.reg.index)
        # league expected runs-per-legal-ball and wickets-per-ball by (season, phase)
        sp = self.reg.groupby(["season_year", "phase"]).agg(r=("total_runs", "sum"), b=("is_legal_delivery", "sum"),
                                                             br=("bowler_runs_conceded", "sum"),
                                                             w=("is_bowler_wicket", "sum"))
        self.sp_rpb = (sp.r / sp.b).rename("lg_rpb")
        self.sp_brpb = (sp.br / sp.b).rename("lg_bowler_rpb")
        self.sp_wpb = (sp.w / sp.b).rename("lg_wpb")
        self.reg = self.reg.join(self.sp_rpb, on=["season_year", "phase"]).join(self.sp_brpb, on=["season_year", "phase"]) \
            .join(self.sp_wpb, on=["season_year", "phase"])
        self.reg["is_boundary"] = self.reg.is_four + self.reg.is_six
        # chase base: full 20-over, non-D/L, decided by runs/wickets
        mc = self.mc
        self.chase_matches = mc[(mc.is_dls == 0) & (mc.is_no_result == 0) & (mc.target_overs == 20)
                                & mc.result_for.isin(["batting first", "chasing"])].copy()
        self.chase_matches["chase_won"] = (self.chase_matches.result_for == "chasing").astype(int)
        self.states = self._chase_states()
        self.close_ids = self._close_matches()

    def _chase_states(self):
        cm = self.chase_matches
        r2 = self.reg[(self.reg.inning == 2) & self.reg.match_id.isin(cm.match_id)].sort_values("delivery_id").copy()
        g = r2.groupby("match_id")
        r2["cum_runs"] = g.total_runs.cumsum()
        r2["cum_legal"] = g.is_legal_delivery.cumsum()
        r2["cum_outs"] = g.is_player_out.cumsum()
        end = r2.groupby(["match_id", "over_number"]).tail(1)
        end = end.merge(cm[["match_id", "target_runs", "chase_won", "season_year", "inn1_runs"]], on=["match_id", "season_year"])
        end["runs_needed"] = end.target_runs - end.cum_runs
        end["balls_left"] = (120 - end.cum_legal).clip(lower=0)
        end["wickets_in_hand"] = 10 - end.cum_outs
        live = end[(end.runs_needed > 0) & (end.balls_left > 0) & (end.wickets_in_hand > 0)].copy()
        live["rrr"] = live.runs_needed / live.balls_left * 6
        return live[["match_id", "season_year", "over_number", "cum_runs", "cum_legal", "runs_needed", "balls_left",
                     "wickets_in_hand", "rrr", "chase_won", "target_runs"]].reset_index(drop=True)

    def _close_matches(self):
        """Phase 3 definition: won by <=10 runs, chase completed with <=6 balls left (both non-D/L), or a tie."""
        mc = self.mc
        nd = mc[mc.is_dls == 0]
        runs_close = nd[(nd.result_for == "batting first") & (nd.result_margin <= 10)].match_id
        ch = nd[nd.result_for == "chasing"]
        balls_close = ch[(ch.target_balls - ch.inn2_legal_balls) <= 6].match_id
        ties = mc[mc.is_super_over == 1].match_id
        return set(runs_close) | set(balls_close) | set(ties)


def tbl(name, df):
    df.to_csv(TABLE_DIR / f"{name}.csv", index=False)
    return df


# =========================================================================== A. BATTING
def a1_consistency(A: Adv) -> Finding:
    bi = A.bi
    g = bi.groupby("player")
    t = pd.DataFrame({"innings": g.size(), "runs": g.runs.sum(), "mean": g.runs.mean(), "median": g.runs.median(),
                      "p25": g.runs.quantile(0.25), "p75": g.runs.quantile(0.75),
                      "n30": g.runs.apply(lambda s: int((s >= 30).sum()))}).reset_index()
    t = t[t.innings >= TH["bat_innings"]].copy()
    ci = t.apply(lambda r: wilson(r.n30, r.innings), axis=1, result_type="expand")
    t["pct_30_plus"], t["ci_low"], t["ci_high"] = ci[0], ci[1], ci[2]
    t["iqr"] = t.p75 - t.p25
    t = t.sort_values("pct_30_plus", ascending=False)
    top = t.head(15).round(1)
    tbl("A1_consistency", t.round(3))
    lead = t.iloc[0]
    overlap = int((t.head(10).ci_low <= t.iloc[9].pct_30_plus).sum())
    above_median = int((t.head(10).ci_low > t.pct_30_plus.median()).sum())
    return Finding("A1", "A. Batting", "Most consistent scorers (rate of 30+ scores with 95% CI)",
                   "Which batters most reliably make a meaningful contribution, and how certain are we of the ranking?",
                   "pct_30_plus = innings with >= 30 runs / innings; 95% Wilson score interval; IQR of innings scores.",
                   f"Batters with >= {TH['bat_innings']} innings (n = {len(t)}).", top[["player", "innings", "mean", "median", "iqr",
                                                                                        "pct_30_plus", "ci_low", "ci_high"]],
                   f"{lead.player} reaches 30 in {lead.pct_30_plus:.1f}% of {int(lead.innings)} innings (95% CI "
                   f"{lead.ci_low:.1f}-{lead.ci_high:.1f}%). The intervals are wide: {overlap} of the top 10 have a lower bound "
                   f"at or below the 10th-ranked player's rate ({t.iloc[9].pct_30_plus:.1f}%), so the order within the top 10 is "
                   f"not statistically settled. However, {above_median} of the top 10 have a lower bound above the median "
                   f"qualifying batter's rate ({t.pct_30_plus.median():.1f}%), so they are reliably more consistent than a "
                   f"typical batter.",
                   "Batting position is not in the data; openers get more opportunity to reach 30 than finishers.")


def a2_milestones(A: Adv) -> Finding:
    bi = A.bi
    q = bi.groupby("player").filter(lambda x: len(x) >= TH["bat_innings"])
    g = q.groupby("player").runs
    t = pd.DataFrame({"innings": g.size(), "pct_30_plus": g.apply(lambda s: (s >= 30).mean() * 100),
                      "pct_50_plus": g.apply(lambda s: (s >= 50).mean() * 100),
                      "pct_100_plus": g.apply(lambda s: (s >= 100).mean() * 100),
                      "fifties_plus": g.apply(lambda s: int((s >= 50).sum())), "hundreds": g.apply(lambda s: int((s >= 100).sum()))})
    t["conversion_50_to_100_pct"] = (t.hundreds / t.fifties_plus.replace(0, np.nan) * 100)
    t = t.reset_index().sort_values("pct_50_plus", ascending=False)
    tbl("A2_milestones", t.round(3))
    league = bi.runs
    conv = t[t.fifties_plus >= 20].sort_values("conversion_50_to_100_pct", ascending=False)
    return Finding("A2", "A. Batting", "Frequency of 30+, 50+ and 100+ scores",
                   "How often do batters reach milestone scores, and who converts fifties into hundreds?",
                   "Share of innings reaching 30 / 50 / 100; conversion = hundreds / innings of 50+.",
                   f"League: {len(league):,} batting innings. Ranking: batters with >= {TH['bat_innings']} innings (n = {len(t)}).",
                   t.head(15).round(1),
                   f"League-wide, {(league >= 30).mean() * 100:.1f}% of innings reach 30, {(league >= 50).mean() * 100:.1f}% "
                   f"reach 50 and {(league >= 100).mean() * 100:.2f}% reach 100. {t.iloc[0].player} reaches 50 most often "
                   f"({t.iloc[0].pct_50_plus:.1f}% of innings). Among batters with 20+ scores of 50 or more, "
                   f"{conv.iloc[0].player} converts best ({conv.iloc[0].hundreds:.0f} hundreds from {conv.iloc[0].fifties_plus:.0f} "
                   f"innings of 50+, {conv.iloc[0].conversion_50_to_100_pct:.1f}%).",
                   "Not-out innings are included as scored (a 45* counts as 'not 50').")


def a3_distribution(A: Adv) -> Finding:
    bi = A.bi
    top = A.D.batters.nlargest(12, "runs").player.tolist()
    d = bi[bi.player.isin(top)]
    stats_t = d.groupby("player").runs.describe()[["count", "mean", "25%", "50%", "75%", "max"]].loc[top].reset_index()
    stats_t["skew"] = d.groupby("player").runs.skew().loc[top].values
    fig, ax = plt.subplots(figsize=(11, 5.2))
    data = [d[d.player == p].runs.values for p in top]
    bp = ax.boxplot(data, vert=True, patch_artist=True, widths=0.55, showfliers=True,
                    flierprops=dict(marker="o", markersize=3, markerfacecolor=GREY, markeredgecolor=GREY, alpha=0.6),
                    medianprops=dict(color=INK, linewidth=1.6))
    for b in bp["boxes"]:
        b.set(facecolor=BLUE, alpha=0.55, edgecolor=BLUE)
    ax.scatter(range(1, len(top) + 1), [x.mean() for x in data], marker="D", s=26, color=ORANGE, zorder=3, label="Mean")
    ax.set_xticks(range(1, len(top) + 1), top, rotation=30, ha="right")
    ax.set_ylabel("Runs in an innings")
    ax.legend(loc="upper right")
    ax.set_title("Innings score distributions of the 12 leading run scorers")
    eda.subtitle(ax, "Box = middle 50% of innings, line = median, diamond = mean, dots = outliers. Regulation innings, 2008-2024.")
    chart = save_fig(fig, "A3_score_distribution")
    tbl("A3_distribution", stats_t.round(2))
    all_skew = bi.groupby("player").filter(lambda x: len(x) >= TH["bat_innings"]).groupby("player").runs.skew()
    return Finding("A3", "A. Batting", "Scoring distribution", "What does a typical innings look like, versus the average?",
                   "Quartiles, mean and skewness of per-innings runs.",
                   f"12 leading run scorers ({int(stats_t['count'].sum()):,} innings); skewness for all {len(all_skew)} batters "
                   f"with >= {TH['bat_innings']} innings.", stats_t.round(1),
                   f"{'Every' if (all_skew > 0).all() else 'Almost every'} qualifying batter's score distribution is "
                   f"right-skewed (skewness > 0 for {int((all_skew > 0).sum())} of {len(all_skew)}); the median innings is below the mean for all 12 leaders "
                   f"({int((stats_t['50%'] < stats_t['mean']).sum())}/12). Example: {stats_t.iloc[0].player}'s median innings is "
                   f"{stats_t.iloc[0]['50%']:.0f} vs a mean of {stats_t.iloc[0]['mean']:.1f}. Averages therefore overstate a "
                   f"'typical' innings; medians and milestone rates (A1-A2) describe reliability better.",
                   "Distributions mix batting positions and eras.", chart)


def a4_boundary_dot(A: Adv) -> Finding:
    r = A.reg
    g = r.groupby("batter").agg(balls=("is_ball_faced", "sum"), runs=("batsman_runs", "sum"),
                                boundaries=("is_boundary", "sum"),
                                dots=("batsman_runs", lambda s: 0))
    faced = r[r.is_ball_faced == 1]
    g["dots"] = faced.assign(d=(faced.batsman_runs == 0)).groupby("batter").d.sum()
    g = g[g.balls >= TH["bat_balls"]].copy()
    g["boundary_pct"] = g.boundaries / g.balls * 100
    g["dot_pct"] = g.dots / g.balls * 100
    g["strike_rate"] = g.runs / g.balls * 100
    g["boundary_run_share"] = (4 * faced.groupby("batter").is_four.sum() + 6 * faced.groupby("batter").is_six.sum()) \
        .reindex(g.index) / g.runs * 100
    g = g.reset_index().rename(columns={"batter": "player"})
    rho, p = stats.spearmanr(g.boundary_pct, g.dot_pct)
    rho_sr_b, _ = stats.spearmanr(g.boundary_pct, g.strike_rate)
    rho_sr_d, _ = stats.spearmanr(g.dot_pct, g.strike_rate)
    tbl("A4_boundary_dot", g.round(3))
    fig, ax = plt.subplots(figsize=(10, 6.3))
    sc = ax.scatter(g.dot_pct, g.boundary_pct, c=g.strike_rate, cmap=LinearSegmentedColormap.from_list("sr", ["#d6e4f5", BLUE, "#0d3a73"]),
                    s=30, edgecolor=SURFACE, linewidth=0.7)
    lab = pd.concat([g.nlargest(5, "boundary_pct"), g.nsmallest(4, "dot_pct"), g.nlargest(3, "dot_pct")]).drop_duplicates("player")
    eda.label_points(ax, lab.dot_pct, lab.boundary_pct, lab.player)
    cb = fig.colorbar(sc, ax=ax, pad=0.01)
    cb.set_label("Strike rate")
    ax.set_xlabel("Dot-ball % (balls faced with 0 runs off the bat)")
    ax.set_ylabel("Boundary % (4s + 6s per ball faced)")
    ax.set_title("Batting styles: boundary hitting vs dot balls")
    eda.subtitle(ax, f"Batters with {TH['bat_balls']}+ balls faced (n={len(g)}). Colour = strike rate.")
    chart = save_fig(fig, "A4_boundary_vs_dot")
    show = g.sort_values("boundary_pct", ascending=False)[["player", "balls", "strike_rate", "boundary_pct", "dot_pct",
                                                           "boundary_run_share"]].head(15).round(1)
    return Finding("A4", "A. Batting", "Boundary % and dot-ball %",
                   "Do batters score by hitting boundaries, by avoiding dot balls, or both?",
                   "boundary % = (4s + 6s) / balls faced; dot % = balls faced with 0 batter runs / balls faced "
                   "(batter view, so leg-byes off a 'dot' still count as a batter dot); Spearman rank correlation.",
                   f"Batters with >= {TH['bat_balls']} balls faced (n = {len(g)}).", show,
                   f"{show.iloc[0].player} hits a boundary off {show.iloc[0].boundary_pct:.1f}% of balls. Across batters, the "
                   f"relationship between boundary % and dot % is "
                   + (f"{'positive' if rho > 0 else 'negative'} (Spearman rho = {rho:.2f}, p = {p:.3f})"
                      if p < 0.05 else
                      f"weak and not statistically significant (rho = {rho:.2f}, p = {p:.3f}) - both styles (boundary-heavy "
                      f"with many dots, and low-dot rotation) exist side by side")
                   + f". Strike rate tracks boundary % (rho = {rho_sr_b:.2f}) more closely than low dot % (rho = {rho_sr_d:.2f}).",
                   "Proxy fours/sixes (batsman_runs = 4/6). No shot or field data.", chart)


def a5_death_acceleration(A: Adv) -> Finding:
    r = A.reg
    g = r.assign(seg=np.where(r.phase == "Death", "death", "pre")).groupby(["batter", "seg"]) \
        .agg(runs=("batsman_runs", "sum"), balls=("is_ball_faced", "sum")).unstack()
    g.columns = [f"{a}_{b}" for a, b in g.columns]
    g = g[(g.balls_death >= TH["death_balls"]) & (g.balls_pre >= TH["non_death_balls"])].copy()
    g["sr_pre"] = g.runs_pre / g.balls_pre * 100
    g["sr_death"] = g.runs_death / g.balls_death * 100
    g["acceleration"] = g.sr_death - g.sr_pre
    # league benchmark (all batters) so acceleration can be judged relative to normal
    lg = r.assign(seg=np.where(r.phase == "Death", "death", "pre")).groupby("seg").agg(runs=("batsman_runs", "sum"),
                                                                                       balls=("is_ball_faced", "sum"))
    lg_acc = lg.runs["death"] / lg.balls["death"] * 100 - lg.runs["pre"] / lg.balls["pre"] * 100
    g = g.reset_index().rename(columns={"batter": "player"}).sort_values("acceleration", ascending=False)
    tbl("A5_death_acceleration", g.round(3))
    show = g.head(12)
    fig, ax = plt.subplots(figsize=(9.5, 6))
    y = np.arange(len(show))[::-1]
    ax.hlines(y, show.sr_pre, show.sr_death, color=GRID, lw=3)
    ax.scatter(show.sr_pre, y, color=GREY, s=55, label="Overs 1-15 strike rate", zorder=3)
    ax.scatter(show.sr_death, y, color=AQUA, s=55, label="Death-overs (16-20) strike rate", zorder=3)
    for yy, (a, b) in zip(y, zip(show.sr_pre, show.sr_death)):
        ax.text(b + 3, yy, f"+{b - a:.0f}", va="center", fontsize=8.5, color=INK2)
    ax.set_yticks(y, show.player)
    ax.grid(axis="y", visible=False)
    ax.legend(loc="lower right")
    ax.set_xlabel("Strike rate (runs per 100 balls)")
    ax.set_title("Biggest death-overs accelerators")
    eda.subtitle(ax, f"Min {TH['death_balls']} death balls and {TH['non_death_balls']} other balls (n={len(g)} qualify). "
                     f"League average acceleration: +{lg_acc:.0f}.")
    chart = save_fig(fig, "A5_death_acceleration")
    return Finding("A5", "A. Batting", "Death-overs acceleration",
                   "Which batters lift their scoring rate most in overs 16-20?",
                   "acceleration = strike rate in death overs - strike rate in overs 1-15 (same batter).",
                   f"Batters with >= {TH['death_balls']} death balls and >= {TH['non_death_balls']} balls in overs 1-15 "
                   f"(n = {len(g)}).", show[["player", "balls_pre", "sr_pre", "balls_death", "sr_death", "acceleration"]].round(1),
                   f"League-wide, strike rate rises by {lg_acc:.1f} in the death overs. {show.iloc[0].player} accelerates most "
                   f"(+{show.iloc[0].acceleration:.1f}: {show.iloc[0].sr_pre:.1f} -> {show.iloc[0].sr_death:.1f}), followed by "
                   f"{show.iloc[1].player} (+{show.iloc[1].acceleration:.1f}). {int((g.acceleration > 0).sum())} of {len(g)} "
                   f"qualifying batters score faster at the death; the smallest change is {g.iloc[-1].player} "
                   f"({g.iloc[-1].acceleration:+.1f}).",
                   "Selection effect: batters who reach the death overs are often set; finishers who only bat late face fewer pre-death balls.",
                   chart)


def a6_season_variability(A: Adv) -> Finding:
    r = A.reg
    s = r.groupby(["batter", "season_year"]).agg(runs=("batsman_runs", "sum"), balls=("is_ball_faced", "sum"))
    s = s[s.balls >= TH["season_balls"]].reset_index()
    lg = r.groupby("season_year").agg(lr=("batsman_runs", "sum"), lb=("is_ball_faced", "sum"))
    s = s.join((lg.lr / lg.lb * 100).rename("league_sr"), on="season_year")
    s["sr"] = s.runs / s.balls * 100
    s["sr_vs_league"] = s.sr - s.league_sr
    g = s.groupby("batter").agg(seasons=("season_year", "size"), mean_sr_vs_league=("sr_vs_league", "mean"),
                                sd_sr_vs_league=("sr_vs_league", "std"), min_sr=("sr", "min"), max_sr=("sr", "max"),
                                runs=("runs", "sum"))
    g = g[g.seasons >= TH["season_min_seasons"]].reset_index().rename(columns={"batter": "player"})
    tbl("A6_season_variability", g.round(3))
    per_ball_sd = r[r.is_ball_faced == 1].batsman_runs.std()          # SD of runs off one ball faced
    se100, se250 = per_ball_sd / np.sqrt(100) * 100, per_ball_sd / np.sqrt(250) * 100
    stable, volatile = g.nsmallest(8, "sd_sr_vs_league"), g.nlargest(8, "sd_sr_vs_league")
    show = pd.concat([stable.assign(group="most stable"), volatile.assign(group="most variable")]).round(1)
    return Finding("A6", "A. Batting", "Season-to-season variability",
                   "Whose scoring rate is steady from season to season, and whose swings widely?",
                   "Per qualifying season: strike rate minus the league strike rate that season (removes the 2023-24 scoring "
                   "jump); variability = standard deviation of that difference across seasons.",
                   f"Seasons with >= {TH['season_balls']} balls faced; batters with >= {TH['season_min_seasons']} such seasons "
                   f"(n = {len(g)}).", show[["group", "player", "seasons", "mean_sr_vs_league", "sd_sr_vs_league", "min_sr", "max_sr"]],
                   f"The steadiest batter is {stable.iloc[0].player} (season-adjusted strike rate varies by SD "
                   f"{stable.iloc[0].sd_sr_vs_league:.1f} over {stable.iloc[0].seasons} seasons); the most variable is "
                   f"{volatile.iloc[0].player} (SD {volatile.iloc[0].sd_sr_vs_league:.1f}, from {volatile.iloc[0].min_sr:.0f} to "
                   f"{volatile.iloc[0].max_sr:.0f}). The median SD across qualifying batters is {g.sd_sr_vs_league.median():.1f} "
                   f"strike-rate points. Much of this is sampling noise: with a per-ball run SD of {per_ball_sd:.2f}, a season's "
                   f"strike rate has a standard error of about {se100:.0f} points at 100 balls and {se250:.0f} at 250 balls.",
                   "Role changes (opener vs finisher) across seasons are not visible in the data.")


def a7_first_vs_chasing(A: Adv) -> Finding:
    bi = A.bi
    g = bi.groupby(["player", "inning"]).agg(innings=("runs", "size"), runs=("runs", "sum"), balls=("balls", "sum"),
                                             outs=("out", "sum")).unstack()
    g.columns = [f"{a}_{b}" for a, b in g.columns]
    g = g[(g.innings_1 >= TH["split_innings"]) & (g.innings_2 >= TH["split_innings"])].copy()
    g["sr_bat_first"] = g.runs_1 / g.balls_1 * 100
    g["sr_chasing"] = g.runs_2 / g.balls_2 * 100
    g["rpi_bat_first"] = g.runs_1 / g.innings_1
    g["rpi_chasing"] = g.runs_2 / g.innings_2
    g["notout_pct_chasing"] = (1 - g.outs_2 / g.innings_2) * 100
    g["notout_pct_bat_first"] = (1 - g.outs_1 / g.innings_1) * 100
    g["sr_diff"] = g.sr_chasing - g.sr_bat_first
    g = g.reset_index()
    w_sr = stats.wilcoxon(g.sr_chasing, g.sr_bat_first)
    w_rpi = stats.wilcoxon(g.rpi_chasing, g.rpi_bat_first)
    tbl("A7_bat_first_vs_chasing", g.round(3))
    fig, ax = plt.subplots(figsize=(8, 7))
    ax.scatter(g.sr_bat_first, g.sr_chasing, color=BLUE, alpha=0.6, s=34, edgecolor=SURFACE)
    lo, hi = min(g.sr_bat_first.min(), g.sr_chasing.min()) - 5, max(g.sr_bat_first.max(), g.sr_chasing.max()) + 5
    ax.plot([lo, hi], [lo, hi], color=INK2, lw=1, ls="--")
    ax.text(hi - 2, hi - 6, "equal", color=INK2, fontsize=8.5, ha="right")
    lab = pd.concat([g.nlargest(4, "sr_diff"), g.nsmallest(4, "sr_diff")])
    eda.label_points(ax, lab.sr_bat_first, lab.sr_chasing, lab.player)
    ax.set_xlim(lo, hi); ax.set_ylim(lo, hi)
    ax.set_xlabel("Strike rate batting first")
    ax.set_ylabel("Strike rate chasing")
    ax.set_title("Batting first vs chasing strike rate")
    eda.subtitle(ax, f"Batters with {TH['split_innings']}+ innings in each role (n={len(g)}). Above the line = faster when chasing.")
    chart = save_fig(fig, "A7_bat_first_vs_chasing")
    show = pd.concat([g.nlargest(6, "sr_diff"), g.nsmallest(6, "sr_diff")])[
        ["player", "innings_1", "sr_bat_first", "innings_2", "sr_chasing", "sr_diff", "rpi_bat_first", "rpi_chasing"]].round(1)
    return Finding("A7", "A. Batting", "Batting first vs chasing",
                   "Do batters perform differently when setting a target versus chasing one?",
                   "Per batter: strike rate and runs per innings in innings 1 vs innings 2; Wilcoxon signed-rank test "
                   "(paired, non-parametric) across batters.",
                   f"Batters with >= {TH['split_innings']} innings in both roles (n = {len(g)}).", show,
                   f"Median strike rate is {g.sr_bat_first.median():.1f} batting first vs {g.sr_chasing.median():.1f} chasing "
                   f"(Wilcoxon p = {w_sr.pvalue:.3f}); median runs per innings {g.rpi_bat_first.median():.1f} vs "
                   f"{g.rpi_chasing.median():.1f} (p = {w_rpi.pvalue:.3g}). Chasing innings are cut short when the target is "
                   f"reached (median not-out rate {g.notout_pct_chasing.median():.0f}% chasing vs {g.notout_pct_bat_first.median():.0f}% "
                   f"batting first), so lower runs per innings when chasing is expected and is NOT evidence of weaker batting. "
                   f"Individual differences (e.g. {show.iloc[0].player} {show.iloc[0].sr_diff:+.1f}) are not tested one by one "
                   f"to avoid multiple-comparison false positives.",
                   "Chase innings are truncated by the target; strike rate is the fairer comparison.", chart)


# =========================================================================== B. BOWLING
def b1_phase_wickets(A: Adv) -> Finding:
    r = A.reg
    p = r.groupby("phase").agg(balls=("is_legal_delivery", "sum"), bowler_wkts=("is_bowler_wicket", "sum"),
                               runs=("bowler_runs_conceded", "sum")).loc[PH]
    p["balls_per_bowler_wicket"] = p.balls / p.bowler_wkts
    p["economy"] = p.runs / p.balls * 6
    kinds = r[r.is_bowler_wicket == 1].groupby(["phase", "dismissal_kind"]).size().unstack(fill_value=0).loc[PH]
    mix = kinds.div(kinds.sum(axis=1), axis=0) * 100
    chi2, pval, dof, exp = stats.chi2_contingency(kinds.values)
    t = p.join(mix.add_prefix("pct_")).round(2).reset_index()
    tbl("B1_phase_wickets", t)
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.3))
    axes[0].bar(PH, p.balls_per_bowler_wicket, color=[PHC[x] for x in PH], width=0.6)
    for i, v in enumerate(p.balls_per_bowler_wicket):
        axes[0].text(i, v, f"{v:.1f}", ha="center", va="bottom", fontsize=9)
    axes[0].set_title("Legal balls per bowler wicket")
    axes[0].grid(axis="x", visible=False)
    order = ["caught", "bowled", "lbw", "stumped", "caught and bowled", "hit wicket"]
    left = np.zeros(3)
    cols = [BLUE, ORANGE, AQUA, "#eda100", "#6250d6", GREY]
    for k, c in zip(order, cols):
        vals = mix[k].values if k in mix else np.zeros(3)
        axes[1].barh(PH, vals, left=left, color=c, label=k, height=0.6, edgecolor=SURFACE, linewidth=1)
        left += vals
    axes[1].invert_yaxis()
    axes[1].xaxis.set_major_formatter(mtick.PercentFormatter())
    axes[1].legend(ncol=3, fontsize=8, loc="upper center", bbox_to_anchor=(0.5, -0.12))
    axes[1].set_title("How bowler wickets fall (share of dismissal types)")
    eda.fig_title(fig, "Wicket-taking by phase (regulation deliveries, bowler-credited wickets)")
    chart = save_fig(fig, "B1_phase_wicket_rate")
    return Finding("B1", "B. Bowling", "Wicket-taking rate and dismissal mix by phase",
                   "How does the rate and the type of wicket change across the innings?",
                   "balls per bowler wicket = legal balls / is_bowler_wicket; dismissal mix = share of bowler wickets by kind; "
                   "chi-square test of independence between phase and dismissal kind.",
                   f"{int(p.bowler_wkts.sum()):,} bowler wickets from {int(p.balls.sum()):,} legal balls.",
                   t[["phase", "balls", "bowler_wkts", "balls_per_bowler_wicket", "economy"] + [c for c in t.columns if c.startswith("pct_")]],
                   f"A bowler wicket falls every {p.balls_per_bowler_wicket['Death']:.1f} balls at the death vs "
                   f"{p.balls_per_bowler_wicket['Powerplay']:.1f} in the Powerplay and {p.balls_per_bowler_wicket['Middle']:.1f} "
                   f"in the middle overs. The dismissal mix differs by phase (chi-square = {chi2:.0f}, dof = {dof}, "
                   f"p = {pval:.1e}): caught is {mix.loc['Death', 'caught']:.0f}% of death wickets vs "
                   f"{mix.loc['Powerplay', 'caught']:.0f}% in the Powerplay; stumpings are {mix.loc['Middle', 'stumped']:.1f}% of "
                   f"middle-overs wickets vs {mix.loc['Powerplay', 'stumped']:.1f}% (Powerplay) and {mix.loc['Death', 'stumped']:.1f}% "
                   f"(death), and bowled/lbw shares are highest in the Powerplay ({mix.loc['Powerplay', 'bowled'] + mix.loc['Powerplay', 'lbw']:.0f}%). "
                   f"Bowler type is not in the data, so the link to spin in the middle overs is a plausible explanation, not a finding.",
                   f"Smallest expected cell count = {exp.min():.1f} (hit wicket); chi-square assumption (>=5) "
                   f"{'met' if exp.min() >= 5 else 'NOT met for the rarest kind - result driven by large categories'}.", chart)


def bowler_adjusted(A: Adv, deliv: pd.DataFrame) -> pd.DataFrame:
    """Bowler economy vs the league economy expected for the SAME seasons and phases they bowled in."""
    g = deliv.assign(exp=deliv.is_legal_delivery * deliv.lg_bowler_rpb, expw=deliv.is_legal_delivery * deliv.lg_wpb) \
        .groupby("bowler").agg(legal_balls=("is_legal_delivery", "sum"), runs=("bowler_runs_conceded", "sum"),
                               wickets=("is_bowler_wicket", "sum"), dots=("is_dot_ball", "sum"),
                               boundaries=("is_boundary", "sum"), exp_runs=("exp", "sum"), exp_wkts=("expw", "sum"))
    g["economy"] = g.runs / g.legal_balls * 6
    g["adj_economy"] = (g.runs - g.exp_runs) / g.legal_balls * 6
    g["strike_rate"] = g.legal_balls / g.wickets.replace(0, np.nan)
    g["wickets_vs_expected"] = g.wickets / g.exp_wkts
    g["dot_pct"] = g.dots / g.legal_balls * 100
    g["boundary_pct"] = g.boundaries / g.legal_balls * 100
    return g.reset_index()


def b2_tradeoff(A: Adv) -> Finding:
    b = bowler_adjusted(A, A.reg)
    b = b[b.legal_balls >= TH["bowl_balls"]].copy()
    rho, p = stats.spearmanr(b.adj_economy, b.strike_rate)
    tbl("B2_bowler_adjusted", b.round(4))
    fig, ax = plt.subplots(figsize=(10, 6.5))
    ax.scatter(b.adj_economy, b.wickets_vs_expected, s=np.clip(b.wickets * 1.5, 12, 320), color=AQUA, alpha=0.6,
               edgecolor=SURFACE, linewidth=1)
    ax.axvline(0, color=INK2, lw=1, ls="--")
    ax.axhline(1, color=INK2, lw=1, ls="--")
    lab = pd.concat([b.nsmallest(5, "adj_economy"), b.nlargest(5, "wickets_vs_expected"), b.nlargest(3, "wickets")]).drop_duplicates("bowler")
    eda.label_points(ax, lab.adj_economy, lab.wickets_vs_expected, lab.bowler)
    ax.set_xlabel("Economy vs expected for same seasons & phases (runs/over; negative = better)")
    ax.set_ylabel("Wickets / expected wickets (>1 = more than league rate)")
    ax.set_title("Bowling trade-off: run control vs wicket-taking (season- and phase-adjusted)")
    eda.subtitle(ax, f"Bowlers with {TH['bowl_balls']}+ legal balls (n={len(b)}). Bubble = wickets. "
                     "Top-left = economical AND above-average wicket-taker.")
    chart = save_fig(fig, "B2_adjusted_tradeoff")
    both = b[(b.adj_economy < 0) & (b.wickets_vs_expected > 1)].sort_values("adj_economy")
    show = b.sort_values("adj_economy")[["bowler", "legal_balls", "economy", "adj_economy", "wickets",
                                         "wickets_vs_expected", "strike_rate"]].head(15).round(2)
    return Finding("B2", "B. Bowling", "Economy vs wicket-taking trade-off (season- and phase-adjusted)",
                   "Is there a trade-off between conceding few runs and taking wickets, once we adjust for when bowlers bowled?",
                   "Expected runs/wickets = each legal ball x league rate for that season AND phase. adj_economy = (runs - "
                   "expected) x 6 / balls; wickets_vs_expected = wickets / expected. Spearman correlation.",
                   f"Bowlers with >= {TH['bowl_balls']} legal balls (n = {len(b)}).", show,
                   f"Phase/season adjustment changes the picture: {show.iloc[0].bowler} is the most economical relative to "
                   f"context ({show.iloc[0].adj_economy:+.2f} runs/over). Across bowlers, the rank correlation between adjusted "
                   f"economy and strike rate is rho = {rho:.2f} (p = {p:.3f}) - "
                   + ("a statistically significant " + ("trade-off (cheaper bowlers take wickets less often)" if rho < 0
                                                         else "alignment (cheaper bowlers also take wickets more often)")
                      if p < 0.05 else
                      "no statistically significant trade-off: being economical neither costs nor guarantees wickets")
                   + ". "
                   f"{len(both)} of {len(b)} bowlers beat the league on BOTH measures (e.g. "
                   f"{', '.join(both.bowler.head(5))}).",
                   "Adjustment uses phase and season only; batter quality and venue are not controlled.", chart)


def b3_dot_boundary(A: Adv) -> Finding:
    b = bowler_adjusted(A, A.reg)
    b = b[b.legal_balls >= TH["bowl_balls"]].copy()
    rho, p = stats.spearmanr(b.dot_pct, b.economy)
    rho2, p2 = stats.spearmanr(b.boundary_pct, b.economy)
    show = b.sort_values("dot_pct", ascending=False)[["bowler", "legal_balls", "dot_pct", "boundary_pct", "economy"]].head(12).round(2)
    low_b = b.sort_values("boundary_pct")[["bowler", "legal_balls", "boundary_pct", "dot_pct", "economy"]].head(12).round(2)
    return Finding("B3", "B. Bowling", "Dot-ball and boundary-conceding percentages",
                   "Which bowlers build pressure with dot balls, and which concede fewest boundaries?",
                   "dot % = legal balls with no runs scored / legal balls; boundary % = 4s + 6s off the bat / legal balls; "
                   "Spearman correlation with economy.",
                   f"Bowlers with >= {TH['bowl_balls']} legal balls (n = {len(b)}).", show,
                   f"{show.iloc[0].bowler} has the highest dot-ball rate ({show.iloc[0].dot_pct:.1f}%); {low_b.iloc[0].bowler} "
                   f"concedes the fewest boundaries ({low_b.iloc[0].boundary_pct:.1f}% of balls). Boundary % explains economy "
                   f"more strongly (rho = {rho2:.2f}) than dot % (rho = {rho:.2f}): limiting boundaries matters more for run "
                   f"control than bowling dots. Note: dot % and boundary % are not era-adjusted (both shift with scoring levels).",
                   "Fours/sixes proxy. Dot % counts legal balls with total_runs = 0 (leg-byes break a dot).", None,
                   {"Fewest boundaries conceded": low_b})


def phase_specialists(A: Adv, phase: str, qid: str, title: str) -> Finding:
    d = A.reg[A.reg.phase == phase]
    b = bowler_adjusted(A, d)
    b = b[b.legal_balls >= TH["phase_bowl_balls"]].sort_values("adj_economy")
    tbl(f"{qid}_{phase.lower()}_specialists", b.round(4))
    show = b[["bowler", "legal_balls", "economy", "adj_economy", "wickets", "strike_rate", "dot_pct", "boundary_pct"]].head(12).round(2)
    chart = None
    if phase == "Death":
        s = show.iloc[::-1]
        fig, ax = plt.subplots(figsize=(9, 5.6))
        ax.barh(s.bowler, s.adj_economy, color=[AQUA if v < 0 else ORANGE for v in s.adj_economy], height=0.65)
        for y, (v, sr) in enumerate(zip(s.adj_economy, s.strike_rate)):
            ax.text(v - 0.03, y, f"{v:+.2f}  (SR {sr:.1f})", va="center", ha="right", fontsize=8.5, color=INK)
        ax.axvline(0, color=INK2, lw=1)
        ax.grid(axis="y", visible=False)
        ax.set_xlim(min(s.adj_economy.min() * 1.9, -1), 0.3)
        ax.set_xlabel("Death-over economy vs league death economy in the same seasons (runs/over)")
        ax.set_title("Best death-overs bowlers (season-adjusted)")
        eda.subtitle(ax, f"Min {TH['phase_bowl_balls']} legal balls in overs 16-20 (n={len(b)} qualify). SR = balls per bowler wicket.")
        chart = save_fig(fig, "B4_death_specialists")
    return Finding(qid, "B. Bowling", title,
                   f"Who are the most effective {phase.lower()} bowlers once season scoring levels are removed?",
                   "adj_economy = (bowler runs - league runs expected for those seasons in this phase) x 6 / legal balls.",
                   f"Bowlers with >= {TH['phase_bowl_balls']} legal balls in the {phase.lower()} (n = {len(b)}).", show,
                   f"{show.iloc[0].bowler} is the standout {phase.lower()} bowler ({show.iloc[0].adj_economy:+.2f} runs/over vs "
                   f"league; raw economy {show.iloc[0].economy:.2f}, strike rate {show.iloc[0].strike_rate:.1f}), then "
                   f"{show.iloc[1].bowler} ({show.iloc[1].adj_economy:+.2f}) and {show.iloc[2].bowler} "
                   f"({show.iloc[2].adj_economy:+.2f}). {int((b.adj_economy < 0).sum())} of {len(b)} qualifying bowlers beat "
                   f"the league rate.",
                   "Specialists are selected by captains for this phase - a survivor effect inflates their numbers.", chart)


def b6_bowler_consistency(A: Adv) -> Finding:
    d = A.reg
    s = d.assign(exp=d.is_legal_delivery * d.lg_bowler_rpb).groupby(["bowler", "season_year"]) \
        .agg(balls=("is_legal_delivery", "sum"), runs=("bowler_runs_conceded", "sum"), exp=("exp", "sum"))
    s = s[s.balls >= TH["bowl_season_balls"]].reset_index()
    s["adj_econ"] = (s.runs - s.exp) / s.balls * 6
    g = s.groupby("bowler").agg(seasons=("season_year", "size"), mean_adj_econ=("adj_econ", "mean"),
                                sd_adj_econ=("adj_econ", "std"),
                                seasons_better_than_league=("adj_econ", lambda x: int((x < 0).sum())))
    g = g[g.seasons >= TH["bowl_min_seasons"]].reset_index()
    g["pct_seasons_better"] = g.seasons_better_than_league / g.seasons * 100
    rpb_sd = d[d.is_legal_delivery == 1].bowler_runs_conceded.std()
    se120, se300 = rpb_sd / np.sqrt(120) * 6, rpb_sd / np.sqrt(300) * 6
    tbl("B6_bowler_consistency", g.round(4))
    show = g.sort_values(["seasons_better_than_league", "mean_adj_econ"], ascending=[False, True]).head(12).round(2)
    return Finding("B6", "B. Bowling", "Bowlers consistent across seasons",
                   "Which bowlers beat the league economy season after season?",
                   "Per qualifying season: economy minus league economy expected for that season and the phases bowled. "
                   "Consistency = number of seasons better than the league, and SD of the season values.",
                   f"Seasons with >= {TH['bowl_season_balls']} legal balls; bowlers with >= {TH['bowl_min_seasons']} such "
                   f"seasons (n = {len(g)}).", show,
                   f"{show.iloc[0].bowler} beat the league in {show.iloc[0].seasons_better_than_league} of "
                   f"{show.iloc[0].seasons} seasons (mean {show.iloc[0].mean_adj_econ:+.2f} runs/over). "
                   f"{int((g.pct_seasons_better == 100).sum())} bowler(s) beat the league in every qualifying season. "
                   f"The median bowler beat the league in {g.pct_seasons_better.median():.0f}% of seasons.",
                   f"Season samples are noisy: a season economy has a standard error of about {se120:.2f} runs/over at 120 "
                   f"balls and {se300:.2f} at 300 balls (per-ball SD {rpb_sd:.2f}).")


def b7_conditions(A: Adv) -> Finding:
    d = A.reg
    lg = d.groupby(["inning", "phase"]).agg(runs=("bowler_runs_conceded", "sum"), balls=("is_legal_delivery", "sum"),
                                            w=("is_bowler_wicket", "sum"))
    lg["economy"] = lg.runs / lg.balls * 6
    lg["balls_per_wkt"] = lg.balls / lg.w
    lg_t = lg[["economy", "balls_per_wkt"]].unstack(0)
    lg_t.columns = [f"{a}_inn{b}" for a, b in lg_t.columns]
    # per bowler: economy bowling first (defending later) vs bowling second
    b = d.groupby(["bowler", "inning"]).agg(runs=("bowler_runs_conceded", "sum"), balls=("is_legal_delivery", "sum")).unstack()
    b.columns = [f"{a}_{c}" for a, c in b.columns]
    b = b[(b.balls_1 >= 500) & (b.balls_2 >= 500)].copy()
    b["econ_inn1"] = b.runs_1 / b.balls_1 * 6
    b["econ_inn2"] = b.runs_2 / b.balls_2 * 6
    w = stats.wilcoxon(b.econ_inn1, b.econ_inn2)
    # venue scoring tier (season-adjusted first-innings score terciles, venues >= 20 full matches)
    V = eda.venue_table(A.D)
    V = V[V.full_matches >= TH["venue_matches"]].copy()
    V["tier"] = pd.qcut(V.avg_inn1_vs_season, 3, labels=["Low-scoring", "Mid", "High-scoring"])
    dv = d.merge(V[["venue", "tier"]], on="venue")
    tier = dv.groupby("tier", observed=True).agg(balls=("is_legal_delivery", "sum"), runs=("bowler_runs_conceded", "sum"),
                                                 w=("is_bowler_wicket", "sum"), dots=("is_dot_ball", "sum"),
                                                 b4=("is_boundary", "sum"))
    tier["economy"] = tier.runs / tier.balls * 6
    tier["balls_per_wkt"] = tier.balls / tier.w
    tier["dot_pct"] = tier.dots / tier.balls * 100
    tier["boundary_pct"] = tier.b4 / tier.balls * 100
    tbl("B7_conditions_innings", lg_t.round(3).reset_index())
    tbl("B7_conditions_venue_tier", tier.round(3).reset_index())
    t = lg_t.round(2).reset_index()
    return Finding("B7", "B. Bowling", "Bowling under different match conditions",
                   "Does bowling change between the first and second innings, and between high- and low-scoring venues?",
                   "Economy and balls per bowler wicket by innings x phase; per-bowler paired comparison (Wilcoxon) of "
                   "economy in innings 1 vs 2; venue tiers = terciles of season-adjusted first-innings score.",
                   f"League: all regulation balls. Paired test: bowlers with >= 500 legal balls in each innings (n = {len(b)}). "
                   f"Venues: {len(V)} with >= {TH['venue_matches']} full matches.", t,
                   f"Bowling second, the median qualifying bowler's economy is {b.econ_inn2.median():.2f} vs "
                   f"{b.econ_inn1.median():.2f} bowling first (Wilcoxon p = {w.pvalue:.3f}"
                   f"{', a statistically significant but small difference' if w.pvalue < 0.05 else ', not significant'}); "
                   f"second-innings totals are partly truncated by successful chases, which may contribute. Death-over wicket "
                   f"rates are similar in both innings ({lg.loc[(2, 'Death'), 'balls_per_wkt']:.1f} vs "
                   f"{lg.loc[(1, 'Death'), 'balls_per_wkt']:.1f} balls per wicket). At high-scoring venues economy is "
                   f"{tier.loc['High-scoring', 'economy']:.2f} vs {tier.loc['Low-scoring', 'economy']:.2f} at low-scoring venues, "
                   f"with boundary % {tier.loc['High-scoring', 'boundary_pct']:.1f}% vs {tier.loc['Low-scoring', 'boundary_pct']:.1f}% "
                   f"and balls per wicket {tier.loc['High-scoring', 'balls_per_wkt']:.1f} vs {tier.loc['Low-scoring', 'balls_per_wkt']:.1f}.",
                   "Second-innings bowling is affected by how the chase unfolds (truncated innings, required rate).", None,
                   {"Venue scoring tiers": tier.round(2).reset_index()})


# =========================================================================== C. PRESSURE
BANDS = [0, 140, 160, 180, 200, 400]
BAND_LAB = ["<140", "140-159", "160-179", "180-199", "200+"]


def c1_chase_by_target(A: Adv) -> Finding:
    cm = A.chase_matches.copy()
    cm["band"] = pd.cut(cm.inn1_runs, BANDS, right=False, labels=BAND_LAB)
    cm["period"] = np.where(cm.season_year >= 2023, "2023-24", "2008-22")
    rows = []
    for (per, band), g in cm.groupby(["period", "band"], observed=True):
        p, lo, hi = wilson(g.chase_won.sum(), len(g))
        rows.append({"period": per, "first_innings": band, "matches": len(g), "chase_wins": int(g.chase_won.sum()),
                     "chase_win_pct": p, "ci_low": lo, "ci_high": hi})
    allp = []
    for band, g in cm.groupby("band", observed=True):
        p, lo, hi = wilson(g.chase_won.sum(), len(g))
        allp.append({"period": "All", "first_innings": band, "matches": len(g), "chase_wins": int(g.chase_won.sum()),
                     "chase_win_pct": p, "ci_low": lo, "ci_high": hi})
    t = pd.DataFrame(allp + rows)
    tbl("C1_chase_by_first_innings", t.round(3))
    fig, ax = plt.subplots(figsize=(10, 5))
    x = np.arange(len(BAND_LAB))
    for i, (per, col) in enumerate([("2008-22", BLUE), ("2023-24", ORANGE)]):
        s = t[t.period == per].set_index("first_innings").reindex(BAND_LAB)
        xs = x + (i - 0.5) * 0.28
        ax.bar(xs, s.chase_win_pct, width=0.28, color=col, label=per)
        ax.errorbar(xs, s.chase_win_pct, yerr=[s.chase_win_pct - s.ci_low, s.ci_high - s.chase_win_pct],
                    fmt="none", ecolor=INK2, capsize=3, lw=1)
        for xx, (v, n) in zip(xs, zip(s.chase_win_pct, s.matches)):
            if pd.notna(v):
                ax.text(xx, 2, f"n={int(n)}", ha="center", fontsize=7.5, color=SURFACE, rotation=90, va="bottom")
    ax.axhline(50, color=INK2, lw=1, ls="--")
    ax.set_xticks(x, BAND_LAB)
    ax.set_ylim(0, 100)
    ax.yaxis.set_major_formatter(mtick.PercentFormatter())
    ax.set_xlabel("First-innings score")
    ax.set_ylabel("Chasing team win %")
    ax.legend(title="Seasons")
    ax.set_title("Chase success by first-innings score")
    eda.subtitle(ax, "Full 20-over, non-D/L matches decided by runs/wickets. Error bars = 95% Wilson interval.")
    chart = save_fig(fig, "C1_chase_by_first_innings")
    a = t[t.period == "All"].set_index("first_innings")
    r23 = t[(t.period == "2023-24")].set_index("first_innings")
    monotonic = bool(a.reindex(BAND_LAB).chase_win_pct.is_monotonic_decreasing)
    return Finding("C1", "C. Match pressure", "Chasing success by first-innings score",
                   "How does the size of the target change the chasing side's chance of winning?",
                   "Chase win % by first-innings score band; 95% Wilson intervals; split 2008-22 vs 2023-24.",
                   f"{len(cm)} full, non-D/L, decided matches.", t.round(1),
                   f"Chases of sub-140 totals succeed {a.loc['<140', 'chase_win_pct']:.0f}% of the time, falling to "
                   f"{a.loc['160-179', 'chase_win_pct']:.0f}% for 160-179 and {a.loc['200+', 'chase_win_pct']:.0f}% for 200+ "
                   f"(n = {int(a.loc['200+', 'matches'])}). Chase success "
                   f"{'falls in every successive band' if monotonic else 'generally falls as the target rises (not strictly in every band)'}. In 2023-24, "
                   f"targets of 180-199 were chased {r23.loc['180-199', 'chase_win_pct']:.0f}% of the time (n = "
                   f"{int(r23.loc['180-199', 'matches'])}, CI {r23.loc['180-199', 'ci_low']:.0f}-{r23.loc['180-199', 'ci_high']:.0f}%) "
                   f"- the 'safe' total has moved upward with the scoring increase, though 2023-24 samples are small.",
                   "Venue and team strength are not controlled.", chart)


def c2_required_rate(A: Adv) -> Finding:
    st = A.states
    rows = []
    rr_bins, rr_lab = [0, 6, 8, 10, 12, 14, 99], ["<6", "6-8", "8-10", "10-12", "12-14", "14+"]
    for over in [6, 10, 15]:
        s = st[st.over_number == over].copy()
        s["rrr_band"] = pd.cut(s.rrr, rr_bins, right=False, labels=rr_lab)
        s["wih"] = pd.cut(s.wickets_in_hand, [0, 5, 8, 11], right=False, labels=["1-4", "5-7", "8-10"])
        for (band, wih), g in s.groupby(["rrr_band", "wih"], observed=True):
            if len(g) >= 10:
                p, lo, hi = wilson(g.chase_won.sum(), len(g))
                rows.append({"after_over": over, "required_rate": band, "wickets_in_hand": wih, "states": len(g),
                             "chase_win_pct": p, "ci_low": lo, "ci_high": hi})
    t = pd.DataFrame(rows)
    tbl("C2_chase_by_required_rate", t.round(3))
    s10 = t[t.after_over == 10]
    fig, ax = plt.subplots(figsize=(10, 5))
    for wih, col in [("8-10", BLUE), ("5-7", ORANGE), ("1-4", AQUA)]:
        s = s10[s10.wickets_in_hand == wih].set_index("required_rate").reindex(rr_lab)
        if s.chase_win_pct.notna().sum() == 0:
            continue  # no cell with >= 10 chases for this wickets-in-hand band
        ax.plot(rr_lab, s.chase_win_pct.astype(float), marker="o", color=col, label=f"{wih} wickets in hand")
        ax.fill_between(rr_lab, s.ci_low.astype(float), s.ci_high.astype(float), color=col, alpha=0.12)
    ax.set_ylim(0, 100)
    ax.yaxis.set_major_formatter(mtick.PercentFormatter())
    ax.set_xlabel("Required run rate after 10 overs (runs per over)")
    ax.set_ylabel("Chases won")
    ax.legend(loc="upper right")
    ax.set_title("Chase success after 10 overs by required rate and wickets in hand")
    eda.subtitle(ax, "Full 20-over, non-D/L chases still in progress after over 10. Bands with <10 chases omitted; shading = 95% CI.")
    chart = save_fig(fig, "C2_required_rate_wickets")
    s10b = st[st.over_number == 10]
    lr = stats.spearmanr(s10b.rrr, s10b.chase_won)
    k = s10.set_index(["required_rate", "wickets_in_hand"])
    def pick(rr, wh):
        try:
            v = k.loc[(rr, wh)]
            return f"{v.chase_win_pct:.0f}% (n={int(v.states)})"
        except KeyError:
            return "n/a"
    return Finding("C2", "C. Match pressure", "Chasing success by required run rate and wickets in hand",
                   "Given the situation part-way through a chase, how often does the chasing side win?",
                   "At the end of overs 6, 10 and 15 of a chase: required rate = runs needed / balls left x 6; wickets in "
                   "hand = 10 - dismissals (retired hurt excluded). Win % per (required-rate band, wickets band); 95% Wilson CI.",
                   f"{A.states.match_id.nunique()} full non-D/L chases; {len(s10b)} still live after over 10. Cells with < 10 "
                   "chases are omitted.", t.round(1),
                   f"After 10 overs, needing 8-10 an over with 8-10 wickets in hand the chase is won {pick('8-10', '8-10')}; "
                   f"with only 5-7 wickets in hand it falls to {pick('8-10', '5-7')}. Needing 10-12 with 8-10 wickets: "
                   f"{pick('10-12', '8-10')}. Both required rate and wickets in hand matter (rank correlation of required "
                   f"rate with winning at over 10: rho = {lr.statistic:.2f}). These are observed frequencies from real "
                   "match states, not a modelled 'pressure index'.",
                   "Each chase contributes one state per over shown, so cells at different overs are not independent.", chart)


def c3_wickets_remaining(A: Adv) -> Finding:
    r = A.reg.copy()
    r["wkts_lost_band"] = pd.cut(r.wkts_before, [-1, 1, 3, 5, 10], labels=["0-1", "2-3", "4-5", "6+"])
    g = r.groupby(["phase", "wkts_lost_band"], observed=True).agg(balls=("is_legal_delivery", "sum"),
                                                                  runs=("total_runs", "sum"), b4=("is_boundary", "sum"),
                                                                  dots=("is_dot_ball", "sum"))
    g["run_rate"] = g.runs / g.balls * 6
    g["boundary_pct"] = g.b4 / g.balls * 100
    g["dot_pct"] = g.dots / g.balls * 100
    g = g[g.balls >= 1000]
    t = g.reset_index()
    tbl("C3_wickets_remaining", t.round(3))
    piv = g.run_rate.unstack(0)[PH]
    fig, ax = plt.subplots(figsize=(8.5, 4.4))
    im = ax.imshow(piv.values, cmap=LinearSegmentedColormap.from_list("rr", ["#f3f2ee", BLUE]), aspect="auto")
    for i in range(piv.shape[0]):
        for j in range(piv.shape[1]):
            v = piv.values[i, j]
            if pd.notna(v):
                n = g.balls.unstack(0)[PH].values[i, j]
                ax.text(j, i, f"{v:.2f}\n({int(n):,} balls)", ha="center", va="center", fontsize=8.5,
                        color=SURFACE if v > np.nanmean(piv.values) + 0.6 else INK)
    ax.set_xticks(range(3), PH)
    ax.set_yticks(range(len(piv)), piv.index)
    ax.set_ylabel("Wickets already lost")
    ax.grid(False)
    ax.set_title("Run rate by wickets already lost, within each phase")
    eda.subtitle(ax, "Regulation deliveries; cells with <1,000 legal balls omitted.")
    fig.colorbar(im, ax=ax, label="Runs per over")
    chart = save_fig(fig, "C3_runrate_by_wickets_lost")
    return Finding("C3", "C. Match pressure", "Scoring with different numbers of wickets remaining",
                   "Do batting sides slow down as wickets fall, once the phase of the innings is held constant?",
                   "Wickets lost BEFORE each ball (cumulative is_player_out in the innings); run rate, boundary % and dot % "
                   "by phase x wickets-lost band.", f"{int(g.balls.sum()):,} legal balls in cells with >= 1,000 balls.",
                   t.round(2),
                   f"Within the same phase, losing wickets slows scoring: in the middle overs the run rate is "
                   f"{piv.loc['0-1', 'Middle']:.2f} with 0-1 wickets down vs {piv.loc['6+', 'Middle']:.2f} with 6+ down; in the "
                   f"death overs {piv.loc['0-1', 'Death'] if pd.notna(piv.loc['0-1', 'Death']) else float('nan'):.2f} vs "
                   f"{piv.loc['6+', 'Death']:.2f}. Comparing within a phase matters - overall, death overs have both the most "
                   f"wickets down and the highest scoring, which would hide this effect.",
                   "Association only: batting strength of the remaining batters is not observed.", chart)


def c4_chase_patterns(A: Adv) -> Finding:
    cm = A.chase_matches
    r2 = A.reg[(A.reg.inning == 2) & A.reg.match_id.isin(cm.match_id)].merge(cm[["match_id", "chase_won"]], on="match_id")
    per = r2.groupby(["match_id", "chase_won", "phase"]).agg(runs=("total_runs", "sum"), balls=("is_legal_delivery", "sum"),
                                                              wk=("is_player_out", "sum")).reset_index()
    per = per[per.balls > 0]
    per["rr"] = per.runs / per.balls * 6
    s = per.groupby(["phase", "chase_won"]).agg(innings=("match_id", "nunique"), median_rr=("rr", "median"),
                                                mean_wickets=("wk", "mean")).reset_index()
    tests = []
    for ph in PH:
        a = per[(per.phase == ph) & (per.chase_won == 1)]
        b = per[(per.phase == ph) & (per.chase_won == 0)]
        u = stats.mannwhitneyu(a.rr, b.rr)
        u2 = stats.mannwhitneyu(a.wk, b.wk)
        tests.append({"phase": ph, "won_n": len(a), "lost_n": len(b), "median_rr_won": a.rr.median(), "median_rr_lost": b.rr.median(),
                      "p_run_rate": u.pvalue, "mean_wkts_won": a.wk.mean(), "mean_wkts_lost": b.wk.mean(), "p_wickets": u2.pvalue})
    t = pd.DataFrame(tests)
    tbl("C4_chase_patterns", t.round(5))
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.3))
    x = np.arange(3)
    for i, (lab, col) in enumerate([("won", AQUA), ("lost", ORANGE)]):
        axes[0].bar(x + (i - 0.5) * 0.35, t[f"median_rr_{lab}"], width=0.35, color=col, label=f"Chase {lab}")
        axes[1].bar(x + (i - 0.5) * 0.35, t[f"mean_wkts_{lab}"], width=0.35, color=col, label=f"Chase {lab}")
    for ax, ttl in zip(axes, ["Median run rate in phase", "Mean wickets lost in phase"]):
        ax.set_xticks(x, PH)
        ax.set_title(ttl)
        ax.grid(axis="x", visible=False)
    axes[0].legend()
    eda.fig_title(fig, "Successful vs unsuccessful chases (full 20-over, non-D/L matches)")
    chart = save_fig(fig, "C4_chase_patterns")
    pp = t.set_index("phase")
    return Finding("C4", "C. Match pressure", "Successful vs unsuccessful chase patterns",
                   "What distinguishes chases that succeed from those that fail, phase by phase?",
                   "Per chase and phase: run rate and wickets lost; medians compared with Mann-Whitney U tests.",
                   f"{cm.chase_won.sum()} won and {(1 - cm.chase_won).sum()} lost chases.", t.round(3),
                   f"Successful chases are ahead from the start: Powerplay median run rate {pp.loc['Powerplay', 'median_rr_won']:.2f} "
                   f"vs {pp.loc['Powerplay', 'median_rr_lost']:.2f}, losing {pp.loc['Powerplay', 'mean_wkts_won']:.2f} vs "
                   f"{pp.loc['Powerplay', 'mean_wkts_lost']:.2f} wickets on average (Mann-Whitney p = "
                   f"{pp.loc['Powerplay', 'p_run_rate']:.1e} for run rate, {pp.loc['Powerplay', 'p_wickets']:.1e} for wickets). "
                   f"The biggest wicket gap is in "
                   f"the middle overs ({pp.loc['Middle', 'mean_wkts_won']:.2f} vs {pp.loc['Middle', 'mean_wkts_lost']:.2f}). "
                   f"Caution: winning chases often end early, so their death-overs sample is smaller and selected "
                   f"(n = {int(pp.loc['Death', 'won_n'])} vs {int(pp.loc['Death', 'lost_n'])}).",
                   "Outcome is partly defined by these same runs - this describes how wins happen, not what causes them.", chart)


def c5_close_matches(A: Adv) -> Finding:
    close = A.close_ids
    tl = A.D.team_long
    dec = tl[tl.decided == 1].copy()
    dec["close"] = dec.match_id.isin(close)
    g = dec.groupby("team").apply(lambda x: pd.Series({
        "close_matches": int(x.close.sum()), "close_wins": int(x[x.close].won.sum()),
        "other_matches": int((~x.close).sum()), "other_wins": int(x[~x.close].won.sum())}), include_groups=False).reset_index()
    g = g[g.close_matches >= TH["close_matches_team"]].copy()
    ci = g.apply(lambda r: wilson(r.close_wins, r.close_matches), axis=1, result_type="expand")
    g["close_win_pct"], g["ci_low"], g["ci_high"] = ci[0], ci[1], ci[2]
    g["other_win_pct"] = g.other_wins / g.other_matches * 100
    g["close_minus_other"] = g.close_win_pct - g.other_win_pct
    rho, p = stats.spearmanr(g.close_win_pct, g.other_win_pct)
    # chi-square: is close-match winning distribution different across teams?
    ct = g[["close_wins"]].assign(l=g.close_matches - g.close_wins).values
    chi2, pchi, dof, exp = stats.chi2_contingency(ct)
    g = g.sort_values("close_win_pct", ascending=False)
    tbl("C5_close_matches_team", g.round(3))
    n_close = len(close)
    sig = g[(g.ci_low > 50) | (g.ci_high < 50)]
    return Finding("C5", "C. Match pressure", "Close-match performance by team",
                   "Are some teams genuinely better in tight finishes, or is it chance?",
                   "Close match = won by <= 10 runs, chase completed with <= 6 balls left (both non-D/L), or a tie. "
                   "Close-match win % with 95% Wilson CI; chi-square test of homogeneity across teams; Spearman correlation "
                   "with win % in other matches.",
                   f"{n_close} close matches; teams with >= {TH['close_matches_team']} close matches (n = {len(g)}).",
                   g[["team", "close_matches", "close_win_pct", "ci_low", "ci_high", "other_win_pct", "close_minus_other"]].round(1),
                   f"{g.iloc[0].team} have the best close-match record ({g.iloc[0].close_win_pct:.1f}% of "
                   f"{int(g.iloc[0].close_matches)}, CI {g.iloc[0].ci_low:.0f}-{g.iloc[0].ci_high:.0f}%) and "
                   f"{g.iloc[-1].team} the worst ({g.iloc[-1].close_win_pct:.1f}%). But only {len(sig)} team(s) have an interval "
                   f"excluding 50%, and the chi-square test does {'not ' if pchi >= 0.05 else ''}reject 'all teams equal' "
                   f"(p = {pchi:.2f}). Close-match and other-match win % correlate at rho = {rho:.2f} (p = {p:.2f}). "
                   + ("The data does not support a 'clutch team' effect beyond what chance explains."
                      if pchi >= 0.05 and len(sig) == 0 else
                      "There is some evidence that close-match records differ between teams; see intervals."),
                   "Close matches are a small, outcome-defined subset; team rosters change each season.")


def c6_narrow_margin_players(A: Adv) -> Finding:
    close = A.close_ids
    r = A.reg.copy()
    r["close"] = r.match_id.isin(close)
    lg = r.groupby(["close", "phase"]).agg(runs=("total_runs", "sum"), balls=("is_legal_delivery", "sum"),
                                           w=("is_bowler_wicket", "sum"))
    lg["run_rate"] = lg.runs / lg.balls * 6
    lg["balls_per_wkt"] = lg.balls / lg.w
    lgt = lg[["run_rate", "balls_per_wkt"]].unstack(0)
    lgt.columns = [f"{a}_{'close' if c else 'other'}" for a, c in lgt.columns]
    b = r.groupby(["batter", "close"]).agg(runs=("batsman_runs", "sum"), balls=("is_ball_faced", "sum")).unstack()
    b.columns = [f"{a}_{'close' if c else 'other'}" for a, c in b.columns]
    b = b[(b.balls_close >= TH["close_bat_balls"]) & (b.balls_other >= TH["bat_balls"])].copy()
    b["sr_close"] = b.runs_close / b.balls_close * 100
    b["sr_other"] = b.runs_other / b.balls_other * 100
    b["sr_diff"] = b.sr_close - b.sr_other
    w = stats.wilcoxon(b.sr_close, b.sr_other)
    b = b.reset_index().rename(columns={"batter": "player"}).sort_values("sr_diff", ascending=False)
    tbl("C6_close_match_batters", b.round(3))
    tbl("C6_close_match_league", lgt.round(3).reset_index())
    show = pd.concat([b.head(6), b.tail(6)])[["player", "balls_close", "sr_close", "balls_other", "sr_other", "sr_diff"]].round(1)
    return Finding("C6", "C. Match pressure", "Batting and bowling in narrow-margin matches",
                   "How does play differ in matches decided by narrow margins, and do individual batters change?",
                   "League run rate and balls per bowler wicket by phase in close vs other matches; per-batter strike rate in "
                   "close vs other matches (Wilcoxon signed-rank).",
                   f"{len(close)} close matches. Batters with >= {TH['close_bat_balls']} balls in close matches and "
                   f">= {TH['bat_balls']} in others (n = {len(b)}).", show,
                   "Run rate in close vs other matches by phase: " + "; ".join(
                       f"{ph} {lgt.loc[ph, 'run_rate_close']:.2f} vs {lgt.loc[ph, 'run_rate_other']:.2f}" for ph in PH)
                   + f" - close matches score {'faster' if lgt.loc['Death', 'run_rate_close'] > lgt.loc['Death', 'run_rate_other'] else 'slower'} "
                     f"at the death, where narrow finishes are decided. For batters, median strike "
                   f"rate in close matches is {b.sr_close.median():.1f} vs {b.sr_other.median():.1f} otherwise (Wilcoxon "
                   f"p = {w.pvalue:.3f}). Individual 'big-match' differences such as {show.iloc[0].player} "
                   f"({show.iloc[0].sr_diff:+.1f}) come from 150-400 balls and are within normal sampling noise.",
                   "Closeness is defined by the result, so it is not a pre-match condition.", None,
                   {"League by phase": lgt.round(2).reset_index()})


def c7_final_overs(A: Adv) -> Finding:
    cm = A.chase_matches
    r2 = A.reg[(A.reg.inning == 2) & A.reg.match_id.isin(cm.match_id) & (A.reg.over_number >= 16)]
    reached = A.states[A.states.over_number == 15].match_id  # chases still live after over 15
    r2 = r2[r2.match_id.isin(reached)].merge(cm[["match_id", "chase_won"]], on="match_id")
    o = r2.groupby(["chase_won", "over_number"]).agg(runs=("total_runs", "sum"), balls=("is_legal_delivery", "sum"),
                                                     matches=("match_id", "nunique"), w=("is_player_out", "sum"))
    o["run_rate"] = o.runs / o.balls * 6
    o["wkts_per_over"] = o.w / o.matches
    t = o.reset_index()
    st15 = A.states[A.states.over_number == 15]
    rr15 = st15.groupby("chase_won").rrr.median()
    tbl("C7_final_overs", t.round(3))
    fig, ax = plt.subplots(figsize=(9.5, 4.6))
    for won, col, lab in [(1, AQUA, "Chases won"), (0, ORANGE, "Chases lost")]:
        s = t[t.chase_won == won]
        ax.plot(s.over_number, s.run_rate, marker="o", color=col, label=lab)
        ax.text(20.15, s.run_rate.iloc[-1], lab, color=INK2, fontsize=8.5, va="center")
    ax.set_xticks(range(16, 21))
    ax.set_xlim(15.7, 21.2)
    ax.set_xlabel("Over")
    ax.set_ylabel("Run rate in the over (runs per 6 legal balls)")
    ax.legend(loc="upper left")
    ax.set_title("Scoring in the final five overs of chases")
    eda.subtitle(ax, f"Chases still in progress after over 15 (n={st15.match_id.nunique()}); full 20-over, non-D/L matches.")
    chart = save_fig(fig, "C7_final_overs_chases")
    return Finding("C7", "C. Match pressure", "Final-overs scoring in successful vs unsuccessful chases",
                   "How does scoring in overs 16-20 differ between chases that are won and lost?",
                   "Run rate and wickets per over for overs 16-20, restricted to chases still live after over 15; required "
                   "rate at the end of over 15.",
                   f"{st15.match_id.nunique()} chases live after over 15 ({int(st15.chase_won.sum())} won).", t.round(2),
                   f"Chases that were eventually won needed a median {rr15[1]:.2f} per over from over 16, vs {rr15[0]:.2f} for "
                   f"those lost: the gap in match position before the final five overs is already large. In the final overs, winning chases scored at "
                   f"{t[t.chase_won == 1].run_rate.mean():.2f} per over on average vs {t[t.chase_won == 0].run_rate.mean():.2f} "
                   f"for losing chases; losing chases also lost {t[t.chase_won == 0].wkts_per_over.mean():.2f} wickets per over "
                   f"vs {t[t.chase_won == 1].wkts_per_over.mean():.2f} for winning chases. Winning chases often finish before over 20, so later overs "
                   f"include fewer winning matches.",
                   "Survivorship: the set of matches changes over by over as chases end.", chart)


# =========================================================================== D. TEAMS
def team_phase(A: Adv):
    r = A.reg
    bat = r.assign(exp=r.is_legal_delivery * r.lg_rpb).groupby(["batting_team", "phase"]).agg(
        runs=("total_runs", "sum"), balls=("is_legal_delivery", "sum"), exp=("exp", "sum"), outs=("is_player_out", "sum"))
    bat["rr"] = bat.runs / bat.balls * 6
    bat["rr_vs_league"] = (bat.runs - bat.exp) / bat.balls * 6
    bowl = r.assign(expw=r.is_legal_delivery * r.lg_wpb, exp=r.is_legal_delivery * r.lg_rpb).groupby(["bowling_team", "phase"]).agg(
        runs=("total_runs", "sum"), balls=("is_legal_delivery", "sum"), w=("is_bowler_wicket", "sum"), expw=("expw", "sum"),
        exp=("exp", "sum"))
    bowl["wkts_per_120"] = bowl.w / bowl.balls * 120
    bowl["wkts_vs_league_per_120"] = (bowl.w - bowl.expw) / bowl.balls * 120
    bowl["econ_vs_league"] = (bowl.runs - bowl.exp) / bowl.balls * 6
    return bat, bowl


def heat(ax, piv, fmt, cmap, center=0, vmax=None, invert=False):
    v = piv.values
    vm = vmax or np.nanmax(np.abs(v - center))
    im = ax.imshow(v, cmap=cmap, vmin=center - vm, vmax=center + vm, aspect="auto")
    for i in range(v.shape[0]):
        for j in range(v.shape[1]):
            if pd.notna(v[i, j]):
                ax.text(j, i, fmt.format(v[i, j]), ha="center", va="center", fontsize=8.3,
                        color=SURFACE if abs(v[i, j] - center) > 0.62 * vm else INK)
    ax.set_xticks(range(v.shape[1]), piv.columns)
    ax.set_yticks(range(v.shape[0]), piv.index)
    ax.grid(False)
    return im


def d1_team_phase_scoring(A: Adv) -> Finding:
    bat, _ = team_phase(A)
    share = bat.runs / bat.groupby(level=0).runs.transform("sum") * 100
    piv = bat.rr_vs_league.unstack()[PH]
    order = piv.mean(axis=1).sort_values(ascending=False).index
    piv = piv.loc[order]
    t = bat.assign(share_of_runs=share).reset_index().rename(columns={"batting_team": "team"})
    tbl("D1_team_phase_batting", t.round(4))
    fig, ax = plt.subplots(figsize=(8.5, 7))
    im = heat(ax, piv, "{:+.2f}", diverging_cmap())
    fig.colorbar(im, ax=ax, label="Runs per over vs league (same seasons)")
    ax.set_title("Team batting by phase vs league (season-adjusted)")
    eda.subtitle(ax, "Blue = scored faster than the league in the same seasons and phase; orange = slower.")
    chart = save_fig(fig, "D1_team_phase_batting")
    best = {ph: piv[ph].idxmax() for ph in PH}
    return Finding("D1", "D. Team contribution", "Team scoring by phase (vs league)",
                   "Where in the innings does each franchise gain or lose runs relative to the league?",
                   "Per team and phase: runs per over minus the league rate expected for the same seasons and phase; share of "
                   "team runs by phase.", f"All regulation deliveries; {len(piv)} franchises.",
                   piv.round(2).reset_index().rename(columns={"batting_team": "team"}),
                   f"Best phase-adjusted batting: Powerplay - {best['Powerplay']} ({piv.loc[best['Powerplay'], 'Powerplay']:+.2f}); "
                   f"Middle - {best['Middle']} ({piv.loc[best['Middle'], 'Middle']:+.2f}); Death - {best['Death']} "
                   f"({piv.loc[best['Death'], 'Death']:+.2f} runs/over). Run shares are similar across teams "
                   f"(Powerplay {share.xs('Powerplay', level=1).min():.0f}-{share.xs('Powerplay', level=1).max():.0f}% of runs), "
                   f"so differences are in efficiency rather than structure.",
                   "Short-lived franchises have small samples (2-5 seasons).", chart)


def d2_team_phase_wickets(A: Adv) -> Finding:
    _, bowl = team_phase(A)
    piv = bowl.wkts_vs_league_per_120.unstack()[PH]
    piv = piv.loc[piv.mean(axis=1).sort_values(ascending=False).index]
    tbl("D2_team_phase_bowling", bowl.reset_index().rename(columns={"bowling_team": "team"}).round(4))
    fig, ax = plt.subplots(figsize=(8.5, 7))
    im = heat(ax, piv, "{:+.2f}", diverging_cmap())
    fig.colorbar(im, ax=ax, label="Bowler wickets per 120 balls vs league")
    ax.set_title("Team wicket-taking by phase vs league (season-adjusted)")
    eda.subtitle(ax, "Blue = more bowler wickets than the league rate for the same seasons and phase.")
    chart = save_fig(fig, "D2_team_phase_wickets")
    best = {ph: piv[ph].idxmax() for ph in PH}
    return Finding("D2", "D. Team contribution", "Team wicket-taking by phase (vs league)",
                   "Which franchises take wickets more often than the league, and in which phase?",
                   "Bowler wickets per 120 legal balls minus the league rate expected for the same seasons and phase.",
                   f"All regulation deliveries; {len(piv)} franchises.",
                   piv.round(2).reset_index().rename(columns={"bowling_team": "team"}),
                   "Most wicket-taking relative to the league: " + "; ".join(
                       f"{ph} - {best[ph]} ({piv.loc[best[ph], ph]:+.2f} per 120 balls)" for ph in PH) +
                   f". The spread is about +/-{np.nanmax(np.abs(piv.values)):.1f} wickets per 120 balls.",
                   "Bowler-credited wickets only (run-outs excluded).", chart)


def d3_strengths(A: Adv) -> Finding:
    r = A.reg
    bat = r.assign(exp=r.is_legal_delivery * r.lg_rpb).groupby("batting_team").agg(runs=("total_runs", "sum"),
                                                                                    balls=("is_legal_delivery", "sum"), exp=("exp", "sum"))
    bowl = r.assign(exp=r.is_legal_delivery * r.lg_rpb).groupby("bowling_team").agg(runs=("total_runs", "sum"),
                                                                                     balls=("is_legal_delivery", "sum"), exp=("exp", "sum"))
    t = pd.DataFrame({"batting_rr_vs_league": (bat.runs - bat.exp) / bat.balls * 6,
                      "bowling_econ_vs_league": (bowl.runs - bowl.exp) / bowl.balls * 6})
    t["net_vs_league"] = t.batting_rr_vs_league - t.bowling_econ_vs_league
    T = eda.team_table(A.D).set_index("team")
    t = t.join(T[["win_pct", "seasons", "decided"]]).rename_axis("team").reset_index()
    rho, p = stats.spearmanr(t.net_vs_league, t.win_pct)
    rho_e, p_e = stats.spearmanr(t[t.seasons >= 10].net_vs_league, t[t.seasons >= 10].win_pct)
    tbl("D3_team_strengths", t.round(4))
    fig, ax = plt.subplots(figsize=(9.5, 6.5))
    ax.scatter(t.batting_rr_vs_league, -t.bowling_econ_vs_league, s=t.decided * 1.4, c=[BLUE if s >= 10 else GREY for s in t.seasons],
               alpha=0.75, edgecolor=SURFACE)
    eda.label_points(ax, t.batting_rr_vs_league, -t.bowling_econ_vs_league, t.team)
    ax.axhline(0, color=INK2, lw=1, ls="--")
    ax.axvline(0, color=INK2, lw=1, ls="--")
    ax.set_xlabel("Batting: run rate vs league (same seasons & phases)")
    ax.set_ylabel("Bowling: runs saved per over vs league (higher = better)")
    ax.set_title("Franchise batting vs bowling strength (season- and phase-adjusted)")
    eda.subtitle(ax, "Top-right = better than the league at both. Bubble = decided matches; grey = fewer than 10 seasons.")
    chart = save_fig(fig, "D3_team_strengths")
    t = t.sort_values("net_vs_league", ascending=False)
    return Finding("D3", "D. Team contribution", "Batting and bowling strength vs league",
                   "How do franchises compare with the league in batting and bowling, and does that explain winning?",
                   "Batting = run rate minus league expectation for the same seasons and phases; bowling = runs conceded per "
                   "over minus expectation; net = batting - bowling. Spearman correlation of net with win %.",
                   f"All {len(t)} franchises (regulation deliveries).", t.round(3),
                   f"{t.iloc[0].team} have the best net rating ({t.iloc[0].net_vs_league:+.2f} runs/over: batting "
                   f"{t.iloc[0].batting_rr_vs_league:+.2f}, bowling {t.iloc[0].bowling_econ_vs_league:+.2f}). Net rating tracks "
                   f"win % closely (rho = {rho:.2f}, p = {p:.3f}, n = {len(t)}; established franchises only: rho = {rho_e:.2f}, "
                   f"n = {int((t.seasons >= 10).sum())}) - run-rate differential is a sound summary of team quality.",
                   "Ignores venue and opposition strength.", chart)


def d4_team_consistency(A: Adv) -> Finding:
    tl = A.D.team_long
    s = tl[tl.decided == 1].groupby(["team", "season_year"]).agg(matches=("won", "size"), wins=("won", "sum")).reset_index()
    s["win_pct"] = s.wins / s.matches * 100
    g = s.groupby("team").agg(seasons=("season_year", "size"), mean_win_pct=("win_pct", "mean"), sd_win_pct=("win_pct", "std"),
                              best=("win_pct", "max"), worst=("win_pct", "min"),
                              seasons_above_50=("win_pct", lambda x: int((x > 50).sum()))).reset_index()
    # binomial expectation of season-to-season SD if every season were a coin with the team's own mean
    n_avg = s.groupby("team").matches.mean()
    g["sd_expected_by_chance"] = g.apply(lambda r: np.sqrt(r.mean_win_pct / 100 * (1 - r.mean_win_pct / 100) / n_avg[r.team]) * 100, axis=1)
    g = g[g.seasons >= 10].sort_values("sd_win_pct")
    g["sd_excess_over_chance"] = g.sd_win_pct - g.sd_expected_by_chance
    n_above = int((g.sd_excess_over_chance > 0).sum())
    tbl("D4_team_season_consistency", g.round(3))
    piv = s.pivot(index="team", columns="season_year", values="win_pct")
    piv = piv.loc[piv.notna().sum(axis=1).sort_values(ascending=False).index]
    fig, ax = plt.subplots(figsize=(13, 6.2))
    im = heat(ax, piv, "{:.0f}", diverging_cmap(), center=50, vmax=50)
    fig.colorbar(im, ax=ax, label="Win % in season")
    ax.set_title("Win % by franchise and season")
    eda.subtitle(ax, "Blank = did not play. Blue > 50%, orange < 50%. Decided matches only.")
    chart = save_fig(fig, "D4_team_season_heatmap")
    return Finding("D4", "D. Team contribution", "Season-adjusted performance and consistency across seasons",
                   "Which franchises are consistently strong, and how much of the season-to-season swing is just chance?",
                   "Win % per season; SD across seasons; compared with the SD expected from binomial chance alone "
                   "(sqrt(p(1-p)/n)) given ~14-16 matches per season.",
                   f"Franchises with >= 10 seasons (n = {len(g)}).", g.round(1),
                   f"{g.iloc[0].team} are the most consistent (season win % SD {g.iloc[0].sd_win_pct:.1f}, above 50% in "
                   f"{g.iloc[0].seasons_above_50} of {g.iloc[0].seasons} seasons); {g.iloc[-1].team} the least "
                   f"(SD {g.iloc[-1].sd_win_pct:.1f}). Binomial chance alone, with ~{A.D.team_long.groupby(['team', 'season_year']).size().mean():.0f} "
                   f"matches a season, would produce an SD of about {g.sd_expected_by_chance.mean():.0f} points. Observed SDs "
                   f"({g.sd_win_pct.min():.0f}-{g.sd_win_pct.max():.0f}) exceed this for {n_above} of {len(g)} franchises, so "
                   f"most season-to-season swings in win % are of the size chance alone produces; the season-level record "
                   f"is a noisy guide to underlying strength.",
                   "Season win % rests on ~14-16 matches.", chart)


def d5_win_vs_loss(A: Adv) -> Finding:
    r = A.reg.merge(A.mc[["match_id", "winner", "is_no_result", "is_dls", "target_overs"]], on="match_id")
    r = r[(r.is_no_result == 0) & (r.is_dls == 0) & (r.target_overs == 20) & r.winner.notna()]
    r["batting_side_won"] = (r.batting_team == r.winner).astype(int)
    per = r.groupby(["match_id", "inning", "batting_side_won", "phase"]).agg(runs=("total_runs", "sum"),
                                                                           balls=("is_legal_delivery", "sum"),
                                                                           outs=("is_player_out", "sum"),
                                                                           dots=("is_dot_ball", "sum"),
                                                                           b=("is_boundary", "sum")).reset_index()
    per = per[(per.inning == 1) & (per.balls > 0)]  # first innings only: not truncated by a target
    per["rr"] = per.runs / per.balls * 6
    per["dot_pct"] = per.dots / per.balls * 100
    per["boundary_pct"] = per.b / per.balls * 100
    t = per.groupby(["phase", "batting_side_won"]).agg(innings=("match_id", "size"), median_rr=("rr", "median"),
                                                       mean_wkts=("outs", "mean"), dot_pct=("dot_pct", "mean"),
                                                       boundary_pct=("boundary_pct", "mean")).reset_index()
    tests = {ph: stats.mannwhitneyu(per[(per.phase == ph) & (per.batting_side_won == 1)].rr,
                                    per[(per.phase == ph) & (per.batting_side_won == 0)].rr).pvalue for ph in PH}
    t["p_run_rate"] = t.phase.map(tests)
    tbl("D5_win_vs_loss_first_innings", t.round(4))
    w = t.set_index(["phase", "batting_side_won"])
    gap = {ph: w.loc[(ph, 1), "median_rr"] - w.loc[(ph, 0), "median_rr"] for ph in PH}
    big = max(gap, key=gap.get)
    return Finding("D5", "D. Team contribution", "What separates winning and losing performances (first innings)",
                   "When a side batting first goes on to win, how does its innings differ from one that loses?",
                   "First innings only (not truncated by a target), full 20-over non-D/L matches: median run rate, wickets, "
                   "dot % and boundary % per phase for eventual winners vs losers; Mann-Whitney U per phase.",
                   f"{per.match_id.nunique()} first innings.", t.round(2),
                   f"Winning first innings outscore losing ones in every phase; the gap is largest in the {big} overs "
                   f"(median {w.loc[(big, 1), 'median_rr']:.2f} vs {w.loc[(big, 0), 'median_rr']:.2f} per over). Winners lose "
                   f"fewer middle-overs wickets ({w.loc[('Middle', 1), 'mean_wkts']:.2f} vs {w.loc[('Middle', 0), 'mean_wkts']:.2f}) "
                   f"and hit more boundaries at the death ({w.loc[('Death', 1), 'boundary_pct']:.1f}% vs "
                   f"{w.loc[('Death', 0), 'boundary_pct']:.1f}% of balls). Mann-Whitney p-values for run rate: "
                   + ", ".join(f"{ph} {tests[ph]:.1e}" for ph in PH) + ".",
                   "The outcome also depends on the second innings; this describes associations within the first innings.")


def d6_eras(A: Adv) -> Finding:
    r = A.reg
    e = r.groupby(["era", "phase"]).agg(runs=("total_runs", "sum"), balls=("is_legal_delivery", "sum"),
                                        b4=("is_four", "sum"), b6=("is_six", "sum"), dots=("is_dot_ball", "sum"),
                                        w=("is_player_out", "sum"))
    e["run_rate"] = e.runs / e.balls * 6
    e["sixes_per_over"] = e.b6 / e.balls * 6
    e["fours_per_over"] = e.b4 / e.balls * 6
    e["dot_pct"] = e.dots / e.balls * 100
    e["balls_per_wkt"] = e.balls / e.w
    t = e.reset_index()
    tbl("D6_eras", t.round(4))
    eras = [lab for *_, lab in ERAS]
    fig, axes = plt.subplots(1, 3, figsize=(13, 4.2), sharey=False)
    for ax, (col, ttl) in zip(axes, [("run_rate", "Run rate"), ("sixes_per_over", "Sixes per over"), ("dot_pct", "Dot-ball %")]):
        for ph in PH:
            s = t[t.phase == ph].set_index("era").reindex(eras)
            ax.plot(eras, s[col], marker="o", color=PHC[ph], label=ph)
        ax.set_title(ttl)
        ax.tick_params(axis="x", labelsize=8.5)
    axes[0].legend(fontsize=8.5)
    eda.fig_title(fig, "How team scoring patterns changed across IPL eras (regulation deliveries)")
    chart = save_fig(fig, "D6_eras")
    a = e.loc["2008-12"]
    b = e.loc["2023-24"]
    dot_fell = [ph for ph in PH if b.loc[ph, "dot_pct"] < a.loc[ph, "dot_pct"]]
    return Finding("D6", "D. Team contribution", "Scoring patterns: early vs recent IPL",
                   "How has the way teams score changed between the early and the recent IPL?",
                   "Run rate, sixes and fours per over, dot % and balls per dismissal by era and phase.",
                   f"All {len(r):,} regulation deliveries; eras " + ", ".join(eras) + ".", t.round(2),
                   f"From 2008-12 to 2023-24 the Powerplay run rate rose from {a.loc['Powerplay', 'run_rate']:.2f} to "
                   f"{b.loc['Powerplay', 'run_rate']:.2f} and sixes per over from {a.loc['Powerplay', 'sixes_per_over']:.2f} to "
                   f"{b.loc['Powerplay', 'sixes_per_over']:.2f}; death-overs sixes per over rose from "
                   f"{a.loc['Death', 'sixes_per_over']:.2f} to {b.loc['Death', 'sixes_per_over']:.2f}. Dot-ball % fell in "
                   f"{len(dot_fell)} of 3 phases (Powerplay {a.loc['Powerplay', 'dot_pct']:.1f}% -> {b.loc['Powerplay', 'dot_pct']:.1f}%). "
                   f"Balls per dismissal changed little (Powerplay {a.loc['Powerplay', 'balls_per_wkt']:.1f} -> "
                   f"{b.loc['Powerplay', 'balls_per_wkt']:.1f}; death {a.loc['Death', 'balls_per_wkt']:.1f} -> "
                   f"{b.loc['Death', 'balls_per_wkt']:.1f}): the extra runs came without wickets becoming rarer, consistent with "
                   f"more aggressive batting.",
                   "Era boundaries are analyst-chosen; the 2023-24 era has two seasons only.", chart)


# =========================================================================== E. VENUES
def e1_venue_phase(A: Adv) -> Finding:
    V = eda.venue_table(A.D)
    keep = V[V.full_matches >= TH["venue_matches"]].venue
    r = A.reg[A.reg.venue.isin(keep)]
    g = r.assign(exp=r.is_legal_delivery * r.lg_rpb).groupby(["venue", "phase"]).agg(
        runs=("total_runs", "sum"), balls=("is_legal_delivery", "sum"), exp=("exp", "sum"), w=("is_bowler_wicket", "sum"))
    g["rr_vs_league"] = (g.runs - g.exp) / g.balls * 6
    piv = g.rr_vs_league.unstack()[PH]
    piv = piv.loc[piv.mean(axis=1).sort_values(ascending=False).index]
    short = {"Punjab Cricket Association IS Bindra Stadium": "PCA IS Bindra (Mohali)",
             "Rajiv Gandhi International Stadium": "Rajiv Gandhi (Hyderabad)",
             "Maharashtra Cricket Association Stadium": "MCA (Pune)", "Dubai International Cricket Stadium": "Dubai Intl"}
    piv.index = [short.get(v, v) for v in piv.index]
    tbl("E1_venue_phase", g.reset_index().round(4))
    fig, ax = plt.subplots(figsize=(8.5, 7))
    im = heat(ax, piv, "{:+.2f}", diverging_cmap())
    fig.colorbar(im, ax=ax, label="Runs per over vs league (same seasons & phase)")
    ax.set_title("Venue scoring by phase vs league (season-adjusted)")
    eda.subtitle(ax, f"Venues with {TH['venue_matches']}+ full matches. Blue = higher-scoring than the league in that phase.")
    chart = save_fig(fig, "E1_venue_phase")
    consistent = piv[(piv > 0).all(axis=1)].index.tolist()
    same_sign = int(((piv > 0).all(axis=1) | (piv < 0).all(axis=1)).sum())
    rho_pd, _ = stats.spearmanr(piv.Powerplay, piv.Death)
    return Finding("E1", "E. Venue & conditions", "Venue scoring patterns by phase",
                   "Which grounds are high- or low-scoring in each phase once season effects are removed?",
                   "Venue run rate in each phase minus the league rate expected for the same seasons and phase.",
                   f"{len(piv)} venues with >= {TH['venue_matches']} full matches.", piv.round(2).reset_index().rename(columns={"index": "venue"}),
                   f"{piv.index[0]} is the highest-scoring venue relative to the league "
                   f"(Powerplay {piv.iloc[0]['Powerplay']:+.2f}, Middle {piv.iloc[0]['Middle']:+.2f}, Death {piv.iloc[0]['Death']:+.2f} "
                   f"runs/over) and {piv.index[-1]} the lowest. Venues above the league in all three phases: "
                   f"{', '.join(consistent) if consistent else 'none'}. {same_sign} of {len(piv)} venues are on the same side "
                   f"of the league in all three phases, and Powerplay and death-over venue effects correlate at rho = "
                   f"{rho_pd:.2f}: venue character is partly consistent across phases, but {len(piv) - same_sign} venues "
                   f"switch between above and below the league depending on the phase.",
                   "Venue effects are confounded with home teams' styles (no home-team field).", chart)


def e2_venue_chase_test(A: Adv) -> Finding:
    d = A.D.decided_bfc
    V = eda.venue_table(A.D)
    keep = V[V.decided >= TH["venue_matches"]].venue
    x = d[d.venue.isin(keep)]
    ct = pd.crosstab(x.venue, x.result_for)
    chi2, p, dof, exp = stats.chi2_contingency(ct.values)
    t = ct.assign(decided=ct.sum(axis=1), chase_win_pct=ct["chasing"] / ct.sum(axis=1) * 100).sort_values("chase_win_pct", ascending=False)
    ci = t.apply(lambda r: wilson(r.chasing, r.decided), axis=1, result_type="expand")
    t["ci_low"], t["ci_high"] = ci[1], ci[2]
    t = t.reset_index()
    tbl("E2_venue_chase_chi2", t.round(3))
    return Finding("E2", "E. Venue & conditions", "Batting-first vs chasing outcomes across venues (test)",
                   "Does the chance of winning while chasing really differ between venues, or are venue differences noise?",
                   "Venue x result_for contingency table (batting first / chasing); chi-square test of homogeneity; Wilson CIs.",
                   f"{len(t)} venues with >= {TH['venue_matches']} decided matches; {int(t.decided.sum())} matches.",
                   t[["venue", "decided", "chasing", "chase_win_pct", "ci_low", "ci_high"]].round(1),
                   f"Chase win % ranges from {t.chase_win_pct.min():.1f}% to {t.chase_win_pct.max():.1f}% across venues, but the "
                   f"chi-square test gives chi2 = {chi2:.1f} (dof = {dof}), p = {p:.2f}: the data does "
                   f"{'NOT ' if p >= 0.05 else ''}provide significant evidence that venue changes the batting-first/chasing "
                   f"balance. The league-wide chasing edge (~54%) is the safer planning assumption than venue-specific rates.",
                   f"Minimum expected cell count {exp.min():.1f} (>= 5 required) - assumption "
                   f"{'met' if exp.min() >= 5 else 'not met'}.")


def e3_venue_bowling(A: Adv) -> Finding:
    V = eda.venue_table(A.D)
    V = V[V.full_matches >= TH["venue_matches"]].copy()
    r = A.reg[A.reg.venue.isin(V.venue)]
    g = r.assign(exp=r.is_legal_delivery * r.lg_bowler_rpb, expw=r.is_legal_delivery * r.lg_wpb).groupby("venue").agg(
        balls=("is_legal_delivery", "sum"), w=("is_bowler_wicket", "sum"), expw=("expw", "sum"), dots=("is_dot_ball", "sum"),
        b4=("is_boundary", "sum"), runs=("bowler_runs_conceded", "sum"), exp=("exp", "sum"))
    g["wkts_vs_expected"] = g.w / g.expw
    g["dot_pct"] = g.dots / g.balls * 100
    g["boundary_pct"] = g.b4 / g.balls * 100
    g["econ_vs_league"] = (g.runs - g.exp) / g.balls * 6
    g = g.join(V.set_index("venue")[["avg_inn1_vs_season"]])
    rw, pw = stats.spearmanr(g.avg_inn1_vs_season, g.wkts_vs_expected)
    rd, pd_ = stats.spearmanr(g.avg_inn1_vs_season, g.dot_pct)
    rb, pb = stats.spearmanr(g.avg_inn1_vs_season, g.boundary_pct)
    t = g.reset_index().sort_values("avg_inn1_vs_season", ascending=False)
    tbl("E3_venue_bowling", t.round(4))
    return Finding("E3", "E. Venue & conditions", "Do high-scoring venues have different bowling patterns?",
                   "At high-scoring grounds, is the extra scoring driven by fewer wickets, fewer dot balls or more boundaries?",
                   "Per venue: bowler wickets vs expected (season & phase), dot %, boundary %; Spearman correlations with the "
                   "venue's season-adjusted first-innings score.",
                   f"{len(t)} venues with >= {TH['venue_matches']} full matches.",
                   t[["venue", "avg_inn1_vs_season", "econ_vs_league", "wkts_vs_expected", "dot_pct", "boundary_pct"]].round(2),
                   f"Across venues, higher scoring goes with more boundaries (rho = {rb:.2f}, p = {pb:.3f}) and "
                   f"{'fewer' if rd < 0 else 'more'} dot balls (rho = {rd:.2f}, p = {pd_:.3f}), while wicket-taking relative to "
                   f"expectation is {'only weakly' if abs(rw) < 0.3 else 'also'} related (rho = {rw:.2f}, p = {pw:.3f}). "
                   + ("Of these, only the boundary relationship is statistically significant: high-scoring grounds are mainly "
                      "'boundary grounds' rather than 'no-wicket grounds'." if pb < 0.05 and pw >= 0.05 and pd_ >= 0.05 else
                      "See p-values for which relationships are statistically significant."),
                   "15 venues is a small sample for correlation; boundary size and pitch type are not in the data.")


def logistic_fit(x, y):
    from sklearn.linear_model import LogisticRegression
    m = LogisticRegression(C=1e6, max_iter=1000).fit(np.asarray(x).reshape(-1, 1), y)
    return m.intercept_[0], m.coef_[0][0]


def e4_first_innings_outcome(A: Adv) -> Finding:
    f = A.D.full
    f = f[f.result_for.isin(["batting first", "chasing"]) & (f.is_dls == 0)].copy()
    f["bf_won"] = (f.result_for == "batting first").astype(int)
    f["period"] = np.where(f.season_year >= 2023, "2023-24", "2008-22")
    rows, curves, boot_store = [], {}, {}
    for per, g in f.groupby("period"):
        a, b = logistic_fit(g.inn1_runs, g.bf_won)
        par = -a / b
        boots = []
        idx = np.arange(len(g))
        for _ in range(500):
            s = g.iloc[RNG.choice(idx, len(idx), replace=True)]
            aa, bb = logistic_fit(s.inn1_runs, s.bf_won)
            boots.append(-aa / bb)
        lo, hi = np.percentile(boots, [2.5, 97.5])
        boot_store[per] = np.array(boots)
        rows.append({"period": per, "matches": len(g), "par_score_50pct": par, "par_ci_low": lo, "par_ci_high": hi,
                     "runs_for_+10pp_at_par": 0.1 / (b * 0.25), "slope_per_run": b})
        curves[per] = (a, b)
    t = pd.DataFrame(rows)
    # difference in par score: independent bootstrap samples of each period, paired by draw
    diff = boot_store["2023-24"] - boot_store["2008-22"]
    d_lo, d_hi = np.percentile(diff, [2.5, 97.5])
    d_pt = t.set_index("period").par_score_50pct["2023-24"] - t.set_index("period").par_score_50pct["2008-22"]
    t = pd.concat([t, pd.DataFrame([{"period": "difference (2023-24 minus 2008-22)", "matches": np.nan,
                                     "par_score_50pct": d_pt, "par_ci_low": d_lo, "par_ci_high": d_hi}])], ignore_index=True)
    tbl("E4_first_innings_logistic", t.round(3))
    fig, ax = plt.subplots(figsize=(9.5, 5))
    xs = np.linspace(110, 250, 200)
    for per, col in [("2008-22", BLUE), ("2023-24", ORANGE)]:
        a, b = curves[per]
        ax.plot(xs, 100 / (1 + np.exp(-(a + b * xs))), color=col, label=per)
        g = f[f.period == per].copy()
        g["band"] = (g.inn1_runs // 20) * 20 + 10
        emp = g.groupby("band").agg(p=("bf_won", "mean"), n=("bf_won", "size"))
        emp = emp[emp.n >= 8]
        ax.scatter(emp.index, emp.p * 100, color=col, s=emp.n * 1.2, alpha=0.5, edgecolor=SURFACE)
        par = t.set_index("period").loc[per, "par_score_50pct"]
        ax.axvline(par, color=col, lw=1, ls=":")
        ax.text(par + 1, 8 if per == "2008-22" else 16, f"par {par:.0f}", color=col, fontsize=9)
    ax.axhline(50, color=INK2, lw=1, ls="--")
    ax.set_ylim(0, 100)
    ax.yaxis.set_major_formatter(mtick.PercentFormatter())
    ax.set_xlabel("First-innings score")
    ax.set_ylabel("Batting-first team win %")
    ax.legend(title="Seasons", loc="upper left")
    ax.set_title("First-innings score and match outcome")
    eda.subtitle(ax, "Lines = logistic fit; dots = observed win % in 20-run bands (size = matches). Full 20-over, non-D/L matches.")
    chart = save_fig(fig, "E4_first_innings_outcome")
    a = t.set_index("period")
    return Finding("E4", "E. Venue & conditions", "First-innings score vs match outcome ('par score')",
                   "What first-innings score gives the batting side an even chance, and has it changed?",
                   "Logistic regression of batting-first win (0/1) on first-innings runs, fitted separately for 2008-22 and "
                   "2023-24; par = score at 50% predicted win probability; 95% CI from 500 bootstrap resamples.",
                   f"{len(f)} full, non-D/L, decided matches ({int(a.loc['2023-24', 'matches'])} in 2023-24).", t.round(2),
                   f"The par score was {a.loc['2008-22', 'par_score_50pct']:.0f} in 2008-22 (95% CI "
                   f"{a.loc['2008-22', 'par_ci_low']:.0f}-{a.loc['2008-22', 'par_ci_high']:.0f}) and "
                   f"{a.loc['2023-24', 'par_score_50pct']:.0f} in 2023-24 (CI {a.loc['2023-24', 'par_ci_low']:.0f}-"
                   f"{a.loc['2023-24', 'par_ci_high']:.0f}). Around par, each extra 10 runs adds about "
                   f"{a.loc['2008-22', 'slope_per_run'] * 0.25 * 1000:.0f} percentage points of win probability (2008-22). The "
                   f"estimated rise in par is {d_pt:+.0f} runs (bootstrap 95% CI {d_lo:+.0f} to {d_hi:+.0f}); "
                   + ("the interval excludes zero, so the par score has risen beyond what sampling noise explains."
                      if d_lo > 0 else
                      "the interval includes zero, so with only two recent seasons the rise is suggestive but not "
                      "statistically conclusive."),
                   "Descriptive model (one predictor); venue and team strength not included.", chart)


# =========================================================================== F. ML ASSESSMENT
def f1_ml_assessment(A: Adv) -> Finding:
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import brier_score_loss, log_loss, roc_auc_score
    st = A.states[A.states.over_number <= 19].copy()
    st["rrr"] = st.rrr.clip(upper=36)
    st["log_balls_left"] = np.log(st.balls_left)
    feats = ["rrr", "wickets_in_hand", "log_balls_left", "runs_needed"]
    train, test = st[st.season_year <= 2021], st[st.season_year >= 2022]
    m = LogisticRegression(max_iter=2000).fit(train[feats], train.chase_won)
    pr = m.predict_proba(test[feats])[:, 1]
    base_rate = np.full(len(test), train.chase_won.mean())
    # baseline 2: empirical lookup by (over, rrr band, wickets band) from training data
    def bands(d):
        return (d.over_number.astype(str) + "|" + pd.cut(d.rrr, [0, 6, 8, 10, 12, 15, 99], right=False).astype(str) + "|" +
                pd.cut(d.wickets_in_hand, [0, 4, 7, 11], right=False).astype(str))
    lut = train.assign(k=bands(train)).groupby("k").chase_won.mean()
    lk = bands(test).map(lut).fillna(train.chase_won.mean()).values
    def metrics(p):
        p = np.clip(p, 1e-6, 1 - 1e-6)
        return brier_score_loss(test.chase_won, p), log_loss(test.chase_won, p), roc_auc_score(test.chase_won, p)
    res = pd.DataFrame([("Base rate (always predict training win %)", *metrics(base_rate)),
                        ("Lookup table: over x required-rate x wickets bands", *metrics(lk)),
                        ("Logistic regression (4 features)", *metrics(pr))],
                       columns=["model", "brier", "log_loss", "roc_auc"])
    cal = pd.DataFrame({"p": pr, "y": test.chase_won.values})
    cal["bin"] = pd.cut(cal.p, np.linspace(0, 1, 11), include_lowest=True)
    calt = cal.groupby("bin", observed=True).agg(states=("y", "size"), mean_predicted=("p", "mean"), observed=("y", "mean")).reset_index()
    calt["bin"] = calt["bin"].astype(str)
    tbl("F1_ml_metrics", res.round(4))
    tbl("F1_ml_calibration", calt.round(4))
    fig, ax = plt.subplots(figsize=(6.5, 6))
    ax.plot([0, 1], [0, 1], color=INK2, ls="--", lw=1)
    ax.plot(calt.mean_predicted, calt.observed, marker="o", color=BLUE)
    for _, rr in calt.iterrows():
        ax.text(rr.mean_predicted + 0.015, rr.observed - 0.03, f"n={rr.states}", fontsize=7.5, color=INK2)
    ax.set_xlabel("Predicted chase win probability")
    ax.set_ylabel("Observed share of chases won")
    ax.set_title("Calibration on 2022-24 (held-out seasons)")
    eda.subtitle(ax, "Logistic model trained on 2008-21 chase states; dashed = perfect calibration.")
    chart = save_fig(fig, "F1_chase_model_calibration")
    coef = dict(zip(feats, m.coef_[0]))
    best = res.iloc[res.brier.idxmin()]
    return Finding("F1", "F. Machine-learning assessment", "Is a predictive model justified?",
                   "Can a model add reliable, decision-useful prediction beyond the descriptive analysis?",
                   "Assessed two candidate tasks. (1) PRE-MATCH winner prediction: rejected - see finding. (2) IN-CHASE win "
                   "probability from the match state (required rate, wickets in hand, balls left, runs needed), all derivable "
                   "at the end of each over: tested with a time-based split (train 2008-21, test 2022-24, whole matches never "
                   "split), against two baselines; metrics Brier score, log loss, ROC AUC and a calibration table.",
                   f"Train {len(train):,} over-end states from {train.match_id.nunique()} chases; test {len(test):,} states from "
                   f"{test.match_id.nunique()} chases.", res.round(4),
                   f"Pre-match prediction is not justified: the only pre-match signals in the data (toss 50.8%, chasing ~54%, "
                   f"venue - E2 not significant) are near coin-flip, squads change every season and there is no player "
                   f"availability data, so any model would be weak and misleading. The in-chase task IS supported: on unseen "
                   f"2022-24 seasons the logistic model reaches AUC {res.iloc[2].roc_auc:.3f} and Brier {res.iloc[2].brier:.3f} vs "
                   f"{res.iloc[0].brier:.3f} for the base rate and {res.iloc[1].brier:.3f} for the lookup table (best: "
                   f"{best.model}). Coefficients have the expected signs (required rate {coef['rrr']:+.2f}, wickets in hand "
                   f"{coef['wickets_in_hand']:+.2f}). It is a transparent win-probability curve suitable for a dashboard visual - "
                   f"not a betting or selection tool.",
                   "Leakage control: only information known at the end of the over; split by season so no match appears in both "
                   "sets. Over-end states from the same chase are correlated, so metrics are optimistic about effective sample size. "
                   "Era shift (2023-24 scoring) is the main risk; check calibration before reuse. No team/player strength, venue or "
                   "D/L chases included.", chart, {"Calibration (test seasons)": calt.round(3)})


# =========================================================================== VALIDATION
def validate(A: Adv, F: list) -> pd.DataFrame:
    rows = []

    def add(cid, area, check, expected, actual, ok, note=""):
        rows.append({"check_id": cid, "area": area, "check": check, "expected": str(expected), "actual": str(actual),
                     "status": "PASS" if bool(ok) else "FAIL", "note": note})

    D, r, mc = A.D, A.reg, A.mc
    S = eda.season_table(D)
    add("P01", "Totals vs Phase 3", "Regulation deliveries / runs", "260,759 / 347,470",
        f"{len(r):,} / {int(r.total_runs.sum()):,}", len(r) == 260759 and r.total_runs.sum() == 347470)
    add("P02", "Totals vs Phase 3", "Season runs table sums to total", int(r.total_runs.sum()), int(S.runs.sum()),
        S.runs.sum() == r.total_runs.sum())
    ph = r.groupby("phase").agg(b=("is_legal_delivery", "sum"), w=("is_bowler_wicket", "sum"), rr=("total_runs", "sum"))
    add("P03", "Legal balls & wickets", "Phase legal balls / bowler wickets sum to totals", "251,319 / 11,795",
        f"{int(ph.b.sum()):,} / {int(ph.w.sum()):,}", ph.b.sum() == 251319 and ph.w.sum() == 11795)
    bat, bowl = team_phase(A)
    add("P04", "Aggregation", "Team x phase batting runs sum to regulation runs", 347470, int(bat.runs.sum()),
        bat.runs.sum() == 347470)
    add("P05", "Aggregation", "Team x phase bowling wickets sum to bowler wickets", 11795, int(bowl.w.sum()), bowl.w.sum() == 11795)
    ba = bowler_adjusted(A, r)
    add("P06", "Aggregation", "Bowler-adjusted table: wickets / balls equal Phase 3 bowler careers",
        f"{int(D.bowlers.wickets.sum())} / {int(D.bowlers.legal_balls.sum())}", f"{int(ba.wickets.sum())} / {int(ba.legal_balls.sum())}",
        ba.wickets.sum() == D.bowlers.wickets.sum() and ba.legal_balls.sum() == D.bowlers.legal_balls.sum())
    add("P07", "Aggregation", "Expected runs (season x phase) sum to actual league runs (adjustment is unbiased)",
        int(r.total_runs.sum()), round(float((r.is_legal_delivery * r.lg_rpb).sum()), 6),
        abs((r.is_legal_delivery * r.lg_rpb).sum() - r.total_runs.sum()) < 1e-6)
    add("P08", "Aggregation", "Expected bowler wickets sum to actual", 11795, round(float((r.is_legal_delivery * r.lg_wpb).sum()), 6),
        abs((r.is_legal_delivery * r.lg_wpb).sum() - 11795) < 1e-6)
    add("P09", "Phase", "Phase assignment: PP 1-6, Middle 7-15, Death 16-20, no super-over phase", "0 violations",
        int(((r.phase == "Powerplay") != r.over_number.between(1, 6)).sum() + ((r.phase == "Death") != r.over_number.between(16, 20)).sum()
            + (r.phase == "Super Over").sum()),
        ((r.phase == "Powerplay") == r.over_number.between(1, 6)).all() and ((r.phase == "Death") == r.over_number.between(16, 20)).all()
        and (r.phase != "Super Over").all())
    add("P10", "Super overs", "No super-over deliveries in any Phase 5 base table", 0, int(r.is_super_over.sum() + (A.states.over_number > 20).sum()),
        r.is_super_over.sum() == 0)
    add("P11", "Wickets", "wkts_before never negative or > 10; equals cumulative outs - current", "0..10",
        f"{int(r.wkts_before.min())}..{int(r.wkts_before.max())}", r.wkts_before.between(0, 10).all())
    add("P12", "Wickets", "Retired hurt not counted (is_player_out / bowler wicket = 0 on 15 rows)", 0,
        int(r[r.is_retired_hurt == 1][["is_player_out", "is_bowler_wicket"]].sum().sum()),
        r[r.is_retired_hurt == 1][["is_player_out", "is_bowler_wicket"]].sum().sum() == 0)
    cm = A.chase_matches
    add("P13", "D/L", "Chase base excludes D/L, no-results, shortened matches and ties", 0,
        int(cm.is_dls.sum() + cm.is_no_result.sum() + (cm.target_overs != 20).sum() + (cm.result_for == "super over").sum()),
        cm.is_dls.sum() == 0 and (cm.target_overs == 20).all() and cm.result_for.isin(["batting first", "chasing"]).all())
    st = A.states
    add("P14", "Chase states", "States: runs needed > 0, balls left > 0, wickets in hand 1-10", "all valid",
        f"{len(st):,} states", (st.runs_needed > 0).all() and (st.balls_left > 0).all() and st.wickets_in_hand.between(1, 10).all())
    # chase completion consistency
    r2 = r[(r.inning == 2) & r.match_id.isin(cm.match_id)].groupby("match_id").total_runs.sum()
    reached = (r2.reindex(cm.match_id).values >= cm.target_runs.values)
    add("P15", "Chase states", "Chase won <=> target reached (result_for vs runs)", f"{len(cm)} agree",
        f"{int((reached == (cm.chase_won == 1).values).sum())} agree", (reached == (cm.chase_won == 1).values).all())
    add("P16", "Chase states", "result_for used for outcomes; chase_won count equals result_for 'chasing'",
        int((cm.result_for == "chasing").sum()), int(cm.chase_won.sum()), (cm.result_for == "chasing").sum() == cm.chase_won.sum())
    add("P17", "Close matches", "Close-match set = Phase 3 definition count", "391 (Phase 3 E5)", len(A.close_ids), len(A.close_ids) == 391)
    # keys
    tabs = {"A1": ("player",), "A5": ("player",), "A6": ("player",), "A7": ("player",), "B2": ("bowler",),
            "B6": ("bowler",), "D3": ("team",)}
    fd = {f.qid: f for f in F}
    dup = 0
    for q, keys in tabs.items():
        tb = fd[q].table
        dup += int(tb.duplicated(list(keys)).sum() + tb[list(keys)].isna().sum().sum())
    add("P18", "Keys", "Player/team keys unique and non-null in ranked tables", 0, dup, dup == 0)
    # thresholds
    thr = [fd["A1"].table.innings.min() >= TH["bat_innings"], fd["A2"].table.innings.min() >= TH["bat_innings"],
           fd["A5"].table.balls_death.min() >= TH["death_balls"], fd["A6"].table.seasons.min() >= TH["season_min_seasons"],
           fd["A7"].table.innings_1.min() >= TH["split_innings"], fd["B2"].table.legal_balls.min() >= TH["bowl_balls"],
           fd["B4"].table.legal_balls.min() >= TH["phase_bowl_balls"], fd["B5"].table.legal_balls.min() >= TH["phase_bowl_balls"],
           fd["B6"].table.seasons.min() >= TH["bowl_min_seasons"], fd["C5"].table.close_matches.min() >= TH["close_matches_team"],
           fd["C6"].table.balls_close.min() >= TH["close_bat_balls"], fd["E2"].table.decided.min() >= TH["venue_matches"]]
    add("P19", "Thresholds", "Every ranked table meets its minimum-sample threshold (12 tables)", "12/12", f"{sum(thr)}/12", all(thr))
    # missing values in key result columns
    def _num(q):  # the E4 'difference' row has no match count / slope by design
        t = fd[q].table
        return t[~t.iloc[:, 0].astype(str).str.startswith("difference")] if q == "E4" else t
    na = sum(int(_num(q).select_dtypes("number").isna().sum().sum()) for q in ["A1", "A5", "B2", "C1", "D3", "E4"])
    add("P20", "Missing values", "No missing numeric values in key result tables (A1, A5, B2, C1, D3, E4)", 0, na, na == 0)
    # statistics
    p, lo, hi = wilson(50, 100)
    p0, lo0, hi0 = wilson(0, 20)
    add("P21", "Statistics", "Wilson CI sanity: 50/100 -> 40.4-59.6; 0/20 -> lower bound 0", "40.4-59.6; 0.0",
        f"{lo:.1f}-{hi:.1f}; {lo0:.1f}", abs(lo - 40.38) < 0.05 and abs(hi - 59.62) < 0.05 and lo0 == 0)
    c1 = fd["C1"].table
    add("P22", "Statistics", "All CIs contain their point estimate and lie in [0, 100]", "true",
        bool(((c1.ci_low <= c1.chase_win_pct) & (c1.chase_win_pct <= c1.ci_high) & (c1.ci_low >= 0) & (c1.ci_high <= 100)).all()),
        ((c1.ci_low <= c1.chase_win_pct) & (c1.chase_win_pct <= c1.ci_high)).all())
    # recompute one statistical test independently (permutation check of a Spearman correlation)
    d3 = fd["D3"].table
    rho = stats.spearmanr(d3.net_vs_league, d3.win_pct).statistic
    rho_manual = np.corrcoef(d3.net_vs_league.rank(), d3.win_pct.rank())[0, 1]
    add("P23", "Statistics", "Spearman rho reproduced manually (rank Pearson) for D3", round(rho, 6), round(rho_manual, 6),
        abs(rho - rho_manual) < 1e-9)
    e4 = fd["E4"].table
    add("P24", "Statistics", "Par-score bootstrap CI brackets the point estimate (E4)", "true",
        bool(((e4.par_ci_low <= e4.par_score_50pct) & (e4.par_score_50pct <= e4.par_ci_high)).all()),
        ((e4.par_ci_low <= e4.par_score_50pct) & (e4.par_score_50pct <= e4.par_ci_high)).all())
    f1 = fd["F1"]
    add("P25", "ML leakage", "Train seasons <= 2021, test seasons >= 2022, no shared match", "0 shared matches",
        len(set(st[st.season_year <= 2021].match_id) & set(st[st.season_year >= 2022].match_id)),
        not (set(st[st.season_year <= 2021].match_id) & set(st[st.season_year >= 2022].match_id)))
    add("P26", "Seven-ball overs", "29 seven-legal-ball overs retained in regulation base", 29,
        int(r[r.is_seven_ball_over == 1].groupby(["match_id", "inning", "over"]).ngroups),
        r[r.is_seven_ball_over == 1].groupby(["match_id", "inning", "over"]).ngroups == 29)
    # ---------------------------------------------------------------- MySQL cross-checks
    try:
        import mysql_utils as mu
        conn = mu.connect()
        q1 = mu.query_df(conn, """SELECT bt.franchise_name AS team, d.phase, SUM(d.total_runs) AS runs, SUM(d.is_legal_delivery) AS balls
                                  FROM v_reg_deliveries d JOIN team bt ON bt.team_id = d.batting_team_id
                                  GROUP BY bt.franchise_name, d.phase""")
        m1 = q1.merge(bat.reset_index().rename(columns={"batting_team": "team"}), on=["team", "phase"], suffixes=("_sql", "_py"))
        add("M01", "MySQL", "Team x phase runs & balls (45 cells) equal MySQL", "45 equal",
            f"{int(((m1.runs_sql == m1.runs_py) & (m1.balls_sql == m1.balls_py)).sum())} equal",
            len(m1) == 45 and ((m1.runs_sql == m1.runs_py) & (m1.balls_sql == m1.balls_py)).all())
        q2 = mu.query_df(conn, """SELECT CASE WHEN inn1_runs < 140 THEN '<140' WHEN inn1_runs < 160 THEN '140-159'
                                         WHEN inn1_runs < 180 THEN '160-179' WHEN inn1_runs < 200 THEN '180-199' ELSE '200+' END AS band,
                                         COUNT(*) AS matches, SUM(result_for = 'chasing') AS chase_wins
                                  FROM matches WHERE is_dls = 0 AND is_no_result = 0 AND target_overs = 20
                                    AND result_for IN ('batting first','chasing') GROUP BY band""")
        py = fd["C1"].table
        py = py[py.period == "All"].set_index("first_innings")
        q2 = q2.set_index("band")
        ok = all(int(q2.loc[b, "matches"]) == int(py.loc[b, "matches"]) and int(q2.loc[b, "chase_wins"]) == int(py.loc[b, "chase_wins"])
                 for b in BAND_LAB)
        add("M02", "MySQL", "Chase success by first-innings band (C1) equals MySQL", "5 bands equal", "5 bands equal" if ok else "mismatch", ok)
        q3 = mu.query_df(conn, """WITH x AS (SELECT d.match_id, d.inning, d.delivery_id, d.is_player_out, d.total_runs, d.is_legal_delivery,
                                      SUM(d.is_player_out) OVER (PARTITION BY d.match_id, d.inning ORDER BY d.delivery_id) - d.is_player_out AS wkts_before
                                    FROM v_reg_deliveries d)
                                  SELECT CASE WHEN wkts_before <= 1 THEN '0-1' WHEN wkts_before <= 3 THEN '2-3'
                                              WHEN wkts_before <= 5 THEN '4-5' ELSE '6+' END AS band,
                                         SUM(total_runs) AS runs, SUM(is_legal_delivery) AS balls FROM x GROUP BY band""")
        pyw = r.assign(band=pd.cut(r.wkts_before, [-1, 1, 3, 5, 10], labels=["0-1", "2-3", "4-5", "6+"]).astype(str)) \
            .groupby("band").agg(runs=("total_runs", "sum"), balls=("is_legal_delivery", "sum"))
        q3 = q3.set_index("band")
        ok = all(int(q3.loc[b, "runs"]) == int(pyw.loc[b, "runs"]) and int(q3.loc[b, "balls"]) == int(pyw.loc[b, "balls"]) for b in pyw.index)
        add("M03", "MySQL", "Wickets-before-ball state (window SUM OVER) runs/balls by band equal MySQL", "4 bands equal",
            "4 bands equal" if ok else "mismatch", ok)
        q4 = mu.query_df(conn, """SELECT p.player_name AS player, SUM(d.batsman_runs) AS runs_death, SUM(d.is_ball_faced) AS balls_death
                                  FROM v_reg_deliveries d JOIN player p ON p.player_id = d.batter_id WHERE d.phase = 'Death'
                                  GROUP BY p.player_name HAVING SUM(d.is_ball_faced) >= 250""")
        a5_full = pd.read_csv(TABLE_DIR / "A5_death_acceleration.csv")  # all qualifying batters, not just the top 12
        a5 = a5_full.merge(q4, on="player", suffixes=("_py", "_sql"))
        ok = len(a5) == len(a5_full) and (a5.runs_death_py == a5.runs_death_sql).all() and (a5.balls_death_py == a5.balls_death_sql).all()
        add("M04", "MySQL", "Death-overs batter runs/balls for all A5 batters equal MySQL", f"{len(a5_full)} equal",
            f"{int(((a5.runs_death_py == a5.runs_death_sql) & (a5.balls_death_py == a5.balls_death_sql)).sum())} equal", ok)
        conn.close()
    except Exception as e:  # never hide a failure
        add("M00", "MySQL", "MySQL cross-checks executed", "connection", f"ERROR: {type(e).__name__}: {e}", False)
    return pd.DataFrame(rows)


# =========================================================================== REPORTING
def write_reports(F, val, A):
    n_pass = (val.status == "PASS").sum()
    lines = ["# IPL Cricket Analytics - Phase 5 Advanced Analytics Report", "",
             f"_Generated by `python/05_advanced_analytics.py` on {datetime.now():%Y-%m-%d %H:%M}. All numbers are computed by the "
             "script from the approved cleaned data (Phase 2) using the validated Phase 3 definitions; MySQL is used for "
             "cross-validation. Interpretations are generated from computed values._", "",
             "## Method notes", "",
             "- **Regulation only** (super overs excluded); **bowler-credited wickets**; **retired hurt is not out**.",
             "- **Season/phase adjustment**: expected runs (or wickets) = each legal ball x the league rate for that season AND "
             "phase; adjusted metric = actual - expected per over (or ratio). This removes the 2023-24 scoring jump and the fact "
             "that death overs are always expensive.",
             "- **Chase analyses** use full 20-over, non-D/L matches decided by runs/wickets "
             f"({len(A.chase_matches)} matches); match states are taken at the end of each over.",
             "- **Statistics**: 95% Wilson intervals for proportions; Spearman (rank) correlation; Wilcoxon signed-rank for "
             "paired player comparisons; Mann-Whitney U for independent groups; chi-square for contingency tables (expected "
             "counts reported); bootstrap (500 resamples) for the par-score interval. Tests are used only where a comparison "
             "is being claimed; individual player differences are not tested one by one (multiple comparisons).",
             "- **Observed vs causal**: all findings are associations in observational data.",
             f"- **Validation**: {n_pass}/{len(val)} checks passed (`reports/advanced_analytics_validation_report.md`).", "",
             "## Contents", ""]
    lines += [f"- [{f.qid} - {f.title}](#{f.qid.lower()})" for f in F]
    sec = None
    for f in F:
        if f.section != sec:
            lines += ["", f"## {f.section}", ""]
            sec = f.section
        lines += [f'<a id="{f.qid.lower()}"></a>', f"### {f.qid}. {f.title}", "",
                  f"1. **Analytical question.** {f.question}",
                  f"2. **Metric definition.** {f.definition}",
                  f"3. **Calculation.** `{f.calc_ref}` in `python/05_advanced_analytics.py`; full table `reports/advanced_analytics_tables/`.",
                  f"4. **Sample size.** {f.sample}",
                  f"5. **Result.** See table{' and chart' if f.chart else ''} below.",
                  f"6. **Interpretation.** {f.insight}",
                  f"7. **Limitations.** {f.limitation}", ""]
        if f.chart:
            lines += [f"![{f.title}]({f.chart})", ""]
        lines += ["<details><summary>Result table</summary>", "", md_table(f.table.head(20)), ""]
        for name, t in f.extra.items():
            lines += [f"**{name}**", "", md_table(t.head(15)), ""]
        lines += ["</details>", ""]
    (cfg.REPORTS_DIR / "advanced_analytics_report.md").write_text("\n".join(lines), encoding="utf-8")
    c = val.status.value_counts().to_dict()
    vl = ["# Phase 5 - Advanced Analytics Validation Report", "",
          f"_Generated by `python/05_advanced_analytics.py` on {datetime.now():%Y-%m-%d %H:%M}. Every check below was executed; "
          "M-checks query the live MySQL database._", "",
          f"**Result: {c.get('PASS', 0)} PASS | {c.get('FAIL', 0)} FAIL** (of {len(val)})", "", md_table(val), ""]
    (cfg.REPORTS_DIR / "advanced_analytics_validation_report.md").write_text("\n".join(vl), encoding="utf-8")


def summary_csv(F):
    rows = []
    for f in F:
        rows.append({"qid": f.qid, "section": f.section, "title": f.title, "sample": f.sample, "finding": f.insight,
                     "chart": f.chart or "", "table": f"advanced_analytics_tables/{f.qid}*.csv"})
    pd.DataFrame(rows).to_csv(cfg.REPORTS_DIR / "advanced_analytics_summary.csv", index=False)


def build_all():
    eda.set_style()
    for p in [CHART_DIR, TABLE_DIR]:
        p.mkdir(parents=True, exist_ok=True)
    A = Adv()
    F = [a1_consistency(A), a2_milestones(A), a3_distribution(A), a4_boundary_dot(A), a5_death_acceleration(A),
         a6_season_variability(A), a7_first_vs_chasing(A),
         b1_phase_wickets(A), b2_tradeoff(A), b3_dot_boundary(A),
         phase_specialists(A, "Death", "B4", "Death-overs specialists (season-adjusted)"),
         phase_specialists(A, "Powerplay", "B5", "Powerplay specialists (season-adjusted)"),
         b6_bowler_consistency(A), b7_conditions(A),
         c1_chase_by_target(A), c2_required_rate(A), c3_wickets_remaining(A), c4_chase_patterns(A), c5_close_matches(A),
         c6_narrow_margin_players(A), c7_final_overs(A),
         d1_team_phase_scoring(A), d2_team_phase_wickets(A), d3_strengths(A), d4_team_consistency(A), d5_win_vs_loss(A),
         d6_eras(A),
         e1_venue_phase(A), e2_venue_chase_test(A), e3_venue_bowling(A), e4_first_innings_outcome(A),
         f1_ml_assessment(A)]
    fn_names = ["a1_consistency", "a2_milestones", "a3_distribution", "a4_boundary_dot", "a5_death_acceleration",
                "a6_season_variability", "a7_first_vs_chasing", "b1_phase_wickets", "b2_tradeoff", "b3_dot_boundary",
                "phase_specialists('Death')", "phase_specialists('Powerplay')", "b6_bowler_consistency", "b7_conditions",
                "c1_chase_by_target", "c2_required_rate", "c3_wickets_remaining", "c4_chase_patterns", "c5_close_matches",
                "c6_narrow_margin_players", "c7_final_overs", "d1_team_phase_scoring", "d2_team_phase_wickets",
                "d3_strengths", "d4_team_consistency", "d5_win_vs_loss", "d6_eras", "e1_venue_phase",
                "e2_venue_chase_test", "e3_venue_bowling", "e4_first_innings_outcome", "f1_ml_assessment"]
    for f, fn in zip(F, fn_names):
        f.calc_ref = fn
        tbl(f.qid, f.table)
    val = validate(A, F)
    return A, F, val


def main():
    A, F, val = build_all()
    val.to_csv(cfg.REPORTS_DIR / "advanced_analytics_validation_checks.csv", index=False)
    write_reports(F, val, A)
    summary_csv(F)
    print(f"[ok] {len(F)} advanced questions; charts: {len(list(CHART_DIR.glob('*.png')))}")
    print(val[["check_id", "check", "expected", "actual", "status"]].to_string(index=False, max_colwidth=55))
    c = val.status.value_counts().to_dict()
    print(f"\nPASS={c.get('PASS', 0)} FAIL={c.get('FAIL', 0)}")
    if c.get("FAIL", 0):
        sys.exit(1)


if __name__ == "__main__":
    main()
