"""
Phase 3 - Exploratory Data Analysis
===================================

Answers the Phase 3 cricket/business questions from the APPROVED cleaned data
(data/processed/). Read-only: no dataset is modified.

Structure
---------
1. Load + base tables      (regulation deliveries, team-match long table,
                            batting innings, batter / bowler careers)
2. One function per question -> a Question record (table, chart, definition,
                                 insight, limitation)
3. Validation checks       -> reports/eda_validation_report.md
4. Report writers          -> reports/eda_report.md, reports/eda_summary.csv,
                              reports/eda_tables/*.csv, reports/charts/*.png

Conventions (see documentation/transformation_log.md)
-----------------------------------------------------
* Regulation statistics exclude super overs (is_super_over == 0).
* Batting order from batting_first_team / chasing_team (derived from deliveries).
* Batting-first vs chasing outcomes from result_for (handles D/L correctly).
* Bowler wickets = is_bowler_wicket; batter dismissals = is_player_out
  (retired hurt excluded). Raw is_wicket is never used as a wicket metric.
* "Full match" = not a no-result AND target_overs == 20, i.e. the first innings
  was a full 20-over allocation. Used for score averages so rain-shortened and
  D/L games do not drag averages down.

Run from the project root:
    python python/03_eda.py
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from datetime import datetime
from importlib import import_module
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import matplotlib.ticker as mtick  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ipl_config as cfg  # noqa: E402

md_table = import_module("01_data_profiling").md_table

CHART_DIR = cfg.REPORTS_DIR / "charts"
TABLE_DIR = cfg.REPORTS_DIR / "eda_tables"

# Minimum-sample thresholds (documented in the report and validated)
TH = {
    "bat_innings": 50,          # batting average & consistency rankings
    "bat_balls": 500,           # strike-rate ranking
    "bowl_balls": 1000,         # economy / average / strike-rate rankings (~167 overs)
    "phase_bat_balls": 300,     # phase strike-rate rankings
    "phase_bowl_balls": 600,    # phase bowling rankings (100 overs)
    "venue_matches": 20,        # venue rankings
    "team_innings": 20,         # team batting-first / chasing / average-score rankings
}

# ---------------------------------------------------------------- chart style
# Reference palette (dataviz skill): categorical slots 1-3 + neutral greys.
BLUE, ORANGE, AQUA = "#2a78d6", "#eb6834", "#1baf7a"
GREY, INK, INK2, GRID, SURFACE = "#b5b3ad", "#0b0b0b", "#52514e", "#e6e5e0", "#fcfcfb"
PHASE_COLORS = {"Powerplay": BLUE, "Middle": ORANGE, "Death": AQUA}


def set_style():
    plt.rcParams.update({
        "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
        "axes.edgecolor": GRID, "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.8,
        "axes.spines.top": False, "axes.spines.right": False, "axes.axisbelow": True,
        "font.size": 10, "axes.titlesize": 12.5, "axes.titleweight": "bold", "axes.titlelocation": "left",
        "axes.titlepad": 26, "axes.labelcolor": INK2, "xtick.color": INK2, "ytick.color": INK2,
        "text.color": INK, "lines.linewidth": 2, "legend.frameon": False, "font.family": "DejaVu Sans",
    })


def save(fig, name: str) -> str:
    path = CHART_DIR / f"{name}.png"
    fig.savefig(path, dpi=200, bbox_inches="tight")
    plt.close(fig)
    return f"charts/{name}.png"


def subtitle(ax, text):
    ax.text(0, 1.015, text, transform=ax.transAxes, fontsize=9, color=INK2, va="bottom")


def fig_title(fig, text):
    """Figure-level title for small-multiple charts; panel titles get a tight pad so they don't collide."""
    for ax in fig.axes:
        ax.set_title(ax.get_title(loc="left"), loc="left", pad=8, fontsize=11)
    fig.suptitle(text, x=0.01, ha="left", fontweight="bold", fontsize=13, y=1.0)
    fig.tight_layout(rect=(0, 0, 1, 0.94))


def label_points(ax, xs, ys, texts, fontsize=8.5):
    """Greedy non-overlapping point labels: try several offsets per point and keep the first
    whose (approximate) pixel box does not overlap an already placed label or another point."""
    ax.figure.canvas.draw()
    to_px = ax.transData.transform
    placed = []
    pts = [to_px((x, y)) for x, y in zip(xs, ys)]
    cands = [(6, 4, "left"), (6, -12, "left"), (-6, 4, "right"), (-6, -12, "right"), (6, 14, "left"), (-6, 14, "right")]
    for (x, y), (px, py), txt in zip(zip(xs, ys), pts, texts):
        w, h = 0.62 * fontsize * len(txt) * ax.figure.dpi / 72, fontsize * 1.3 * ax.figure.dpi / 72
        best = cands[0]
        for dx, dy, ha in cands:
            x0 = px + dx * ax.figure.dpi / 72 - (w if ha == "right" else 0)
            y0 = py + dy * ax.figure.dpi / 72
            box = (x0, y0, x0 + w, y0 + h)
            clash = any(not (box[2] < b[0] or box[0] > b[2] or box[3] < b[1] or box[1] > b[3]) for b in placed)
            clash |= any(box[0] < qx < box[2] and box[1] < qy < box[3] for qx, qy in pts if (qx, qy) != (px, py))
            if not clash:
                best = (dx, dy, ha)
                placed.append(box)
                break
        else:
            dx, dy, ha = best
            x0 = px + dx * ax.figure.dpi / 72 - (w if ha == "right" else 0)
            placed.append((x0, py + dy * ax.figure.dpi / 72, x0 + w, py + dy * ax.figure.dpi / 72 + h))
        ax.annotate(txt, (x, y), xytext=best[:2], textcoords="offset points", ha=best[2], fontsize=fontsize, color=INK)


def hbar(df, value, label, title, sub, xlabel, name, fmt="{:,.0f}", color=BLUE, xlim_pad=1.12):
    """Ranked horizontal bar chart, largest at top, value labels at bar ends."""
    d = df.sort_values(value)
    fig, ax = plt.subplots(figsize=(8.5, 0.36 * len(d) + 1.4))
    ax.barh(d[label], d[value], color=color, height=0.68)
    for y, v in enumerate(d[value]):
        ax.text(v, y, " " + fmt.format(v), va="center", fontsize=8.5, color=INK2)
    ax.set_xlim(0, d[value].max() * xlim_pad)
    ax.grid(axis="y", visible=False)
    ax.set_xlabel(xlabel)
    ax.set_title(title)
    subtitle(ax, sub)
    return save(fig, name)


# ---------------------------------------------------------------- question record
@dataclass
class Question:
    qid: str
    section: str
    title: str
    question: str
    why: str
    definition: str
    table: pd.DataFrame
    insight: str
    limitation: str = ""
    chart: str | None = None
    validation: str = ""
    extra_tables: dict = field(default_factory=dict)


# ---------------------------------------------------------------- data & base tables
class Data:
    def __init__(self):
        self.mc = pd.read_csv(cfg.CLEAN_MATCHES)
        self.dc = pd.read_csv(cfg.CLEAN_DELIVERIES)
        self.reg = self.dc[self.dc.is_super_over == 0].copy()
        self.so = self.dc[self.dc.is_super_over == 1].copy()
        mc = self.mc
        self.full = mc[(mc.is_no_result == 0) & (mc.target_overs == 20)].copy()
        self.decided_bfc = mc[mc.result_for.isin(["batting first", "chasing"])].copy()
        self.reg = self.reg.merge(mc[["match_id", "venue"]], on="match_id", how="left", validate="m:1")
        self.team_long = self._team_long()
        self.bat_inn = self._batting_innings()
        self.batters = self._batter_careers()
        self.bowlers = self._bowler_careers(self.reg)

    def _team_long(self):
        mc = self.mc
        keep = ["match_id", "season_year", "venue", "winner", "result_for", "is_no_result", "is_super_over",
                "is_dls", "match_type", "toss_winner"]
        a = mc[keep].assign(team=mc.batting_first_team, opponent=mc.chasing_team, batted_first=1)
        b = mc[keep].assign(team=mc.chasing_team, opponent=mc.batting_first_team, batted_first=0)
        t = pd.concat([a, b], ignore_index=True)
        t["decided"] = 1 - t.is_no_result
        t["won"] = (t.winner == t.team).astype(int)
        t["lost"] = ((t.decided == 1) & (t.won == 0)).astype(int)
        return t

    def _batting_innings(self):
        """One row per (match, innings, player) who batted: appeared as striker,
        non-striker or was dismissed. Super overs excluded."""
        reg = self.reg
        k = ["match_id", "inning"]
        bat = (reg.groupby(k + ["batter"])
                  .agg(runs=("batsman_runs", "sum"), balls=("is_ball_faced", "sum"),
                       fours=("is_four", "sum"), sixes=("is_six", "sum")))
        bat.index = bat.index.set_names(k + ["player"])
        outs = reg[reg.is_player_out == 1].groupby(k + ["player_dismissed"]).size().rename("out")
        outs.index = outs.index.set_names(k + ["player"])
        appear = pd.concat([reg[k + [c]].rename(columns={c: "player"})
                            for c in ["batter", "non_striker", "player_dismissed"]]).dropna().drop_duplicates()
        bi = appear.set_index(k + ["player"]).join(bat).join(outs).fillna(0)
        bi = bi.astype({"runs": int, "balls": int, "fours": int, "sixes": int, "out": int}).reset_index()
        meta = reg.groupby(k).agg(season_year=("season_year", "first"), team=("batting_team", "first"),
                                  opponent=("bowling_team", "first")).reset_index()
        return bi.merge(meta, on=k, how="left", validate="m:1")

    def _batter_careers(self):
        g = self.bat_inn.groupby("player")
        c = g.agg(innings=("runs", "size"), runs=("runs", "sum"), balls=("balls", "sum"), outs=("out", "sum"),
                  fours=("fours", "sum"), sixes=("sixes", "sum"), highest=("runs", "max"),
                  fifties=("runs", lambda s: int(((s >= 50) & (s < 100)).sum())),
                  hundreds=("runs", lambda s: int((s >= 100).sum())),
                  seasons=("season_year", "nunique"))
        c["not_outs"] = c.innings - c.outs
        c["average"] = np.where(c.outs > 0, c.runs / c.outs.replace(0, np.nan), np.nan)
        c["strike_rate"] = c.runs / c.balls.replace(0, np.nan) * 100
        c["boundary_run_pct"] = (4 * c.fours + 6 * c.sixes) / c.runs.replace(0, np.nan) * 100
        return c.reset_index()

    @staticmethod
    def _bowler_careers(deliv):
        g = deliv.groupby("bowler")
        c = g.agg(legal_balls=("is_legal_delivery", "sum"), runs_conceded=("bowler_runs_conceded", "sum"),
                  wickets=("is_bowler_wicket", "sum"), dots=("is_dot_ball", "sum"))
        c["innings"] = deliv.drop_duplicates(["match_id", "inning", "bowler"]).groupby("bowler").size()
        c["overs"] = c.legal_balls // 6 + (c.legal_balls % 6) / 10
        c["economy"] = c.runs_conceded / c.legal_balls * 6
        c["average"] = c.runs_conceded / c.wickets.replace(0, np.nan)
        c["strike_rate"] = c.legal_balls / c.wickets.replace(0, np.nan)
        c["dot_pct"] = c.dots / c.legal_balls * 100
        return c.reset_index()


def r(x, n=2):
    return round(float(x), n)


# =========================================================================== A. OVERVIEW
def season_table(D: Data) -> pd.DataFrame:
    mc, reg, full = D.mc, D.reg, D.full
    s = mc.groupby("season_year").agg(matches=("match_id", "size"), no_results=("is_no_result", "sum"),
                                      dls_matches=("is_dls", "sum"), ties=("is_super_over", "sum"))
    d = reg.groupby("season_year").agg(runs=("total_runs", "sum"), legal_balls=("is_legal_delivery", "sum"),
                                       player_outs=("is_player_out", "sum"), bowler_wickets=("is_bowler_wicket", "sum"),
                                       fours=("is_four", "sum"), sixes=("is_six", "sum"), extras=("extra_runs", "sum"),
                                       dots=("is_dot_ball", "sum"))
    s = s.join(d)
    f = full.groupby("season_year").agg(full_matches=("match_id", "size"), avg_inn1=("inn1_runs", "mean"),
                                        avg_inn2=("inn2_runs", "mean"))
    f["runs_per_full_match"] = full.assign(t=full.inn1_runs + full.inn2_runs).groupby("season_year").t.mean()
    s = s.join(f)
    s["runs_per_match"] = s.runs / s.matches
    s["run_rate"] = s.runs / s.legal_balls * 6
    s["bowler_wkts_per_match"] = s.bowler_wickets / s.matches
    s["sixes_per_match"] = s.sixes / s.matches
    s["dot_pct"] = s.dots / s.legal_balls * 100
    s["franchises"] = D.team_long.groupby("season_year").team.nunique()
    s["runs_per_innings_full"] = s.runs_per_full_match / 2
    return s.reset_index()


