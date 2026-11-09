"""Builds notebooks/05_advanced_cricket_analytics.ipynb from the finding registry in
python/05_advanced_analytics.py (so notebook and script cannot drift apart).

    python python/05b_build_advanced_notebook.py
    jupyter nbconvert --to notebook --execute --inplace notebooks/05_advanced_cricket_analytics.ipynb
"""
from pathlib import Path

import nbformat as nbf

root = Path(__file__).resolve().parents[1]
SECTIONS = {
    "A. Batting": ["A1", "A2", "A3", "A4", "A5", "A6", "A7"],
    "B. Bowling": ["B1", "B2", "B3", "B4", "B5", "B6", "B7"],
    "C. Match pressure": ["C1", "C2", "C3", "C4", "C5", "C6", "C7"],
    "D. Team contribution": ["D1", "D2", "D3", "D4", "D5", "D6"],
    "E. Venue & conditions": ["E1", "E2", "E3", "E4"],
    "F. Machine-learning assessment": ["F1"],
}
md, code = nbf.v4.new_markdown_cell, nbf.v4.new_code_cell
cells = [
    md("""# 05 · Advanced Cricket Analytics (Phase 5)

Goes beyond Phase 3 EDA: score distributions and consistency with confidence intervals, **season- and
phase-adjusted** player and team metrics, **chase-state** analysis (runs needed, balls left, wickets in hand at
the end of each over), pressure and close-match analysis, venue tests, and an **assessed** predictive task.

All logic lives in `python/05_advanced_analytics.py`; this notebook executes it and walks through every finding
in the required format: question, metric definition, calculation, sample size, result, interpretation, limitations.

**Rules applied throughout:** regulation balls only (super overs excluded); bowler-credited wickets only;
retired hurt is not out; batting order and outcome from `batting_first_team` / `chasing_team` / `result_for`;
D/L and shortened matches excluded from target-based comparisons; 7-legal-ball overs retained.

> MySQL cross-checks (M01-M04) need `MYSQL_USER` / `MYSQL_PASSWORD` in the environment. If they are missing,
> those checks are reported as FAIL, never skipped silently."""),
    code("""import os, sys
from pathlib import Path
from importlib import import_module
import pandas as pd
from IPython.display import Image, Markdown, display

PROJECT_ROOT = Path.cwd().parent if Path.cwd().name == 'notebooks' else Path.cwd()
sys.path.insert(0, str(PROJECT_ROOT / 'python'))
for k in ('MYSQL_USER', 'MYSQL_PASSWORD'):          # read from the Windows user environment if not inherited
    if not os.environ.get(k) and os.name == 'nt':
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, 'Environment') as key:
                os.environ[k] = winreg.QueryValueEx(key, k)[0]
        except OSError:
            pass
adv = import_module('05_advanced_analytics')
pd.set_option('display.max_columns', 30); pd.set_option('display.width', 220); pd.set_option('display.max_colwidth', 100)

A, F, val = adv.build_all()
FD = {f.qid: f for f in F}
print(f'{len(F)} findings | chase base: {len(A.chase_matches)} matches | chase states: {len(A.states):,} | '
      f'validation: {(val.status == "PASS").sum()}/{len(val)} PASS')
print('Thresholds:', adv.TH)

def show(qid):
    f = FD[qid]
    display(Markdown(f"**1. Question.** {f.question}\\n\\n**2. Metric.** {f.definition}\\n\\n"
                     f"**3. Calculation.** `{f.calc_ref}`\\n\\n**4. Sample.** {f.sample}"))
    display(f.table.head(15))
    for name, t in f.extra.items():
        display(Markdown(f'**{name}**')); display(t.head(12))
    if f.chart:
        display(Image(filename=str(PROJECT_ROOT / 'reports' / f.chart), width=900))
    display(Markdown(f"**6. Interpretation.** {f.insight}\\n\\n**7. Limitations.** {f.limitation}"))"""),
    md("## Validation first"),
    code("val[['check_id', 'area', 'check', 'expected', 'actual', 'status']]"),
]
for sec, ids in SECTIONS.items():
    cells.append(md(f"## {sec}"))
    for q in ids:
        cells.append(md(f"### {q}"))
        cells.append(code(f"show('{q}')"))
cells.append(md("## Outputs\n- `reports/advanced_analytics_report.md`\n- `reports/advanced_analytics_validation_report.md`\n"
                "- `reports/advanced_analytics_summary.csv`\n- `reports/advanced_analytics_tables/`\n- `reports/charts/phase5/`"))
nb = nbf.v4.new_notebook()
nb.cells = cells
nb.metadata["kernelspec"] = {"name": "python3", "display_name": "Python 3", "language": "python"}
nbf.write(nb, root / "notebooks" / "05_advanced_cricket_analytics.ipynb")
print("written", len(cells), "cells")
