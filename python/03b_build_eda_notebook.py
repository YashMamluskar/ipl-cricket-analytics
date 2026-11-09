"""Builds notebooks/03_exploratory_data_analysis.ipynb from the question registry in python/03_eda.py,
so the notebook and the script can never disagree."""
import sys
from importlib import import_module
from pathlib import Path

import nbformat as nbf

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / "python"))
eda = import_module("03_eda")
_, _, _, _, Q, _ = eda.build_all()  # only to read the question list (ids, sections, titles)

md, code = nbf.v4.new_markdown_cell, nbf.v4.new_code_cell
cells = [
    md("""# 03 · Exploratory Data Analysis (Phase 3)

**Data:** `data/processed/matches_clean.csv` and `deliveries_clean.csv` (Phase 2, validated). Read-only.

All calculations live in `python/03_eda.py` (one function per question) so they are reproducible from the command
line. This notebook runs that module and walks through each question: **question → why it matters → metric
definition → result table → chart → finding → limitation**. Every number shown is computed live.

**Key conventions**
- Super overs excluded from normal statistics (`is_super_over = 0`).
- Batting order from `batting_first_team` / `chasing_team`; outcomes from `result_for` (handles D/L).
- Bowler wickets = `is_bowler_wicket`; batter dismissals = `is_player_out` (retired hurt is not out).
- *Full match* = not a no-result and `target_overs = 20` (used for score averages)."""),
    code("""import sys
from pathlib import Path
from importlib import import_module
import pandas as pd
from IPython.display import Image, Markdown, display

PROJECT_ROOT = Path.cwd().parent if Path.cwd().name == 'notebooks' else Path.cwd()
sys.path.insert(0, str(PROJECT_ROOT / 'python'))
eda = import_module('03_eda')
pd.set_option('display.max_columns', 40); pd.set_option('display.width', 220); pd.set_option('display.max_colwidth', 120)

D, S, T, V, Q, val = eda.build_all()
QD = {q.qid: q for q in Q}
print(f'{len(Q)} questions | {len(D.mc):,} matches | {len(D.reg):,} regulation deliveries | '
      f'validation: {(val.status == "PASS").sum()}/{len(val)} PASS')
print('Thresholds:', eda.TH)

def show(qid):
    q = QD[qid]
    display(Markdown(f"**Question.** {q.question}\\n\\n**Why it matters.** {q.why}\\n\\n**Metric.** {q.definition}"))
    display(q.table.head(15))
    for name, tb in q.extra_tables.items():
        display(Markdown(f'**{name}**')); display(tb.head(10))
    if q.chart:
        display(Image(filename=str(PROJECT_ROOT / 'reports' / q.chart), width=900))
    display(Markdown(f"**Finding.** {q.insight}" + (f"\\n\\n**Limitation.** {q.limitation}" if q.limitation else '')))"""),
    md("## 0 · Validation first\nNo result is reported unless these checks pass."),
    code("""print(val.status.value_counts().to_string())
val[['check_id', 'area', 'check', 'expected', 'actual', 'status']]"""),
]
section = None
for q in Q:
    if q.section != section:
        cells.append(md(f"## {q.section}"))
        section = q.section
    cells.append(md(f"### {q.qid} · {q.title}"))
    cells.append(code(f"show('{q.qid}')"))
cells += [
    md("## Super overs (analysed separately)\nSuper-over deliveries are excluded above; this is a short separate view."),
    code("""so = D.so
summary = pd.DataFrame({'super_over_matches': [D.mc.is_super_over.sum()], 'deliveries': [len(so)],
                        'runs': [so.total_runs.sum()], 'bowler_wickets': [so.is_bowler_wicket.sum()]})
display(summary)
D.team_long[D.team_long.is_super_over == 1].groupby('team').agg(super_overs=('match_id', 'size'), won=('won', 'sum')) \\
    .sort_values('super_overs', ascending=False)"""),
    md("## Outputs\n- `reports/eda_report.md` - full written findings\n- `reports/eda_validation_report.md`\n"
       "- `reports/eda_summary.csv` - tidy summary of key tables\n- `reports/eda_tables/` - every result table\n"
       "- `reports/charts/` - charts (200 dpi PNG)"),
]
nb = nbf.v4.new_notebook()
nb.cells = cells
nb.metadata["kernelspec"] = {"name": "python3", "display_name": "Python 3", "language": "python"}
nbf.write(nb, root / "notebooks" / "03_exploratory_data_analysis.ipynb")
print("written", len(cells), "cells")