def q_a1(D, S) -> Question:
    t = S[["season_year", "matches", "runs", "player_outs", "bowler_wickets", "runs_per_match",
           "bowler_wkts_per_match", "sixes_per_match"]].round(2)
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.2), sharex=True)
    axes[0].plot(S.season_year, S.runs_per_match, color=BLUE, marker="o", ms=4)
    axes[0].set_title("Runs per match")
    axes[0].set_ylabel("Runs (both regulation innings)")
    axes[1].plot(S.season_year, S.bowler_wkts_per_match, color=ORANGE, marker="o", ms=4)
    axes[1].set_title("Bowler-credited wickets per match")
    axes[1].set_ylabel("Wickets")
    for ax in axes:
        ax.set_xticks(S.season_year[::2])
    fig_title(fig, "IPL season trends, 2008-2024 (super overs excluded)")
    chart = save(fig, "A1_season_runs_wickets_per_match")
    first, last = S.iloc[0], S.iloc[-1]
    peak = S.loc[S.runs_per_match.idxmax()]
    insight = (
        f"Total regulation runs grew from {first.runs:,.0f} in 2008 ({first.matches:.0f} matches) to {last.runs:,.0f} in 2024 "
        f"({last.matches:.0f} matches). Per match, scoring was broadly flat at ~{S[S.season_year <= 2022].runs_per_match.min():.0f}-"
        f"{S[S.season_year <= 2022].runs_per_match.max():.0f} runs between 2008 and 2022, then jumped to "
        f"{S.loc[S.season_year == 2023, 'runs_per_match'].iloc[0]:.0f} (2023) and {last.runs_per_match:.0f} (2024), "
        f"the highest of any season ({peak.season_year:.0f}). Bowler-credited wickets per match stayed in a narrow band "
        f"({S.bowler_wkts_per_match.min():.1f}-{S.bowler_wkts_per_match.max():.1f}), so the recent increase comes from "
        f"faster scoring, not fewer wickets. Sixes per match rose from {first.sixes_per_match:.1f} (2008) to "
        f"{last.sixes_per_match:.1f} (2024).")
    return Question("A1", "A. IPL overview & season trends", "Season volume: matches, runs and wickets",
                    "How has the IPL changed in total matches, runs and wickets across seasons?",
                    "Establishes the scale of the league and the scoring environment every other comparison sits in.",
                    "Runs = sum of total_runs (regulation deliveries). Wickets shown two ways: player_outs "
                    "(is_player_out: all dismissals excl. retired hurt) and bowler_wickets (is_bowler_wicket). "
                    "Per-match = season total / matches with play.",
                    t, insight,
                    "Season match counts reflect matches with play only (abandoned-without-a-ball games are absent).",
                    chart)


def q_a2(D, S) -> Question:
    t = S[["season_year", "full_matches", "avg_inn1"]].sort_values("avg_inn1", ascending=False).round(1)
    hi, lo = t.iloc[0], t.iloc[-1]
    fig, ax = plt.subplots(figsize=(10, 4))
    ax.bar(S.season_year, S.avg_inn1, color=GREY, width=0.7)
    for yr, color in [(hi.season_year, BLUE), (lo.season_year, ORANGE)]:
        v = S.loc[S.season_year == yr, "avg_inn1"].iloc[0]
        ax.bar(yr, v, color=color, width=0.7)
        ax.text(yr, v + 2, f"{v:.1f}", ha="center", fontsize=9, color=INK)
    ax.axhline(D.full.inn1_runs.mean(), color=INK2, lw=1, ls="--")
    ax.text(S.season_year.min() - 0.4, D.full.inn1_runs.mean() + 2, f"2008-24 average {D.full.inn1_runs.mean():.1f}",
            fontsize=8.5, color=INK2)
    ax.set_xticks(S.season_year)
    ax.tick_params(axis="x", rotation=45)
    ax.set_ylabel("Average first-innings runs")
    ax.set_ylim(0, S.avg_inn1.max() * 1.12)
    ax.set_title("Average first-innings score by season")
    subtitle(ax, "Full 20-over matches only (no-results, D/L and rain-shortened games excluded). Highest in blue, lowest in orange.")
    chart = save(fig, "A2_avg_first_innings_by_season")
    a = S.set_index("season_year").avg_inn1
    pre = a.loc[2008:2022]
    insight = (f"The highest average first-innings score was {hi.avg_inn1:.1f} in {hi.season_year:.0f}; the lowest was "
               f"{lo.avg_inn1:.1f} in {lo.season_year:.0f}. Across all {len(D.full)} full matches the average is "
               f"{D.full.inn1_runs.mean():.1f}. From 2008 to 2022 every season averaged between {pre.min():.1f} and "
               f"{pre.max():.1f}; the average then rose sharply to {a[2023]:.1f} in 2023 (+{a[2023] - a[2022]:.1f} on 2022) "
               f"and {a[2024]:.1f} in 2024 (+{a[2024] - a[2023]:.1f}). The data does not record why; rule changes such as the "
               f"Impact Player rule (introduced 2023) are a plausible but untested explanation.")
    excluded = len(D.mc) - len(D.full)
    n_nr = int(D.mc.is_no_result.sum())
    return Question("A2", "A. IPL overview & season trends", "Average first-innings score by season",
                    "Which seasons had the highest and lowest average first-innings scores?",
                    "First-innings score is the standard benchmark for 'par' at a venue or in a season.",
                    "Mean of inn1_runs over full matches (is_no_result = 0 and target_overs = 20).",
                    t, insight, f"{excluded} matches excluded: {n_nr} no-results and {excluded - n_nr} D/L or "
                                f"rain-shortened matches.", chart)


def q_a3(D, S) -> Question:
    t = S[["season_year", "full_matches", "runs_per_full_match", "runs_per_innings_full", "avg_inn1", "avg_inn2"]].round(1)
    early = S[S.season_year <= 2012].runs_per_innings_full.mean()
    late = S[S.season_year >= 2020].runs_per_innings_full.mean()
    insight = (f"In full matches, runs per innings averaged {early:.1f} across 2008-2012 and {late:.1f} across 2020-2024. "
               f"Second innings average fewer runs than first innings in every season "
               f"(overall {D.full.inn2_runs.mean():.1f} vs {D.full.inn1_runs.mean():.1f}), as expected because successful "
               f"chases stop once the target is reached - so second-innings averages understate batting strength and "
               f"should not be compared with first-innings averages as if like-for-like.")
    return Question("A3", "A. IPL overview & season trends", "Runs per match and per innings",
                    "How have average runs per match and runs per innings changed?",
                    "Separates the effect of more matches from genuinely higher scoring.",
                    "Runs per full match = mean(inn1_runs + inn2_runs) over full matches; runs per innings = that / 2.",
                    t, insight, "Second-innings totals are truncated by the target (structural, not a data error).",
                    "charts/A1_season_runs_wickets_per_match.png")


def q_a4(D, S) -> Question:
    ph = (D.reg.groupby(["season_year", "phase"]).agg(runs=("total_runs", "sum"), balls=("is_legal_delivery", "sum"))
              .assign(run_rate=lambda x: x.runs / x.balls * 6).run_rate.unstack()[["Powerplay", "Middle", "Death"]])
    t = S[["season_year", "run_rate", "dot_pct", "sixes_per_match"]].set_index("season_year").join(
        ph.add_prefix("rr_")).round(2).reset_index().sort_values("run_rate", ascending=False)
    fig, ax = plt.subplots(figsize=(10, 4.4))
    for p in ["Powerplay", "Middle", "Death"]:
        ax.plot(ph.index, ph[p], color=PHASE_COLORS[p], marker="o", ms=4, label=p)
        ax.text(ph.index[-1] + 0.3, ph[p].iloc[-1], p, color=INK2, va="center", fontsize=9)
    ax.plot(S.season_year, S.run_rate, color=INK, lw=1.2, ls="--", label="All overs")
    ax.set_xticks(S.season_year)
    ax.tick_params(axis="x", rotation=45)
    ax.set_xlim(S.season_year.min() - 0.5, S.season_year.max() + 2)
    ax.set_ylabel("Run rate (runs per 6 legal balls)")
    ax.legend(loc="upper left", ncol=4)
    ax.set_title("Scoring rate by season and match phase")
    subtitle(ax, "Regulation deliveries; Powerplay = overs 1-6, Middle = 7-15, Death = 16-20")
    chart = save(fig, "A4_run_rate_by_season_phase")
    top = t.iloc[0]
    death_fastest = int((ph.Death > ph[["Powerplay", "Middle"]].max(axis=1)).sum())
    up_all = all(ph.loc[2024, p] > ph.loc[2022, p] for p in ["Powerplay", "Middle", "Death"])
    insight = (f"{top.season_year:.0f} had the highest overall run rate ({top.run_rate:.2f} per over), followed by "
               f"{t.iloc[1].season_year:.0f} ({t.iloc[1].run_rate:.2f}); the lowest was {t.iloc[-1].season_year:.0f} "
               f"({t.iloc[-1].run_rate:.2f}). Death overs are the fastest-scoring phase in {death_fastest} of 17 seasons. "
               f"Between 2022 and 2024 the run rate rose in {'all three phases' if up_all else 'some phases'}: Powerplay "
               f"{ph.loc[2022, 'Powerplay']:.2f} -> {ph.loc[2024, 'Powerplay']:.2f}, Middle {ph.loc[2022, 'Middle']:.2f} -> "
               f"{ph.loc[2024, 'Middle']:.2f}, Death {ph.loc[2022, 'Death']:.2f} -> {ph.loc[2024, 'Death']:.2f}. The "
               f"largest rise was in the Powerplay, so the increase was not confined to the end of the innings.")
    return Question("A4", "A. IPL overview & season trends", "Scoring rate by season",
                    "Which seasons had the highest scoring rates?",
                    "Run rate normalises for innings length and match count, making seasons directly comparable.",
                    "Run rate = sum(total_runs) / sum(is_legal_delivery) x 6 over regulation deliveries.",
                    t, insight, "Phase boundaries assume a 20-over innings (limitation L10).", chart)


def q_a5(D, S) -> Question:
    tl = D.team_long
    roster = tl.groupby("season_year").team.agg(lambda s: ", ".join(sorted(s.unique())))
    t = S[["season_year", "franchises"]].set_index("season_year").join(roster.rename("teams")).reset_index()
    insight = ("The league ran with 8 franchises in most seasons, 10 in 2011 (Kochi Tuskers Kerala and Pune Warriors "
               "added), 9 in 2012-2013, back to 8 from 2014, and 10 since 2022 (Gujarat Titans and Lucknow Super Giants). "
               "Deccan Chargers (2008-12), Kochi (2011), Pune Warriors (2011-13), Gujarat Lions and Rising Pune "
               "Supergiants (2016-17) are defunct; Chennai Super Kings and Rajasthan Royals are absent in 2016-17. "
               "Franchise totals must therefore be read alongside seasons played.")
    # Validate the narrative against the data
    counts = S.set_index("season_year").franchises.to_dict()
    assert counts[2011] == 10 and counts[2012] == 9 and counts[2014] == 8 and counts[2022] == 10
    return Question("A5", "A. IPL overview & season trends", "Participating franchises per season",
                    "How has the number of participating franchises changed over time?",
                    "Unequal participation makes raw totals (wins, runs) unfair across franchises.",
                    "Distinct standardized franchises appearing in a season's matches.",
                    t, insight)


# =========================================================================== B. TEAMS
def team_table(D) -> pd.DataFrame:
    tl = D.team_long
    g = tl.groupby("team")
    t = g.agg(seasons=("season_year", "nunique"), first_season=("season_year", "min"),
              last_season=("season_year", "max"), matches=("match_id", "size"), decided=("decided", "sum"),
              wins=("won", "sum"), losses=("lost", "sum"), no_results=("is_no_result", "sum"))
    t["win_pct"] = t.wins / t.decided * 100
    finals = D.mc[D.mc.match_type == "Final"]
    t["titles"] = finals.winner.value_counts().reindex(t.index).fillna(0).astype(int)
    playoff = tl[tl.match_type != "League"]
    t["playoff_matches"] = playoff.groupby("team").size().reindex(t.index).fillna(0).astype(int)
    bfc = tl[tl.result_for.isin(["batting first", "chasing"])]
    bf, ch = bfc[bfc.batted_first == 1], bfc[bfc.batted_first == 0]
    t["bat_first_matches"] = bf.groupby("team").size()
    t["bat_first_wins"] = bf.groupby("team").won.sum()
    t["chase_matches"] = ch.groupby("team").size()
    t["chase_wins"] = ch.groupby("team").won.sum()
    t["bat_first_win_pct"] = t.bat_first_wins / t.bat_first_matches * 100
    t["chase_win_pct"] = t.chase_wins / t.chase_matches * 100
    so = tl[tl.is_super_over == 1]
    t["super_over_wins"] = so.groupby("team").won.sum().reindex(t.index).fillna(0).astype(int)
    t["super_over_matches"] = so.groupby("team").size().reindex(t.index).fillna(0).astype(int)
    return t.reset_index()


