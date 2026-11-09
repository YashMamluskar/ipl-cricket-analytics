"""Small shared helpers for Phase 5 (finding record, Wilson interval, chart saving, colour map)."""
from __future__ import annotations

from dataclasses import dataclass, field

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.colors import LinearSegmentedColormap

import ipl_config as cfg

CHART_DIR = cfg.REPORTS_DIR / "charts" / "phase5"
TABLE_DIR = cfg.REPORTS_DIR / "advanced_analytics_tables"


@dataclass
class Finding:
    qid: str
    section: str
    title: str
    question: str
    definition: str
    sample: str
    table: pd.DataFrame
    insight: str
    limitation: str = ""
    chart: str | None = None
    extra: dict = field(default_factory=dict)
    calc_ref: str = ""


def wilson(k, n, z: float = 1.959964):
    """Wilson score interval for a proportion, returned in PERCENT: (point, low, high)."""
    k, n = float(k), float(n)
    if n == 0:
        return np.nan, np.nan, np.nan
    p = k / n
    den = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / den
    half = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    lo, hi = max(0.0, centre - half), min(1.0, centre + half)
    return p * 100, round(lo * 100, 10), round(hi * 100, 10)


def save_fig(fig, name: str) -> str:
    CHART_DIR.mkdir(parents=True, exist_ok=True)
    fig.savefig(CHART_DIR / f"{name}.png", dpi=200, bbox_inches="tight")
    plt.close(fig)
    return f"charts/phase5/{name}.png"


def diverging_cmap():
    """Diverging: orange (below league) -> neutral grey -> blue (above league)."""
    return LinearSegmentedColormap.from_list("div", ["#c9541f", "#eb6834", "#f1f0ec", "#2a78d6", "#1a5aa8"])
