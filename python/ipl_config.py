"""
Central configuration for the IPL Cricket Analytics project.

All scripts import paths from here so the folder layout is defined in one place.
"""
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

DATA_DIR = PROJECT_ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
PROCESSED_DIR = DATA_DIR / "processed"
FINAL_DIR = DATA_DIR / "final"
REFERENCE_DIR = DATA_DIR / "reference"

REPORTS_DIR = PROJECT_ROOT / "reports"
PROFILING_DIR = REPORTS_DIR / "profiling"
VALIDATION_DIR = REPORTS_DIR / "validation"
INSIGHTS_DIR = REPORTS_DIR / "insights"

DOCS_DIR = PROJECT_ROOT / "documentation"

RAW_MATCHES = RAW_DIR / "matches.csv"
RAW_DELIVERIES = RAW_DIR / "deliveries.csv"

# SHA-256 of the raw files as received from Kaggle (recorded 2026-11-08).
# Any script reading raw data verifies these so the source can never drift silently.
RAW_SHA256 = {
    "matches.csv": "8a0394246d2a76b44526565f2245d8f4feff91babe57ab16676a2c3d67aa0846",
    "deliveries.csv": "142236ea52950795dab266d4aa392c7645bd1a0db4704f0b8058afd96e24e2c2",
}

# Extras that do NOT count as a legal delivery (ball must be re-bowled).
ILLEGAL_DELIVERY_EXTRAS = {"wides", "noballs"}

# Dismissal kinds that are NOT credited to the bowler.
NON_BOWLER_DISMISSALS = {
    "run out", "retired hurt", "retired out", "obstructing the field",
}
# Dismissal kinds that do NOT end a batter's innings for batting-average purposes.
NOT_OUT_DISMISSALS = {"retired hurt"}
# Dismissal kinds credited to the bowler (the complement of the above, listed explicitly).
BOWLER_WICKET_KINDS = {
    "bowled", "caught", "caught and bowled", "lbw", "stumped", "hit wicket",
}

# Match phases by 1-based over number (standard T20 convention for a 20-over innings).
PHASES = [  # (name, first_over, last_over)
    ("Powerplay", 1, 6),
    ("Middle", 7, 15),
    ("Death", 16, 20),
]

FRANCHISE_MAPPING_CSV = REFERENCE_DIR / "franchise_mapping.csv"
VENUE_MAPPING_CSV = REFERENCE_DIR / "venue_mapping.csv"

CLEAN_MATCHES = PROCESSED_DIR / "matches_clean.csv"
CLEAN_DELIVERIES = PROCESSED_DIR / "deliveries_clean.csv"