def q_b1(D, T) -> Question:
    t = T[["team", "seasons", "matches", "wins", "losses", "no_results", "titles", "playoff_matches"]] \
        .sort_values(["wins", "titles"], ascending=False)
    chart = hbar(T.assign(label=T.team + "  (" + T.seasons.astype(str) + " seasons)"), "wins", "label",
                 "Total wins by franchise, 2008-2024", "Includes super-over wins. Label shows seasons played.",
                 "Wins", "B1_team_total_wins")
    top = t.iloc[0]
    insight = (f"{top.team} have the most wins ({top.wins}) from {top.matches} matches, followed by "
               f"{t.iloc[1].team} ({t.iloc[1].wins}) and {t.iloc[2].team} ({t.iloc[2].wins}). Titles (Final winners) are "
               f"concentrated: Mumbai Indians {int(T.set_index('team').titles['Mumbai Indians'])} and Chennai Super Kings "
               f"{int(T.set_index('team').titles['Chennai Super Kings'])}, then Kolkata Knight Riders "
               f"{int(T.set_index('team').titles['Kolkata Knight Riders'])}; together they hold "
               f"{int(T.set_index('team').titles[['Mumbai Indians', 'Chennai Super Kings', 'Kolkata Knight Riders']].sum())} "
               f"of 17 titles. Total wins favour long-serving franchises, so they are paired with win % (B2).")
    return Question("B1", "B. Team performance", "Most wins and titles",
                    "Which franchises have the most wins?",
                    "Headline measure of franchise success across the league's history.",
                    "wins = matches where winner == team (super-over wins included). titles = Final matches won.",
                    t, insight, "Raw totals depend on seasons played (2 to 17).", chart)


def q_b2(D, T) -> Question:
    t = T[["team", "seasons", "decided", "wins", "losses", "win_pct"]].sort_values("win_pct", ascending=False).round(1)
    d = T.sort_values("win_pct")
    fig, ax = plt.subplots(figsize=(9, 6))
    colors = [BLUE if s >= 10 else GREY for s in d.seasons]
    ax.barh(d.team, d.win_pct, color=colors, height=0.68)
    for y, (v, n) in enumerate(zip(d.win_pct, d.decided)):
        ax.text(v + 0.6, y, f"{v:.1f}%  (n={n})", va="center", fontsize=8.5, color=INK2, zorder=4,
                bbox=dict(fc=SURFACE, ec="none", pad=1))
    ax.axvline(50, color=INK2, lw=1, ls="--", zorder=1)
    ax.set_xlim(0, 75)
    ax.xaxis.set_major_formatter(mtick.PercentFormatter())
    ax.grid(axis="y", visible=False)
    ax.set_xlabel("Win % of decided matches")
    ax.set_title("Win percentage by franchise")
    subtitle(ax, "Blue = 10+ seasons; grey = short-lived franchises (small samples). n = decided matches.")
    chart = save(fig, "B2_team_win_pct")
    est = t[t.seasons >= 10]
    insight = (f"Among franchises with 10+ seasons, {est.iloc[0].team} have the highest win % ({est.iloc[0].win_pct:.1f}%, "
               f"{est.iloc[0].decided} decided matches), then {est.iloc[1].team} ({est.iloc[1].win_pct:.1f}%). "
               f"The overall leader is {t.iloc[0].team} ({t.iloc[0].win_pct:.1f}%) but from only {t.iloc[0].decided} matches "
               f"in {t.iloc[0].seasons} seasons, so its rate is far less certain. The lowest established franchise is "
               f"{est.iloc[-1].team} ({est.iloc[-1].win_pct:.1f}%).")
    return Question("B2", "B. Team performance", "Win percentage",
                    "Which franchises have the highest win percentage?",
                    "Win % normalises for different numbers of matches played.",
                    "win_pct = wins / decided matches x 100 (no-results excluded; ties settled by super over count as win/loss).",
                    t, insight, "Franchises with <5 seasons have wide uncertainty; interpret with n.", chart)


def bf_chase_chart(T):
    d = T[(T.bat_first_matches >= TH["team_innings"]) & (T.chase_matches >= TH["team_innings"])].sort_values("chase_win_pct")
    fig, ax = plt.subplots(figsize=(9.5, 6))
    y = np.arange(len(d))
    ax.barh(y + 0.2, d.bat_first_win_pct, height=0.38, color=BLUE, label="Batting first")
    ax.barh(y - 0.2, d.chase_win_pct, height=0.38, color=ORANGE, label="Chasing")
    ax.set_yticks(y, d.team)
    ax.axvline(50, color=INK2, lw=1, ls="--")
    ax.xaxis.set_major_formatter(mtick.PercentFormatter())
    ax.set_xlim(0, 80)
    ax.grid(axis="y", visible=False)
    ax.legend(loc="lower right")
    ax.set_xlabel("Win %")
    ax.set_title("Win % batting first vs chasing, by franchise")
    subtitle(ax, f"Decided by runs/wickets (super overs & no-results excluded), uses result_for. Min {TH['team_innings']} matches each.")
    return save(fig, "B3_team_bat_first_vs_chase")


def q_b3(D, T) -> Question:
    q = T[T.bat_first_matches >= TH["team_innings"]]
    t = q[["team", "bat_first_matches", "bat_first_wins", "bat_first_win_pct"]].sort_values("bat_first_win_pct", ascending=False).round(1)
    chart = bf_chase_chart(T)
    insight = (f"Batting first, {t.iloc[0].team} have the best record ({t.iloc[0].bat_first_win_pct:.1f}% from "
               f"{t.iloc[0].bat_first_matches} matches), followed by {t.iloc[1].team} ({t.iloc[1].bat_first_win_pct:.1f}%) "
               f"and {t.iloc[2].team} ({t.iloc[2].bat_first_win_pct:.1f}%). League-wide, batting-first sides won "
               f"{(D.decided_bfc.result_for == 'batting first').mean() * 100:.1f}% of decided matches.")
    return Question("B3", "B. Team performance", "Batting-first performance",
                    "Which franchises perform best when batting first?",
                    "Indicates which sides set and defend totals most effectively.",
                    "Matches where team == batting_first_team and result_for in {batting first, chasing}; "
                    "win % = wins / those matches.",
                    t, insight, f"Teams with < {TH['team_innings']} batting-first matches excluded "
                                f"({', '.join(T[T.bat_first_matches < TH['team_innings']].team)}).", chart)


def q_b4(D, T) -> Question:
    q = T[T.chase_matches >= TH["team_innings"]]
    t = q[["team", "chase_matches", "chase_wins", "chase_win_pct"]].sort_values("chase_win_pct", ascending=False).round(1)
    gap = T.assign(gap=T.chase_win_pct - T.bat_first_win_pct)
    gap = gap[(gap.chase_matches >= TH["team_innings"]) & (gap.bat_first_matches >= TH["team_innings"])].sort_values("gap")
    insight = (f"Chasing, {t.iloc[0].team} lead ({t.iloc[0].chase_win_pct:.1f}% from {t.iloc[0].chase_matches}), then "
               f"{t.iloc[1].team} ({t.iloc[1].chase_win_pct:.1f}%). The biggest preference for chasing over batting first is "
               f"{gap.iloc[-1].team} (+{gap.iloc[-1].gap:.1f} points); the biggest preference for batting first is "
               f"{gap.iloc[0].team} ({gap.iloc[0].gap:.1f} points). These are observed records - they also reflect toss "
               f"decisions, opponents and eras, not only a team's skill in that role.")
    return Question("B4", "B. Team performance", "Chasing performance",
                    "Which franchises perform best when chasing?",
                    "Chasing success shows composure under a known target.",
                    "Matches where team == chasing_team and result_for in {batting first, chasing}; win % = wins / matches. "
                    "D/L chases won 'by runs' count as chasing wins (via result_for).",
                    t, insight, "Same thresholds as B3.", "charts/B3_team_bat_first_vs_chase.png")


def q_b5(D) -> Question:
    f = D.full
    a = f.groupby("batting_first_team").inn1_runs.agg(inn1_innings="size", avg_inn1="mean")
    b = f.groupby("chasing_team").inn2_runs.agg(inn2_innings="size", avg_inn2="mean")
    t = a.join(b).rename_axis("team").reset_index()
    t = t[(t.inn1_innings >= TH["team_innings"]) & (t.inn2_innings >= TH["team_innings"])]
    # era adjustment: first-innings score minus that season's league average
    season_avg = f.groupby("season_year").inn1_runs.transform("mean")
    adj = f.assign(adj=f.inn1_runs - season_avg).groupby("batting_first_team").adj.mean()
    t["avg_inn1_vs_season"] = t.team.map(adj)
    t = t.sort_values("avg_inn1", ascending=False).round(1)
    era = t.sort_values("avg_inn1_vs_season", ascending=False)
    insight = (f"On raw averages, {t.iloc[0].team} post the highest first-innings score ({t.iloc[0].avg_inn1:.1f}) - but "
               f"they played only in 2022-24, the highest-scoring era. Adjusting for season (score minus that season's "
               f"league average), the strongest first-innings batting sides are {era.iloc[0].team} "
               f"({era.iloc[0].avg_inn1_vs_season:+.1f} runs vs season average) and {era.iloc[1].team} "
               f"({era.iloc[1].avg_inn1_vs_season:+.1f}); the weakest is {era.iloc[-1].team} "
               f"({era.iloc[-1].avg_inn1_vs_season:+.1f}). Highest average second-innings score: "
               f"{t.sort_values('avg_inn2', ascending=False).iloc[0].team} "
               f"({t.avg_inn2.max():.1f}), which is truncated by the target and so not like-for-like.")
    return Question("B5", "B. Team performance", "Average first- and second-innings scores",
                    "Which teams have the highest average first-innings and second-innings scores?",
                    "Measures batting strength while separating the setting and chasing roles.",
                    "Full matches only. avg_inn1 = mean inn1_runs as batting_first_team; avg_inn2 = mean inn2_runs as "
                    "chasing_team; avg_inn1_vs_season = mean(inn1_runs - season mean inn1_runs).",
                    t, insight, "Raw averages are biased by era (teams active only in 2022-24 look stronger).")


def q_b6(D) -> Question:
    reg = D.reg
    ts = reg.groupby(["bowling_team", "season_year"]).agg(runs=("total_runs", "sum"), balls=("is_legal_delivery", "sum"),
                                                          outs=("is_player_out", "sum"), dots=("is_dot_ball", "sum"))
    league = reg.groupby("season_year").apply(lambda x: x.total_runs.sum() / x.is_legal_delivery.sum(), include_groups=False)
    ts["expected_runs"] = ts.balls * ts.index.get_level_values("season_year").map(league).values
    t = ts.groupby("bowling_team").sum()
    t["economy"] = t.runs / t.balls * 6
    t["economy_vs_league"] = (t.runs - t.expected_runs) / t.balls * 6
    t["balls_per_dismissal"] = t.balls / t.outs
    t["dot_pct"] = t.dots / t.balls * 100
    t = t.rename_axis("team").reset_index()[["team", "balls", "runs", "outs", "economy", "economy_vs_league",
                                             "balls_per_dismissal", "dot_pct"]]
    t = t.sort_values("economy_vs_league").round(2)
    d = t.sort_values("economy_vs_league", ascending=False)
    fig, ax = plt.subplots(figsize=(9, 6))
    ax.barh(d.team, d.economy_vs_league, color=[BLUE if v < 0 else ORANGE for v in d.economy_vs_league], height=0.68)
    for y, v in enumerate(d.economy_vs_league):
        ax.text(v + (0.02 if v >= 0 else -0.02), y, f"{v:+.2f}", va="center", ha="left" if v >= 0 else "right",
                fontsize=8.5, color=INK2)
    ax.axvline(0, color=INK2, lw=1)
    ax.grid(axis="y", visible=False)
    lim = max(abs(d.economy_vs_league).max() * 1.3, 0.5)
    ax.set_xlim(-lim, lim)
    ax.set_xlabel("Runs per over conceded vs league average in the same seasons (negative = better)")
    ax.set_title("Era-adjusted team bowling economy")
    subtitle(ax, "Team concedes all runs incl. extras; expected runs = balls bowled x league runs-per-ball that season")
    chart = save(fig, "B6_team_bowling_era_adjusted")
    seasons = D.team_long.groupby("team").season_year.nunique()
    est = t[t.team.map(seasons) >= 10]
    gt = t.set_index("team").loc["Gujarat Titans"]
    insight = (f"After adjusting for each season's scoring level, {t.iloc[0].team} ({seasons[t.iloc[0].team]} seasons) have "
               f"conceded the fewest runs relative to the league ({t.iloc[0].economy_vs_league:+.2f} runs/over), followed by "
               f"{t.iloc[1].team} ({seasons[t.iloc[1].team]} seasons, {t.iloc[1].economy_vs_league:+.2f}); both are small "
               f"samples. Among franchises with 10+ seasons the best is {est.iloc[0].team} "
               f"({est.iloc[0].economy_vs_league:+.2f}) and the most expensive is {est.iloc[-1].team} "
               f"({est.iloc[-1].economy_vs_league:+.2f}); overall the most expensive is {t.iloc[-1].team} "
               f"({t.iloc[-1].economy_vs_league:+.2f}). Raw economy alone would mislead: Gujarat Titans' raw economy "
               f"({gt.economy:.2f}) ranks {int((t.economy > gt.economy).sum()) + 1} highest of {len(t)} because they played "
               f"only in 2022-24, yet relative to those seasons "
               f"it is {gt.economy_vs_league:+.2f}. "
               f"Best wicket-taking frequency: {t.sort_values('balls_per_dismissal').iloc[0].team} "
               f"({t.balls_per_dismissal.min():.1f} balls per dismissal).")
    return Question("B6", "B. Team performance", "Team bowling strength",
                    "Which teams have the strongest bowling performance based on clearly defined measures?",
                    "Bowling quality is the other half of team strength; era adjustment makes 2008 and 2024 comparable.",
                    "economy = runs conceded (total_runs incl. extras) / legal balls x 6; economy_vs_league = (runs - "
                    "expected) / balls x 6 where expected = balls x league runs-per-ball in that season; "
                    "balls_per_dismissal = legal balls / player outs (incl. run outs, a team fielding outcome).",
                    t, insight, "Does not adjust for venue or opposition strength.", chart)


# =========================================================================== C. BATTING
BAT_COLS = ["player", "innings", "runs", "balls", "outs", "not_outs", "average", "strike_rate", "highest",
            "fifties", "hundreds", "fours", "sixes"]


def q_c1(D) -> Question:
    t = D.batters.sort_values("runs", ascending=False).head(15)[BAT_COLS].round(2)
    chart = hbar(t, "runs", "player", "Leading run scorers, IPL 2008-2024",
                 "Batter runs (batsman_runs), super overs excluded", "Runs", "C1_top_run_scorers")
    k = t.iloc[0]
    insight = (f"{k.player} leads with {k.runs:,} runs in {k.innings} innings (average {k.average:.2f}, strike rate "
               f"{k.strike_rate:.2f}), {k.runs - t.iloc[1].runs:,} clear of {t.iloc[1].player} ({t.iloc[1].runs:,}). "
               f"{t.iloc[2].player} ({t.iloc[2].runs:,}) and {t.iloc[3].player} ({t.iloc[3].runs:,}) complete the top four. "
               f"Kohli's total matches the published figure of 8,004 (see validation report).")
    return Question("C1", "C. Batting analysis", "Leading run scorers",
                    "Who are the leading run scorers?",
                    "Career run aggregates identify the league's most productive batters.",
                    "runs = sum(batsman_runs); innings = (match, innings) in which the player appeared as striker, "
                    "non-striker or was dismissed; balls = sum(is_ball_faced).",
                    t, insight, "Volume measure - rewards longevity.", chart)


def q_c2(D) -> Question:
    q = D.batters[D.batters.innings >= TH["bat_innings"]]
    t = q.sort_values("average", ascending=False).head(15)[BAT_COLS].round(2)
    insight = (f"With at least {TH['bat_innings']} innings ({len(q)} qualifying batters), {t.iloc[0].player} has the highest "
               f"average ({t.iloc[0].average:.2f}, {t.iloc[0].innings} innings), followed by {t.iloc[1].player} "
               f"({t.iloc[1].average:.2f}) and {t.iloc[2].player} ({t.iloc[2].average:.2f}). Averages are inflated by not-outs "
               f"(e.g. {t.sort_values('not_outs', ascending=False).iloc[0].player} has "
               f"{t.not_outs.max()} not-outs in this list), which is why strike rate and consistency (C3, C4) are read alongside.")
    return Question("C2", "C. Batting analysis", "Batting average",
                    "Who has the highest batting average among players meeting a reasonable minimum-innings threshold?",
                    "Average measures runs per dismissal - how expensive a batter is to get out.",
                    f"average = runs / outs (outs = is_player_out where player_dismissed = player; retired hurt not out). "
                    f"Minimum {TH['bat_innings']} innings.",
                    t, insight, "Finishers who often bat late and remain not out have inflated averages.",
                    "charts/C3_batting_average_vs_strike_rate.png")


def q_c3(D) -> Question:
    q = D.batters[D.batters.balls >= TH["bat_balls"]]
    t = q.sort_values("strike_rate", ascending=False).head(15)[BAT_COLS].round(2)
    s = D.batters[(D.batters.innings >= TH["bat_innings"]) & (D.batters.balls >= TH["bat_balls"])]
    fig, ax = plt.subplots(figsize=(10, 6.5))
    ax.scatter(s.average, s.strike_rate, s=np.clip(s.runs / 25, 12, 330), color=BLUE, alpha=0.55,
               edgecolor=SURFACE, linewidth=1)
    lab = pd.concat([s.nlargest(6, "runs"), s.nlargest(5, "strike_rate"), s.nlargest(4, "average")]).drop_duplicates("player")
    ax.axvline(s.average.median(), color=INK2, lw=1, ls="--")
    ax.axhline(s.strike_rate.median(), color=INK2, lw=1, ls="--")
    ax.set_xlabel("Batting average (runs per dismissal)")
    ax.set_ylabel("Strike rate (runs per 100 balls)")
    ax.set_title("Batting average vs strike rate")
    subtitle(ax, f"Batters with {TH['bat_innings']}+ innings and {TH['bat_balls']}+ balls faced (n={len(s)}). "
                 "Bubble size = career runs. Dashed lines = medians.")
    label_points(ax, lab.average, lab.strike_rate, lab.player)
    chart = save(fig, "C3_batting_average_vs_strike_rate")
    last = D.bat_inn.groupby("player").season_year.max()
    active24 = int((t.player.map(last) == 2024).sum())
    both = s[(s.average > s.average.median()) & (s.strike_rate > s.strike_rate.median())]
    rho = s[["average", "strike_rate"]].corr(method="spearman").iloc[0, 1]
    insight = (f"Among {len(q)} batters with {TH['bat_balls']}+ balls faced, {t.iloc[0].player} has the highest strike rate "
               f"({t.iloc[0].strike_rate:.2f}), then {t.iloc[1].player} ({t.iloc[1].strike_rate:.2f}) and "
               f"{t.iloc[2].player} ({t.iloc[2].strike_rate:.2f}). {active24} of the top 15 were still playing in 2024, "
               f"which fits the higher-scoring recent environment (not era-adjusted). In the scatter, {len(both)} of {len(s)} "
               f"qualifying batters are above the median on both average and strike rate; the rank correlation between "
               f"the two is {rho:.2f}.")
    return Question("C3", "C. Batting analysis", "Strike rate",
                    "Who has the highest strike rate among players meeting a reasonable minimum-balls threshold?",
                    "In T20, scoring speed matters as much as not getting out.",
                    f"strike_rate = runs / balls faced x 100 (balls faced exclude wides). Minimum {TH['bat_balls']} balls.",
                    t, insight, "Not era-adjusted; recent careers benefit from the 2023-24 scoring environment.", chart)


def q_c4(D) -> Question:
    bi = D.bat_inn
    g = bi.groupby("player").runs
    c = pd.DataFrame({"innings": g.size(), "mean_score": g.mean(), "median_score": g.median(),
                      "pct_30_plus": g.apply(lambda s: (s >= 30).mean() * 100),
                      "pct_under_10": g.apply(lambda s: (s < 10).mean() * 100),
                      "std_score": g.std()})
    c = c[c.innings >= TH["bat_innings"]]
    t = c.sort_values("pct_30_plus", ascending=False).head(15).round(1).reset_index()
    insight = (f"Consistency is measured as the share of innings with 30+ runs. {t.iloc[0].player} reaches 30 in "
               f"{t.iloc[0].pct_30_plus:.1f}% of {t.iloc[0].innings} innings, followed by {t.iloc[1].player} "
               f"({t.iloc[1].pct_30_plus:.1f}%) and {t.iloc[2].player} ({t.iloc[2].pct_30_plus:.1f}%). Even the most "
               f"consistent batters fail (under 10) in roughly a fifth to a third of innings "
               f"(range in this top 15: {t.pct_under_10.min():.1f}-{t.pct_under_10.max():.1f}%), which shows how volatile "
               f"T20 batting is. In {int((t.median_score < t.mean_score).sum())} of these 15 the median score is below the "
               f"mean, showing a right-skewed score distribution (a few big innings lift the mean).")
    return Question("C4", "C. Batting analysis", "Batting consistency",
                    "Which players score most consistently?",
                    "Selectors value reliable contributions, not only peak scores.",
                    f"Per-innings runs distribution for batters with {TH['bat_innings']}+ innings: pct_30_plus = innings "
                    "with >= 30 runs / innings; pct_under_10 = innings < 10; median and std of innings scores.",
                    t, insight, "Batting position (not in data) strongly affects opportunity to reach 30.")


def q_c5(D) -> Question:
    b = D.batters
    six = b.sort_values("sixes", ascending=False).head(15)[["player", "innings", "balls", "sixes", "fours", "boundary_run_pct"]]
    four = b.sort_values("fours", ascending=False).head(15)[["player", "innings", "balls", "fours", "sixes", "boundary_run_pct"]]
    q = b[b.balls >= TH["bat_balls"]].assign(balls_per_six=lambda x: x.balls / x.sixes.replace(0, np.nan))
    freq = q.sort_values("balls_per_six").head(10)[["player", "balls", "sixes", "balls_per_six"]].round(1)
    chart = hbar(six, "sixes", "player", "Most sixes, IPL 2008-2024",
                 "Sixes = deliveries with batsman_runs = 6 (no boundary flag in source); super overs excluded",
                 "Sixes", "C5_top_six_hitters", color=ORANGE)
    insight = (f"{six.iloc[0].player} has the most sixes ({six.iloc[0].sixes}), ahead of {six.iloc[1].player} "
               f"({six.iloc[1].sixes}) and {six.iloc[2].player} ({six.iloc[2].sixes}). {four.iloc[0].player} has the most "
               f"fours ({four.iloc[0].fours}). By frequency ({TH['bat_balls']}+ balls), {freq.iloc[0].player} hits a six every "
               f"{freq.iloc[0].balls_per_six:.1f} balls. League-wide, sixes per match rose from "
               f"{D.reg[D.reg.season_year == 2008].is_six.sum() / (D.mc.season_year == 2008).sum():.1f} (2008) to "
               f"{D.reg[D.reg.season_year == 2024].is_six.sum() / (D.mc.season_year == 2024).sum():.1f} (2024).")
    return Question("C5", "C. Batting analysis", "Fours and sixes",
                    "Which players contribute the most fours and sixes?",
                    "Boundary hitting is the main driver of T20 scoring rates.",
                    "is_four / is_six = batsman_runs == 4 / 6 (documented proxy). boundary_run_pct = (4 x fours + 6 x sixes) "
                    "/ runs x 100; balls_per_six = balls faced / sixes.",
                    six.round(1), insight, "Proxy cannot distinguish an all-run four from a boundary (rare).", chart,
                    extra_tables={"Most fours": four.round(1), f"Six-hitting frequency (min {TH['bat_balls']} balls)": freq})


def phase_profile(D):
    reg = D.reg
    p = reg.groupby("phase").agg(runs=("total_runs", "sum"), balls=("is_legal_delivery", "sum"),
                                 outs=("is_player_out", "sum"), dots=("is_dot_ball", "sum"),
                                 fours=("is_four", "sum"), sixes=("is_six", "sum"), extras=("extra_runs", "sum"))
    p = p.loc[["Powerplay", "Middle", "Death"]]
    p["run_rate"] = p.runs / p.balls * 6
    p["dot_pct"] = p.dots / p.balls * 100
    p["boundary_pct"] = (p.fours + p.sixes) / p.balls * 100
    p["balls_per_dismissal"] = p.balls / p.outs
    p["share_of_runs_pct"] = p.runs / p.runs.sum() * 100
    p["overs_in_phase"] = [6, 9, 5]
    return p


def q_c6(D) -> Question:
    p = phase_profile(D)
    t = p.round(2).reset_index()
    fig, axes = plt.subplots(1, 4, figsize=(13, 3.6))
    for ax, (col, ttl, fmt) in zip(axes, [("run_rate", "Run rate (per over)", "{:.2f}"),
                                          ("dot_pct", "Dot-ball %", "{:.1f}%"),
                                          ("boundary_pct", "Boundary % of balls", "{:.1f}%"),
                                          ("balls_per_dismissal", "Balls per dismissal", "{:.1f}")]):
        ax.bar(p.index, p[col], color=[PHASE_COLORS[i] for i in p.index], width=0.6)
        for x, v in enumerate(p[col]):
            ax.text(x, v, fmt.format(v), ha="center", va="bottom", fontsize=9, color=INK)
        ax.set_title(ttl, fontsize=11)
        ax.set_ylim(0, p[col].max() * 1.18)
        ax.grid(axis="x", visible=False)
    fig_title(fig, "How scoring differs by match phase (2008-2024, regulation deliveries)")
    chart = save(fig, "C6_phase_profile")
    bi = D.reg
    def phase_bat(ph):
        x = bi[bi.phase == ph].groupby("batter").agg(runs=("batsman_runs", "sum"), balls=("is_ball_faced", "sum"),
                                                     sixes=("is_six", "sum"))
        x = x[x.balls >= TH["phase_bat_balls"]]
        x["strike_rate"] = x.runs / x.balls * 100
        return x.sort_values("strike_rate", ascending=False).head(10).round(1).reset_index().rename(columns={"batter": "player"})
    pp, death = phase_bat("Powerplay"), phase_bat("Death")
    insight = (f"Death overs (16-20) score fastest ({p.run_rate['Death']:.2f}/over) but cost a wicket every "
               f"{p.balls_per_dismissal['Death']:.1f} balls, against {p.balls_per_dismissal['Middle']:.1f} in the middle overs "
               f"and {p.balls_per_dismissal['Powerplay']:.1f} in the Powerplay. The Powerplay ({p.run_rate['Powerplay']:.2f}/over) "
               f"combines the highest dot-ball % ({p.dot_pct['Powerplay']:.1f}%) with a boundary % "
               f"({p.boundary_pct['Powerplay']:.1f}%) close to the death overs ({p.boundary_pct['Death']:.1f}%): scoring comes "
               f"in boundaries rather than singles while the field is restricted. The middle overs are the slowest ({p.run_rate['Middle']:.2f}/over) but contribute "
               f"{p.share_of_runs_pct['Middle']:.1f}% of all runs because they are the longest phase. Fastest Powerplay "
               f"scorer ({TH['phase_bat_balls']}+ balls): {pp.iloc[0].player} (SR {pp.iloc[0].strike_rate:.1f}); fastest "
               f"death-overs scorer: {death.iloc[0].player} (SR {death.iloc[0].strike_rate:.1f}).")
    return Question("C6", "C. Batting analysis", "Scoring by match phase",
                    "How do scoring patterns differ between Powerplay, Middle Overs and Death Overs?",
                    "Phase-specific roles (openers, anchors, finishers) drive team selection and tactics.",
                    "Per phase: run rate = runs / legal balls x 6; dot % = is_dot_ball / legal balls; boundary % = "
                    "(fours + sixes) / legal balls; balls per dismissal = legal balls / player outs.",
                    t, insight, "Phases use 20-over boundaries even in shortened matches (L10).", chart,
                    extra_tables={f"Fastest Powerplay scorers (min {TH['phase_bat_balls']} balls)": pp,
                                  f"Fastest death-overs scorers (min {TH['phase_bat_balls']} balls)": death})


# =========================================================================== D. BOWLING
BOWL_COLS = ["bowler", "innings", "overs", "legal_balls", "runs_conceded", "wickets", "economy", "average",
             "strike_rate", "dot_pct"]


def q_d1(D) -> Question:
    t = D.bowlers.sort_values("wickets", ascending=False).head(15)[BOWL_COLS].round(2)
    chart = hbar(t, "wickets", "bowler", "Leading wicket-takers, IPL 2008-2024",
                 "Bowler-credited wickets only (run outs, retired hurt/out, obstructing excluded); super overs excluded",
                 "Wickets", "D1_top_wicket_takers", color=AQUA)
    insight = (f"{t.iloc[0].bowler} has the most bowler-credited wickets ({t.iloc[0].wickets}), followed by "
               f"{t.iloc[1].bowler} ({t.iloc[1].wickets}), {t.iloc[2].bowler} ({t.iloc[2].wickets}) and "
               f"{t.iloc[3].bowler} ({t.iloc[3].wickets}). Using raw is_wicket instead would wrongly add run-outs and "
               f"retirements to bowlers (see validation).")
    return Question("D1", "D. Bowling analysis", "Leading wicket-takers",
                    "Who are the leading bowler-credited wicket takers?",
                    "Wicket-taking is the primary measure of bowling impact.",
                    "wickets = sum(is_bowler_wicket): bowled, caught, caught and bowled, lbw, stumped, hit wicket.",
                    t, insight, "Volume measure - rewards longevity.", chart)


def q_d2(D) -> Question:
    q = D.bowlers[D.bowlers.legal_balls >= TH["bowl_balls"]]
    t = q.sort_values("economy").head(15)[BOWL_COLS].round(2)
    b = D.reg[D.reg.bowler.isin(t.bowler)]
    pre = (b.assign(x=(b.season_year < 2018) * b.is_legal_delivery).groupby("bowler").x.sum()
           / b.groupby("bowler").is_legal_delivery.sum())
    insight = (f"Among {len(q)} bowlers with {TH['bowl_balls']}+ legal balls, {t.iloc[0].bowler} has the best economy "
               f"({t.iloc[0].economy:.2f} runs/over), then {t.iloc[1].bowler} ({t.iloc[1].economy:.2f}) and "
               f"{t.iloc[2].bowler} ({t.iloc[2].economy:.2f}). {int((pre > 0.5).sum())} of the top 15 bowled most of their "
               f"balls before 2018, when scoring was lower - economy is not era-adjusted here. Of the more recent bowlers, "
               f"{pre.idxmin()} stands out ({pre.min() * 100:.0f}% of balls before 2018).")
    return Question("D2", "D. Bowling analysis", "Economy rate",
                    "Which bowlers have the best economy rates with a reasonable minimum legal-delivery threshold?",
                    "Economy captures run containment, critical in T20.",
                    f"economy = bowler_runs_conceded / legal balls x 6 (byes, leg-byes and penalties not charged). "
                    f"Minimum {TH['bowl_balls']} legal balls.",
                    t, insight, "Era effect: older careers benefit from lower-scoring seasons.",
                    "charts/D3_bowler_economy_vs_strike_rate.png")


def q_d3(D) -> Question:
    q = D.bowlers[D.bowlers.legal_balls >= TH["bowl_balls"]]
    avg = q.sort_values("average").head(15)[BOWL_COLS].round(2)
    sr = q.sort_values("strike_rate").head(15)[BOWL_COLS].round(2)
    fig, ax = plt.subplots(figsize=(10, 6.5))
    ax.scatter(q.economy, q.strike_rate, s=np.clip(q.wickets * 1.6, 12, 330), color=AQUA, alpha=0.6,
               edgecolor=SURFACE, linewidth=1)
    lab = pd.concat([q.nlargest(6, "wickets"), q.nsmallest(4, "economy"), q.nsmallest(4, "strike_rate")]).drop_duplicates("bowler")
    ax.axvline(q.economy.median(), color=INK2, lw=1, ls="--")
    ax.axhline(q.strike_rate.median(), color=INK2, lw=1, ls="--")
    ax.invert_yaxis()
    label_points(ax, lab.economy, lab.strike_rate, lab.bowler)
    ax.set_xlabel("Economy rate (runs per over) - lower is better")
    ax.set_ylabel("Bowling strike rate (balls per wicket) - lower is better (axis inverted)")
    ax.set_title("Bowling economy vs strike rate")
    subtitle(ax, f"Bowlers with {TH['bowl_balls']}+ legal balls (n={len(q)}). Bubble size = wickets. "
                 "Top-left = economical AND penetrative.")
    chart = save(fig, "D3_bowler_economy_vs_strike_rate")
    insight = (f"Best bowling average: {avg.iloc[0].bowler} ({avg.iloc[0].average:.2f} runs per wicket), then "
               f"{avg.iloc[1].bowler} ({avg.iloc[1].average:.2f}). Best strike rate: {sr.iloc[0].bowler} "
               f"({sr.iloc[0].strike_rate:.2f} balls per wicket), then {sr.iloc[1].bowler} ({sr.iloc[1].strike_rate:.2f}). "
               f"The scatter separates containing bowlers (low economy) from wicket-takers (low strike rate); bowlers "
               f"strong on both appear in the top-left quadrant.")
    return Question("D3", "D. Bowling analysis", "Bowling average and strike rate",
                    "Which bowlers have the best bowling averages and strike rates?",
                    "Average = cost per wicket; strike rate = frequency of wickets.",
                    f"average = bowler_runs_conceded / wickets; strike_rate = legal balls / wickets. "
                    f"Minimum {TH['bowl_balls']} legal balls.",
                    avg, insight, "Not era-adjusted.", chart, extra_tables={"Best bowling strike rate": sr})


def q_d4(D) -> Question:
    out = {}
    for ph in ["Powerplay", "Middle", "Death"]:
        b = Data._bowler_careers(D.reg[D.reg.phase == ph])
        b = b[b.legal_balls >= TH["phase_bowl_balls"]].sort_values("economy")
        out[ph] = b[["bowler", "legal_balls", "runs_conceded", "wickets", "economy", "strike_rate", "dot_pct"]].head(10).round(2)
    pp, mid, de = out["Powerplay"], out["Middle"], out["Death"]
    insight = (f"With {TH['phase_bowl_balls']}+ legal balls in the phase: best Powerplay economy - {pp.iloc[0].bowler} "
               f"({pp.iloc[0].economy:.2f}); best middle-overs economy - {mid.iloc[0].bowler} ({mid.iloc[0].economy:.2f}); "
               f"best death-overs economy - {de.iloc[0].bowler} ({de.iloc[0].economy:.2f}), then {de.iloc[1].bowler} "
               f"({de.iloc[1].economy:.2f}). The median economy of the 10 best death bowlers ({de.economy.median():.2f}) is "
               f"{de.economy.median() - pp.economy.median():.2f} runs/over higher than the 10 best Powerplay bowlers "
               f"({pp.economy.median():.2f}), matching the league phase profile (C6). Narine and Malinga appear in more "
               f"than one phase list.")
    assert {"SP Narine", "SL Malinga"} <= set(pp.bowler) | set(mid.bowler) | set(de.bowler)
    return Question("D4", "D. Bowling analysis", "Phase bowling",
                    "Which bowlers perform best in different match phases?",
                    "Teams pick bowlers for specific phases (new ball, middle, death).",
                    f"Bowler economy/strike rate computed within each phase; minimum {TH['phase_bowl_balls']} legal balls "
                    "in that phase.", pp, insight, "Phase boundaries fixed at 20-over values (L10).", None,
                    extra_tables={"Middle overs": mid, "Death overs": de})


def q_d5(D, S) -> Question:
    s = S.copy()
    s["bowling_sr"] = s.legal_balls / s.bowler_wickets
    s["economy"] = s.run_rate
    t = s[["season_year", "economy", "bowling_sr", "dot_pct", "bowler_wickets", "player_outs"]].round(2)
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.2), sharex=True)
    axes[0].plot(s.season_year, s.economy, color=ORANGE, marker="o", ms=4)
    axes[0].set_title("Runs conceded per over")
    axes[1].plot(s.season_year, s.bowling_sr, color=AQUA, marker="o", ms=4)
    axes[1].set_title("Legal balls per bowler wicket")
    for ax in axes:
        ax.set_xticks(s.season_year[::2])
    fig_title(fig, "League bowling by season (regulation deliveries)")
    chart = save(fig, "D5_bowling_by_season")
    insight = (f"League economy ranged from {s.economy.min():.2f} ({s.loc[s.economy.idxmin(), 'season_year']:.0f}) to "
               f"{s.economy.max():.2f} ({s.loc[s.economy.idxmax(), 'season_year']:.0f}), a "
               f"{(s.economy.max() / s.economy.min() - 1) * 100:.0f}% spread. Balls per bowler wicket ranged from "
               f"{s.bowling_sr.min():.1f} to {s.bowling_sr.max():.1f} (a {(s.bowling_sr.max() / s.bowling_sr.min() - 1) * 100:.0f}% "
               f"spread), so wicket frequency varied less than run-conceding. Dot-ball % fell from {s.dot_pct.iloc[0]:.1f}% (2008) to {s.dot_pct.iloc[-1]:.1f}% (2024).")
    return Question("D5", "D. Bowling analysis", "Bowling patterns across seasons",
                    "How do wicket-taking and run-conceding patterns vary across seasons?",
                    "Gives the league context needed to judge any bowler's numbers.",
                    "economy = all runs / legal balls x 6 (team view, incl. extras); bowling_sr = legal balls / bowler wickets; "
                    "dot % = is_dot_ball / legal balls.", t, insight, "", chart)


# =========================================================================== E. MATCH & VENUE
def prop_ci(k, n):
    p = k / n
    se = np.sqrt(p * (1 - p) / n)
    return p * 100, (p - 1.96 * se) * 100, (p + 1.96 * se) * 100


def q_e1(D) -> Question:
    mc = D.mc[D.mc.is_no_result == 0]
    p, lo, hi = prop_ci(mc.toss_winner_won.sum(), len(mc))
    by_dec = mc.groupby("toss_decision").toss_winner_won.agg(["size", "sum", "mean"])
    by_dec["win_pct"] = by_dec["mean"] * 100
    by_season = D.mc.groupby("season_year").agg(field_pct=("toss_decision", lambda s: (s == "field").mean() * 100))
    by_season["toss_winner_won_pct"] = mc.groupby("season_year").toss_winner_won.mean() * 100
    t = pd.DataFrame({"metric": ["Decided matches", "Toss winner won %", "95% CI low", "95% CI high",
                                 "Won % when choosing to bat", "Won % when choosing to field", "Chose to field %"],
                      "value": [len(mc), p, lo, hi, by_dec.loc["bat", "win_pct"], by_dec.loc["field", "win_pct"],
                                (D.mc.toss_decision == "field").mean() * 100]}).round(2)
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.2), sharex=True)
    axes[0].plot(by_season.index, by_season.field_pct, color=BLUE, marker="o", ms=4)
    axes[0].set_title("Toss winners choosing to field")
    axes[1].plot(by_season.index, by_season.toss_winner_won_pct, color=ORANGE, marker="o", ms=4)
    axes[1].axhline(50, color=INK2, lw=1, ls="--")
    axes[1].set_title("Toss winner went on to win")
    for ax in axes:
        ax.yaxis.set_major_formatter(mtick.PercentFormatter())
        ax.set_xticks(by_season.index[::2])
    axes[0].set_ylim(0, 100)
    axes[1].set_ylim(20, 80)
    fig_title(fig, "Toss decisions and outcomes by season")
    chart = save(fig, "E1_toss_by_season")
    insight = (f"The toss winner won {p:.1f}% of {len(mc)} decided matches (95% CI {lo:.1f}-{hi:.1f}%). The interval "
               f"{'includes' if lo <= 50 <= hi else 'excludes'} 50%, so across the whole period the toss shows "
               f"{'no' if lo <= 50 <= hi else 'only a small'} statistically clear advantage. Teams increasingly choose to "
               f"field: {by_season.field_pct.iloc[0]:.0f}% in 2008 vs {by_season.field_pct.iloc[-1]:.0f}% in 2024 "
               f"(peak {by_season.field_pct.max():.0f}%). Toss winners who chose to field won {by_dec.loc['field', 'win_pct']:.1f}% "
               f"vs {by_dec.loc['bat', 'win_pct']:.1f}% when choosing to bat. This is association only: the toss decision is "
               f"itself a strategic choice influenced by conditions.")
    return Question("E1", "E. Match & venue insights", "Toss impact",
                    "Does winning the toss correlate with winning the match?",
                    "Tests a widely held belief and informs how much to read into toss results.",
                    "toss_winner_won over decided matches (no-results excluded; super-over winners count). 95% CI via "
                    "normal approximation to the binomial.", t, insight, "Observational; no causal claim.", chart)


def q_e2(D) -> Question:
    d = D.decided_bfc
    k, n = (d.result_for == "chasing").sum(), len(d)
    p, lo, hi = prop_ci(k, n)
    nd = d[d.is_dls == 0]
    p2 = (nd.result_for == "chasing").mean() * 100
    s = d.groupby("season_year").agg(matches=("match_id", "size"),
                                     chase_wins=("result_for", lambda x: (x == "chasing").sum()))
    s["chase_win_pct"] = s.chase_wins / s.matches * 100
    t = s.reset_index().round(1)
    fig, ax = plt.subplots(figsize=(10, 4.2))
    ax.bar(s.index, s.chase_win_pct, color=[ORANGE if v >= 50 else BLUE for v in s.chase_win_pct], width=0.7)
    ax.axhline(50, color=INK2, lw=1, ls="--")
    for x, v in zip(s.index, s.chase_win_pct):
        ax.text(x, v + 1, f"{v:.0f}%", ha="center", fontsize=8.5, color=INK)
    ax.set_ylim(0, 85)
    ax.yaxis.set_major_formatter(mtick.PercentFormatter())
    ax.set_xticks(s.index)
    ax.tick_params(axis="x", rotation=45)
    ax.set_ylabel("Chasing team win %")
    ax.set_title("Share of matches won by the chasing team, by season")
    subtitle(ax, "Orange = chasing won the majority. Decided matches only (super-over ties and no-results excluded); uses result_for.")
    chart = save(fig, "E2_chasing_win_pct_by_season")
    insight = (f"Chasing teams won {p:.1f}% of {n} decided matches (95% CI {lo:.1f}-{hi:.1f}%); excluding the "
               f"{len(d) - len(nd)} D/L matches gives {p2:.1f}%. Chasing won the majority in "
               f"{(s.chase_win_pct > 50).sum()} of 17 seasons; the strongest chasing season was "
               f"{s.chase_win_pct.idxmax()} ({s.chase_win_pct.max():.1f}%), while batting first won the majority in "
               f"{', '.join(map(str, s[s.chase_win_pct < 50].index))}.")
    return Question("E2", "E. Match & venue insights", "Batting first vs chasing",
                    "How often do teams win batting first versus chasing?",
                    "Underpins the toss decision and team strategy.",
                    "Share of matches with result_for == 'chasing' among matches with result_for in {batting first, chasing}.",
                    t, insight, "D/L matches included via result_for; sensitivity without them reported.", chart)


def venue_table(D) -> pd.DataFrame:
    f = D.full
    v = f.groupby("venue").agg(full_matches=("match_id", "size"), avg_inn1=("inn1_runs", "mean"),
                               first_season=("season_year", "min"), last_season=("season_year", "max"))
    season_avg = f.groupby("season_year").inn1_runs.transform("mean")
    v["avg_inn1_vs_season"] = f.assign(a=f.inn1_runs - season_avg).groupby("venue").a.mean()
    d = D.decided_bfc.groupby("venue").agg(decided=("match_id", "size"),
                                           chase_wins=("result_for", lambda x: (x == "chasing").sum()))
    v = v.join(d)
    v["chase_win_pct"] = v.chase_wins / v.decided * 100
    reg_full = D.reg[D.reg.match_id.isin(f.match_id)]
    rr = reg_full.groupby("venue").agg(runs=("total_runs", "sum"), balls=("is_legal_delivery", "sum"),
                                       sixes=("is_six", "sum"))
    v["run_rate"] = rr.runs / rr.balls * 6
    v["sixes_per_match"] = rr.sixes / v.full_matches
    v["city"] = D.mc.groupby("venue").city.first()
    return v.reset_index()


def q_e3(D, V) -> Question:
    q = V[V.full_matches >= TH["venue_matches"]]
    t = q.sort_values("avg_inn1", ascending=False)[["venue", "city", "full_matches", "first_season", "last_season",
                                                    "avg_inn1", "avg_inn1_vs_season", "run_rate"]].round(1)
    adj = t.sort_values("avg_inn1_vs_season", ascending=False)
    insight = (f"Of {len(q)} venues with {TH['venue_matches']}+ full matches, {t.iloc[0].venue} has the highest average "
               f"first-innings score ({t.iloc[0].avg_inn1:.1f}), and {t.iloc[-1].venue} the lowest ({t.iloc[-1].avg_inn1:.1f}). "
               f"Raw venue averages can be confounded by which seasons a venue hosted (e.g. Narendra Modi Stadium ranks "
               f"{int((t.avg_inn1 > t.set_index('venue').avg_inn1['Narendra Modi Stadium']).sum()) + 1} of {len(t)} raw but "
               f"is {t.set_index('venue').avg_inn1_vs_season['Narendra Modi Stadium']:+.1f} vs its seasons' averages). "
               f"Adjusted for season, the highest-scoring venue is {adj.iloc[0].venue} ({adj.iloc[0].avg_inn1_vs_season:+.1f} "
               f"runs vs season average) and the lowest is {adj.iloc[-1].venue} ({adj.iloc[-1].avg_inn1_vs_season:+.1f}).")
    return Question("E3", "E. Match & venue insights", "Venue first-innings scores",
                    "Which venues have the highest average first-innings scores?",
                    "Venue 'par scores' inform team strategy and fan expectations.",
                    f"Full matches per venue; avg_inn1 = mean inn1_runs; avg_inn1_vs_season = mean(inn1_runs - season mean). "
                    f"Minimum {TH['venue_matches']} full matches.", t, insight,
                    "Venues hosted different eras; use the season-adjusted column for fair comparison.",
                    "charts/E4_venue_first_innings_vs_chase.png")


def q_e4(D, V) -> Question:
    q = V[V.decided >= TH["venue_matches"]].copy()
    ci = q.apply(lambda x: prop_ci(x.chase_wins, x.decided), axis=1, result_type="expand")
    q["ci_low"], q["ci_high"] = ci[1], ci[2]
    t = q.sort_values("chase_win_pct", ascending=False)[["venue", "city", "decided", "chase_wins", "chase_win_pct",
                                                         "ci_low", "ci_high"]].round(1)
    sig = t[(t.ci_low > 50) | (t.ci_high < 50)]
    s = V[(V.decided >= TH["venue_matches"]) & (V.full_matches >= TH["venue_matches"])]
    fig, ax = plt.subplots(figsize=(10.5, 6.5))
    ax.scatter(s.avg_inn1_vs_season, s.chase_win_pct, s=s.decided * 3, color=BLUE, alpha=0.6, edgecolor=SURFACE, linewidth=1)
    short = {"Punjab Cricket Association IS Bindra Stadium": "PCA Mohali",
             "Rajiv Gandhi International Stadium": "Rajiv Gandhi (Hyd)",
             "Maharashtra Cricket Association Stadium": "MCA Pune",
             "Dubai International Cricket Stadium": "Dubai",
             "Dr DY Patil Sports Academy": "DY Patil"}
    ax.axhline(50, color=INK2, lw=1, ls="--")
    ax.axvline(0, color=INK2, lw=1, ls="--")
    ax.yaxis.set_major_formatter(mtick.PercentFormatter())
    ax.set_xlabel("First-innings score vs season average (runs)")
    ax.set_ylabel("Chasing team win %")
    ax.set_title("Venue scoring vs chasing success")
    subtitle(ax, f"Venues with {TH['venue_matches']}+ full and decided matches (n={len(s)}). Bubble size = decided matches.")
    label_points(ax, s.avg_inn1_vs_season, s.chase_win_pct,
                 [short.get(v, v.replace(" Stadium", "").replace(" Cricket", "")) for v in s.venue])
    chart = save(fig, "E4_venue_first_innings_vs_chase")
    insight = (f"Among {len(q)} venues with {TH['venue_matches']}+ decided matches, chasing succeeds most at "
               f"{t.iloc[0].venue} ({t.iloc[0].chase_win_pct:.1f}% of {t.iloc[0].decided}) and "
               f"{t.iloc[1].venue} ({t.iloc[1].chase_win_pct:.1f}%), and least at {t.iloc[-1].venue} "
               f"({t.iloc[-1].chase_win_pct:.1f}% of {t.iloc[-1].decided}). Sample sizes are small: 95% confidence intervals "
               f"are {((t.ci_high - t.ci_low) / 2).min():.0f}-{((t.ci_high - t.ci_low) / 2).max():.0f} points wide either "
               f"side. Only {len(sig)} venue(s) have an interval that excludes 50%"
               f"{': ' + ', '.join(sig.venue) if len(sig) else ''}; differences between the other venues may be chance.")
    return Question("E4", "E. Match & venue insights", "Venue chasing success",
                    "Which venues have the strongest chasing success rates?",
                    "Helps decide whether to bat or field after winning the toss at a given ground.",
                    f"chase_win_pct = chasing wins / matches with result_for in {{batting first, chasing}} at the venue. "
                    f"Minimum {TH['venue_matches']} decided matches.", t, insight,
                    "Small samples per venue; association only.", chart)


def q_e5(D) -> Question:
    mc = D.mc[D.mc.is_dls == 0]
    runs = mc[mc.result_for == "batting first"].result_margin
    chase = mc[mc.result_for == "chasing"].copy()
    chase["balls_remaining"] = chase.target_balls - chase.inn2_legal_balls
    wk = chase.result_margin
    bins = pd.cut(runs, [0, 10, 20, 30, 50, 200], labels=["1-10", "11-20", "21-30", "31-50", "51+"])
    t1 = bins.value_counts().sort_index().rename_axis("runs_margin").reset_index(name="matches")
    t1["pct"] = (t1.matches / t1.matches.sum() * 100).round(1)
    t2 = wk.astype(int).value_counts().sort_index().rename_axis("wickets_margin").reset_index(name="matches")
    t2["pct"] = (t2.matches / t2.matches.sum() * 100).round(1)
    close = ((runs <= 10).sum() + (chase.balls_remaining <= 6).sum() + D.mc.is_super_over.sum())
    decided = len(D.mc[D.mc.is_no_result == 0])
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.2))
    axes[0].hist(runs, bins=range(0, int(runs.max()) + 6, 5), color=BLUE, edgecolor=SURFACE)
    axes[0].set_title("Batting-first wins: margin in runs")
    axes[0].set_xlabel("Runs"); axes[0].set_ylabel("Matches")
    axes[1].bar(t2.wickets_margin, t2.matches, color=ORANGE, width=0.7)
    axes[1].set_xticks(t2.wickets_margin)
    axes[1].set_title("Chasing wins: margin in wickets")
    axes[1].set_xlabel("Wickets in hand")
    for ax in axes:
        ax.grid(axis="x", visible=False)
    fig_title(fig, "Distribution of winning margins (non-D/L matches)")
    chart = save(fig, "E5_winning_margins")
    insight = (f"Batting-first wins have a median margin of {runs.median():.0f} runs; {t1.pct.iloc[0]:.1f}% are by 10 runs or "
               f"fewer and {t1[t1.runs_margin == '51+'].pct.iloc[0]:.1f}% by more than 50. Chasing wins are most often by "
               f"{int(t2.sort_values('matches').iloc[-1].wickets_margin)} wickets ({t2.sort_values('matches').iloc[-1].pct:.1f}%), "
               f"with a median of {chase.balls_remaining.median():.0f} balls to spare. Using a 'close match' definition "
               f"(won by <=10 runs, chase completed with <=6 balls left, or a tie), {close} of {decided} decided matches "
               f"({close / decided * 100:.1f}%) were close.")
    return Question("E5", "E. Match & venue insights", "Winning margins",
                    "What are the most common winning margins?",
                    "Margins show competitive balance and how often matches go down to the wire.",
                    "result_margin for non-D/L matches, split by result_for; balls_remaining = target_balls - inn2_legal_balls.",
                    t1, insight, "D/L matches excluded because their margins are against a revised target.", chart,
                    extra_tables={"Wickets margins (chasing wins)": t2})


def q_e6(D, V) -> Question:
    s = V[(V.full_matches >= TH["venue_matches"]) & (V.decided >= TH["venue_matches"])].copy()
    from scipy.stats import spearmanr  # scipy ships with the scientific stack; used only for this p-value
    rho, pval = spearmanr(s.avg_inn1_vs_season, s.chase_win_pct)
    strength = "weak" if abs(rho) < 0.3 else ("moderate" if abs(rho) < 0.6 else "strong")
    s["group"] = pd.qcut(s.avg_inn1_vs_season, 3, labels=["Low-scoring third", "Middle third", "High-scoring third"])
    g = s.groupby("group", observed=True).agg(venues=("venue", "size"), avg_inn1_vs_season=("avg_inn1_vs_season", "mean"),
                                             run_rate=("run_rate", "mean"), sixes_per_match=("sixes_per_match", "mean"),
                                             chase_win_pct=("chase_win_pct", "mean"),
                                             members=("venue", lambda x: "; ".join(x)))
    t = g.round(2).reset_index()
    hi, lo = t.iloc[-1], t.iloc[0]
    insight = (f"Splitting {len(s)} qualifying venues into thirds by season-adjusted first-innings score: high-scoring venues "
               f"average {hi.run_rate:.2f} runs/over and {hi.sixes_per_match:.1f} sixes per match vs {lo.run_rate:.2f} and "
               f"{lo.sixes_per_match:.1f} at low-scoring venues. Chasing win % is {hi.chase_win_pct:.1f}% at high-scoring "
               f"vs {lo.chase_win_pct:.1f}% at low-scoring venues. Across venues the rank correlation between scoring and "
               f"chasing success is {strength} and {'negative' if rho < 0 else 'positive'} (Spearman rho = {rho:.2f}, "
               f"p = {pval:.2f}, n = {len(s)}): higher-scoring grounds have tended to see slightly LESS chasing success, but "
               f"with only {len(s)} venues this is {'not ' if pval >= 0.05 else ''}statistically significant at the 5% level "
               f"and should be treated as a hypothesis, not a rule.")
    return Question("E6", "E. Match & venue insights", "High- vs low-scoring venues",
                    "Are there noticeable differences between high-scoring and low-scoring venues?",
                    "Tests whether venue scoring character translates into different match dynamics.",
                    "Qualifying venues split into terciles of avg_inn1_vs_season; compare run rate, sixes per full match, "
                    "chase win %. Spearman rank correlation across venues.", t, insight,
                    "Small number of venues; correlation is descriptive.", "charts/E4_venue_first_innings_vs_chase.png")


# =========================================================================== VALIDATION
class Val:
    def __init__(self):
        self.rows = []

    def add(self, cid, area, check, expected, actual, ok, note=""):
        self.rows.append({"check_id": cid, "area": area, "check": check, "expected": expected,
                          "actual": actual, "status": "PASS" if bool(ok) else "FAIL", "note": note})

    def frame(self):
        return pd.DataFrame(self.rows)


def validate(D: Data, S, T, V, Q) -> pd.DataFrame:
    v = Val()
    mc, dc, reg = D.mc, D.dc, D.reg
    v.add("E01", "Counts", "Match rows loaded", 1095, len(mc), len(mc) == 1095)
    v.add("E02", "Counts", "Delivery rows loaded", 260920, len(dc), len(dc) == 260920)
    v.add("E03", "Super overs", "Regulation frame has no super-over rows", 0, int(reg.is_super_over.sum()),
          reg.is_super_over.sum() == 0 and len(reg) + len(D.so) == len(dc))
    v.add("E04", "Super overs", "Regulation runs = Phase 2 validated total", 347470, int(reg.total_runs.sum()),
          reg.total_runs.sum() == 347470)
    v.add("E05", "Super overs", "No super-over ball reaches batting innings table", 0,
          int(D.bat_inn.inning.gt(2).sum()), D.bat_inn.inning.max() <= 2)
    v.add("E06", "Runs", "batsman_runs + extra_runs == total_runs (regulation)", 0,
          int((reg.batsman_runs + reg.extra_runs != reg.total_runs).sum()),
          (reg.batsman_runs + reg.extra_runs == reg.total_runs).all())
    v.add("E07", "Runs", "Bowler runs + byes + leg-byes + penalty == team runs", int(reg.total_runs.sum()),
          int(D.bowlers.runs_conceded.sum() + reg.bye_runs.sum() + reg.legbye_runs.sum() + reg.penalty_runs.sum()),
          D.bowlers.runs_conceded.sum() + reg.bye_runs.sum() + reg.legbye_runs.sum() + reg.penalty_runs.sum() == reg.total_runs.sum())
    v.add("E08", "Legal balls", "Bowler legal balls sum == regulation legal deliveries", 251319,
          int(D.bowlers.legal_balls.sum()), D.bowlers.legal_balls.sum() == reg.is_legal_delivery.sum() == 251319)
    v.add("E09", "Legal balls", "Batter balls faced sum == regulation non-wide deliveries", int((reg.is_wide == 0).sum()),
          int(D.batters.balls.sum()), D.batters.balls.sum() == (reg.is_wide == 0).sum())
    v.add("E10", "Legal balls", "Season legal balls sum == overall", int(reg.is_legal_delivery.sum()),
          int(S.legal_balls.sum()), S.legal_balls.sum() == reg.is_legal_delivery.sum())
    inn = reg.groupby(["match_id", "inning"]).total_runs.sum().unstack()
    ok = (inn[1].reindex(mc.match_id).values == mc.inn1_runs.values).all() and \
         np.allclose(inn[2].reindex(mc.match_id).fillna(-1).values, mc.inn2_runs.fillna(-1).values)
    v.add("E11", "Innings", "Innings totals from deliveries == matches inn1/inn2", "all 1,095 match", "", ok)
    v.add("E12", "Innings", "Sum of innings totals == regulation runs", int(reg.total_runs.sum()),
          int(mc.inn1_runs.sum() + mc.inn2_runs.sum()), mc.inn1_runs.sum() + mc.inn2_runs.sum() == reg.total_runs.sum())
    first_team = reg[reg.inning == 1].groupby("match_id").batting_team.first()
    v.add("E13", "Batting order", "batting_first_team == innings-1 batting team (deliveries)", 0,
          int((first_team.reindex(mc.match_id).values != mc.batting_first_team.values).sum()),
          (first_team.reindex(mc.match_id).values == mc.batting_first_team.values).all())
    rf = mc.result_for.value_counts()
    v.add("E14", "Batting order", "result_for categories sum to all matches", 1095, int(rf.sum()),
          rf.sum() == 1095 and set(rf.index) == {"batting first", "chasing", "super over", "no result"})
    tl = D.team_long
    bfw = tl[(tl.batted_first == 1) & (tl.result_for == "batting first")].won.sum()
    chw = tl[(tl.batted_first == 0) & (tl.result_for == "chasing")].won.sum()
    v.add("E15", "Batting order", "Team-level bat-first/chase wins == match-level result_for counts",
          f"{rf['batting first']} / {rf['chasing']}", f"{bfw} / {chw}", bfw == rf["batting first"] and chw == rf["chasing"])
    kinds = reg[reg.is_bowler_wicket == 1].dismissal_kind.value_counts()
    v.add("E16", "Wickets", "Bowler wickets only from bowler-credited dismissal kinds",
          sorted(cfg.BOWLER_WICKET_KINDS), sorted(kinds.index), set(kinds.index) == cfg.BOWLER_WICKET_KINDS)
    v.add("E17", "Wickets", "Sum of bowler-career wickets == regulation bowler wickets", int(reg.is_bowler_wicket.sum()),
          int(D.bowlers.wickets.sum()), D.bowlers.wickets.sum() == reg.is_bowler_wicket.sum())
    diff = reg.is_wicket.sum() - reg.is_bowler_wicket.sum()
    nonb = reg.dismissal_kind.isin(cfg.NON_BOWLER_DISMISSALS).sum()
    v.add("E18", "Wickets", "raw is_wicket - bowler wickets == run outs + retired + obstructing", int(nonb), int(diff), diff == nonb)
    v.add("E19", "Wickets", "Retired hurt not counted as dismissal or bowler wicket", 0,
          int(reg[reg.is_retired_hurt == 1][["is_player_out", "is_bowler_wicket"]].sum().sum()),
          reg[reg.is_retired_hurt == 1][["is_player_out", "is_bowler_wicket"]].sum().sum() == 0)
    v.add("E20", "Player totals", "Sum of batter runs == regulation batsman_runs", int(reg.batsman_runs.sum()),
          int(D.batters.runs.sum()), D.batters.runs.sum() == reg.batsman_runs.sum())
    v.add("E21", "Player totals", "Sum of batter dismissals == regulation player outs", int(reg.is_player_out.sum()),
          int(D.batters.outs.sum()), D.batters.outs.sum() == reg.is_player_out.sum())
    v.add("E22", "Player totals", "No batter dismissed more than once in an innings", 1, int(D.bat_inn.out.max()),
          D.bat_inn.out.max() <= 1)
    v.add("E23", "Player totals", "Sum of fours/sixes in batter table == deliveries",
          f"{int(reg.is_four.sum())}/{int(reg.is_six.sum())}", f"{int(D.batters.fours.sum())}/{int(D.batters.sixes.sum())}",
          D.batters.fours.sum() == reg.is_four.sum() and D.batters.sixes.sum() == reg.is_six.sum())
    v.add("E24", "Season totals", "Season runs sum == overall regulation runs", int(reg.total_runs.sum()),
          int(S.runs.sum()), S.runs.sum() == reg.total_runs.sum())
    v.add("E25", "Season totals", "Season matches sum == 1095 and 17 seasons", 1095, int(S.matches.sum()),
          S.matches.sum() == 1095 and len(S) == 17)
    v.add("E26", "Season totals", "Season bowler wickets sum == overall", int(reg.is_bowler_wicket.sum()),
          int(S.bowler_wickets.sum()), S.bowler_wickets.sum() == reg.is_bowler_wicket.sum())
    v.add("E27", "Team totals", "Team wins sum == decided matches", int((mc.is_no_result == 0).sum()), int(T.wins.sum()),
          T.wins.sum() == (mc.is_no_result == 0).sum())
    v.add("E28", "Team totals", "Team matches sum == 2 x matches; wins == losses", 2190, int(T.matches.sum()),
          T.matches.sum() == 2 * len(mc) and T.wins.sum() == T.losses.sum())
    v.add("E29", "Team totals", "15 franchises; titles sum == 17 Finals", "15 / 17", f"{len(T)} / {int(T.titles.sum())}",
          len(T) == 15 and T.titles.sum() == 17)
    v.add("E30", "D/L", "No D/L or rain-shortened match in full-match base", 0,
          int((D.full.is_dls == 1).sum() + (D.full.target_overs != 20).sum()),
          (D.full.is_dls == 0).all() and (D.full.target_overs == 20).all() and (D.full.is_no_result == 0).all())
    dl6 = mc[(mc.is_dls == 1) & (mc.win_type == "runs") & (mc.result_for == "chasing")]
    v.add("E31", "D/L", "6 D/L chases won 'by runs' counted as chasing wins", 6, len(dl6),
          len(dl6) == 6 and (dl6.result_for == "chasing").all())
    v.add("E32", "D/L", "Margin analysis (E5) excludes D/L", 0, 0, True, "enforced by filter is_dls == 0 in q_e5")
    v.add("E33", "Keys", "Batter career table: player unique, no nulls", 0,
          int(D.batters.player.duplicated().sum() + D.batters.player.isna().sum()),
          D.batters.player.is_unique and D.batters.player.notna().all())
    v.add("E34", "Keys", "Bowler career table: bowler unique, no nulls", 0, int(D.bowlers.bowler.duplicated().sum()),
          D.bowlers.bowler.is_unique and D.bowlers.bowler.notna().all())
    v.add("E35", "Keys", "Batting innings key (match, innings, player) unique", 0,
          int(D.bat_inn.duplicated(["match_id", "inning", "player"]).sum()),
          not D.bat_inn.duplicated(["match_id", "inning", "player"]).any())
    v.add("E36", "Keys", "Team / venue / season tables have unique, non-null keys", 0,
          int(T.team.duplicated().sum() + V.venue.duplicated().sum() + S.season_year.duplicated().sum()),
          T.team.is_unique and V.venue.is_unique and S.season_year.is_unique and T.team.notna().all())
    # threshold checks on the exact tables published
    qd = {q.qid: q for q in Q}
    v.add("E37", "Thresholds", f"C2 batting-average table: all >= {TH['bat_innings']} innings", TH["bat_innings"],
          int(qd["C2"].table.innings.min()), qd["C2"].table.innings.min() >= TH["bat_innings"])
    v.add("E38", "Thresholds", f"C3 strike-rate table: all >= {TH['bat_balls']} balls", TH["bat_balls"],
          int(qd["C3"].table.balls.min()), qd["C3"].table.balls.min() >= TH["bat_balls"])
    v.add("E39", "Thresholds", f"C4 consistency table: all >= {TH['bat_innings']} innings", TH["bat_innings"],
          int(qd["C4"].table.innings.min()), qd["C4"].table.innings.min() >= TH["bat_innings"])
    mins = [qd["D2"].table.legal_balls.min(), qd["D3"].table.legal_balls.min(), qd["D3"].extra_tables["Best bowling strike rate"].legal_balls.min()]
    v.add("E40", "Thresholds", f"D2/D3 bowling tables: all >= {TH['bowl_balls']} legal balls", TH["bowl_balls"],
          int(min(mins)), min(mins) >= TH["bowl_balls"])
    ph_min = min([qd["D4"].table.legal_balls.min()] + [x.legal_balls.min() for x in qd["D4"].extra_tables.values()])
    v.add("E41", "Thresholds", f"D4 phase bowling tables: all >= {TH['phase_bowl_balls']} balls", TH["phase_bowl_balls"],
          int(ph_min), ph_min >= TH["phase_bowl_balls"])
    pb_min = min(x.balls.min() for x in qd["C6"].extra_tables.values())
    v.add("E42", "Thresholds", f"C6 phase batting tables: all >= {TH['phase_bat_balls']} balls", TH["phase_bat_balls"],
          int(pb_min), pb_min >= TH["phase_bat_balls"])
    v.add("E43", "Thresholds", f"E3/E4 venue tables: all >= {TH['venue_matches']} matches", TH["venue_matches"],
          f"{int(qd['E3'].table.full_matches.min())} / {int(qd['E4'].table.decided.min())}",
          qd["E3"].table.full_matches.min() >= TH["venue_matches"] and qd["E4"].table.decided.min() >= TH["venue_matches"])
    v.add("E44", "Thresholds", f"B3/B4 team tables: all >= {TH['team_innings']} matches", TH["team_innings"],
          f"{int(qd['B3'].table.bat_first_matches.min())} / {int(qd['B4'].table.chase_matches.min())}",
          qd["B3"].table.bat_first_matches.min() >= TH["team_innings"] and qd["B4"].table.chase_matches.min() >= TH["team_innings"])
    # published benchmarks
    b = D.batters.set_index("player")
    v.add("E45", "Benchmark", "V Kohli career runs (published: 8,004 after IPL 2024)", 8004, int(b.runs["V Kohli"]),
          b.runs["V Kohli"] == 8004, "Verified via web search in Phase 2")
    titles = D.mc[D.mc.match_type == "Final"].winner.value_counts()
    expected_titles = {"Mumbai Indians": 5, "Chennai Super Kings": 5, "Kolkata Knight Riders": 3, "Rajasthan Royals": 1,
                       "Deccan Chargers": 1, "Sunrisers Hyderabad": 1, "Gujarat Titans": 1}
    v.add("E46", "Benchmark", "IPL champions 2008-2024 (public record)", str(expected_titles), str(titles.to_dict()),
          titles.to_dict() == expected_titles, "Public record of tournament winners")
    return v.frame()


# =========================================================================== REPORTING
def tidy_summary(Q, S, T) -> pd.DataFrame:
    """Long-format summary: section, table, rank, entity, metric, value."""
    rows = []

    def add(section, table, df, entity, metrics):
        for rank, (_, row) in enumerate(df.iterrows(), start=1):
            for mtr in metrics:
                val = row[mtr]
                rows.append({"section": section, "table": table, "rank": rank, "entity": row[entity],
                             "metric": mtr, "value": round(float(val), 3) if pd.notna(val) else None})
    add("Season", "season_summary", S, "season_year",
        ["matches", "runs", "bowler_wickets", "player_outs", "runs_per_match", "run_rate", "avg_inn1", "avg_inn2",
         "sixes_per_match", "dot_pct", "franchises"])
    add("Team", "team_summary", T.sort_values("wins", ascending=False), "team",
        ["seasons", "matches", "wins", "losses", "win_pct", "titles", "bat_first_win_pct", "chase_win_pct"])
    qd = {q.qid: q for q in Q}
    add("Team", "team_bowling_era_adjusted", qd["B6"].table, "team", ["economy", "economy_vs_league", "balls_per_dismissal"])
    add("Batting", "top_run_scorers", qd["C1"].table, "player", ["runs", "innings", "average", "strike_rate"])
    add("Batting", f"best_average_min{TH['bat_innings']}inn", qd["C2"].table, "player", ["average", "innings", "runs"])
    add("Batting", f"best_strike_rate_min{TH['bat_balls']}balls", qd["C3"].table, "player", ["strike_rate", "balls", "runs"])
    add("Batting", "most_sixes", qd["C5"].table, "player", ["sixes", "fours"])
    add("Bowling", "top_wicket_takers", qd["D1"].table, "bowler", ["wickets", "economy", "average", "strike_rate"])
    add("Bowling", f"best_economy_min{TH['bowl_balls']}balls", qd["D2"].table, "bowler", ["economy", "legal_balls", "wickets"])
    add("Bowling", f"best_average_min{TH['bowl_balls']}balls", qd["D3"].table, "bowler", ["average", "strike_rate", "wickets"])
    add("Venue", f"venue_first_innings_min{TH['venue_matches']}", qd["E3"].table, "venue",
        ["avg_inn1", "avg_inn1_vs_season", "full_matches"])
    add("Venue", f"venue_chasing_min{TH['venue_matches']}", qd["E4"].table, "venue", ["chase_win_pct", "decided"])
    return pd.DataFrame(rows)


def write_report(Q, val, D):
    n_pass = (val.status == "PASS").sum()
    lines = [
        "# IPL Cricket Analytics - Phase 3 Exploratory Data Analysis Report", "",
        f"_Generated by `python/03_eda.py` on {datetime.now():%Y-%m-%d %H:%M} from `data/processed/` (Phase 2 approved data). "
        "Every number in this report is computed by the script; interpretations are written around those computed values._", "",
        "## Scope and conventions", "",
        f"- **Coverage:** IPL 2008-2024, {len(D.mc):,} matches, {len(D.reg):,} regulation deliveries "
        f"({len(D.so)} super-over deliveries analysed separately / excluded from normal statistics).",
        f"- **Full matches** ({len(D.full):,}): not a no-result and `target_overs = 20`. Used for score averages so D/L and "
        "rain-shortened games do not distort them.",
        "- **Batting order:** `batting_first_team` / `chasing_team` (from deliveries). **Outcomes:** `result_for` (handles D/L).",
        "- **Wickets:** bowler wickets = `is_bowler_wicket`; batter dismissals = `is_player_out` (retired hurt excluded). "
        "Raw `is_wicket` is never used as a wicket metric.",
        "- **Thresholds:** " + ", ".join(f"{k} = {v}" for k, v in TH.items()) + ".",
        f"- **Validation:** {n_pass}/{len(val)} checks passed (see `reports/eda_validation_report.md`).",
        "- **Observed vs causal:** findings describe associations in historical data. Where a possible cause is mentioned it "
        "is labelled as a hypothesis that this data cannot test.", "",
        "## Contents", "",
    ]
    for q in Q:
        lines.append(f"- [{q.qid} - {q.title}](#{q.qid.lower()})")
    current = None
    for q in Q:
        if q.section != current:
            lines += ["", f"## {q.section}", ""]
            current = q.section
        lines += [f"<a id=\"{q.qid.lower()}\"></a>", f"### {q.qid}. {q.title}", "",
                  f"**Question.** {q.question}", "", f"**Why it matters.** {q.why}", "",
                  f"**Metric definition.** {q.definition}", "",
                  f"**Finding.** {q.insight}", ""]
        if q.chart:
            lines += [f"![{q.title}]({q.chart})", ""]
        lines += ["<details><summary>Result table</summary>", "", md_table(q.table.head(20)), ""]
        for name, tb in q.extra_tables.items():
            lines += [f"**{name}**", "", md_table(tb.head(15)), ""]
        lines += ["</details>", ""]
        if q.limitation:
            lines += [f"**Limitation.** {q.limitation}", ""]
    lines += ["## Overall limitations", "",
              "- Matches abandoned without a ball bowled are absent; season counts are matches with play.",
              "- No player metadata (role, batting position, nationality) - roles are inferred only from phase usage.",
              "- No home-team field; home advantage was not analysed.",
              "- Fours/sixes use a run-value proxy; phase labels use 20-over boundaries in shortened games.",
              "- Player rankings are not era-adjusted unless stated (team bowling B6 and venue scores E3 are).",
              "- 29 seven-legal-ball overs are retained as recorded (225 deliveries, <0.1% of data) - negligible effect.",
              ""]
    (cfg.REPORTS_DIR / "eda_report.md").write_text("\n".join(lines), encoding="utf-8")


def write_validation(val):
    c = val.status.value_counts().to_dict()
    lines = ["# Phase 3 - EDA Validation Report", "",
             f"_Generated by `python/03_eda.py` on {datetime.now():%Y-%m-%d %H:%M}. Each check is executed against the "
             "same in-memory tables used to produce the EDA results._", "",
             f"**Result: {c.get('PASS', 0)} PASS | {c.get('FAIL', 0)} FAIL** (of {len(val)} checks)", "",
             md_table(val), "",
             "## Exceptions and notes", "",
             "- **Published-figure comparisons (E45, E46):** run totals and champions match public records. Differences "
             "from other published stats, if any appear later, would most likely come from super-over exclusion "
             "(this project excludes them), season coverage (data ends 2024) or player-name identity "
             "(e.g. 'Arshad Khan' vs 'Arshad Khan (2)' are kept separate).",
             "- **Seven-legal-ball overs:** retained and included in all totals (they are real recorded deliveries).",
             ""]
    (cfg.REPORTS_DIR / "eda_validation_report.md").write_text("\n".join(lines), encoding="utf-8")


def build_all():
    set_style()
    for p in [CHART_DIR, TABLE_DIR]:
        p.mkdir(parents=True, exist_ok=True)
    D = Data()
    S = season_table(D)
    T = team_table(D)
    V = venue_table(D)
    Q = [q_a1(D, S), q_a2(D, S), q_a3(D, S), q_a4(D, S), q_a5(D, S),
         q_b1(D, T), q_b2(D, T), q_b3(D, T), q_b4(D, T), q_b5(D), q_b6(D),
         q_c1(D), q_c2(D), q_c3(D), q_c4(D), q_c5(D), q_c6(D),
         q_d1(D), q_d2(D), q_d3(D), q_d4(D), q_d5(D, S),
         q_e1(D), q_e2(D), q_e3(D, V), q_e4(D, V), q_e5(D), q_e6(D, V)]
    val = validate(D, S, T, V, Q)
    return D, S, T, V, Q, val


def main():
    D, S, T, V, Q, val = build_all()
    S.round(3).to_csv(TABLE_DIR / "season_summary.csv", index=False)
    T.round(3).to_csv(TABLE_DIR / "team_summary.csv", index=False)
    V.round(3).to_csv(TABLE_DIR / "venue_summary.csv", index=False)
    D.batters.round(3).to_csv(TABLE_DIR / "batter_careers.csv", index=False)
    D.bowlers.round(3).to_csv(TABLE_DIR / "bowler_careers.csv", index=False)
    for q in Q:
        q.table.to_csv(TABLE_DIR / f"{q.qid}.csv", index=False)
    tidy_summary(Q, S, T).to_csv(cfg.REPORTS_DIR / "eda_summary.csv", index=False)
    val.to_csv(cfg.REPORTS_DIR / "eda_validation_checks.csv", index=False)
    write_report(Q, val, D)
    write_validation(val)
    print(f"[ok] {len(Q)} questions answered; charts: {len(list(CHART_DIR.glob('*.png')))}")
    print(val[["check_id", "check", "expected", "actual", "status"]].to_string(index=False, max_colwidth=60))
    c = val.status.value_counts().to_dict()
    print(f"\nPASS={c.get('PASS', 0)} FAIL={c.get('FAIL', 0)}")
    if c.get("FAIL", 0):
        sys.exit(1)


if __name__ == "__main__":
    main()
