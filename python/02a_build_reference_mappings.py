"""
Phase 2a - Build reference mapping tables (franchise, venue, city)
==================================================================

Creates the reviewed lookup tables that the cleaning script (02b) applies.
Mappings live here, in one place, so every change is visible and auditable.

Outputs
-------
data/reference/franchise_mapping.csv
data/reference/venue_mapping.csv

Run from the project root:
    python python/02a_build_reference_mappings.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ipl_config as cfg  # noqa: E402

# --------------------------------------------------------------------------- #
# 1. FRANCHISE MAPPING
#    approved = merge decision signed off by project owner (Phase 2 brief)
# --------------------------------------------------------------------------- #
FRANCHISE_RULES = {
    # original name                  : (standard franchise,            type,               decision status)
    "Delhi Daredevils":               ("Delhi Capitals",               "historical rename", "APPROVED"),
    "Kings XI Punjab":                ("Punjab Kings",                 "historical rename", "APPROVED"),
    "Royal Challengers Bangalore":    ("Royal Challengers Bengaluru",  "historical rename", "APPROVED"),
    "Rising Pune Supergiant":         ("Rising Pune Supergiants",      "spelling variant",  "APPROVED"),
}
APPROVAL_DATE = "2026-11-08"
FRANCHISE_NOTES = {
    "Delhi Daredevils": "Same franchise renamed Delhi Capitals from IPL 2019 (data: DD 2008-2018, DC 2019-2024).",
    "Kings XI Punjab": "Same franchise renamed Punjab Kings from IPL 2021 (data: KXIP 2008-2020, PBKS 2021-2024).",
    "Royal Challengers Bangalore": "Same franchise; 'Bengaluru' spelling adopted for IPL 2024 (data: 2008-2023 vs 2024).",
    "Rising Pune Supergiant": "2017 spelling of the 2016-17 Pune franchise; merged into owner-chosen standard 'Rising Pune Supergiants'.",
    "Rising Pune Supergiants": "2016 spelling; chosen by owner as the standard name for the 2016-17 Pune franchise.",
    "Deccan Chargers": "Separate franchise (terminated 2012). Deliberately NOT merged with Sunrisers Hyderabad.",
    "Sunrisers Hyderabad": "Separate franchise from 2013. Deliberately NOT merged with Deccan Chargers.",
    "Gujarat Lions": "Two-season franchise 2016-17. Deliberately NOT merged with Gujarat Titans.",
    "Gujarat Titans": "New franchise from 2022. Deliberately NOT merged with Gujarat Lions.",
}

TEAM_SHORT = {
    "Chennai Super Kings": "CSK", "Deccan Chargers": "DC-08", "Delhi Capitals": "DC",
    "Gujarat Lions": "GL", "Gujarat Titans": "GT", "Kochi Tuskers Kerala": "KTK",
    "Kolkata Knight Riders": "KKR", "Lucknow Super Giants": "LSG", "Mumbai Indians": "MI",
    "Pune Warriors": "PWI", "Punjab Kings": "PBKS", "Rajasthan Royals": "RR",
    "Rising Pune Supergiants": "RPS",
    "Royal Challengers Bengaluru": "RCB", "Sunrisers Hyderabad": "SRH",
}


def build_franchise_mapping(m: pd.DataFrame) -> pd.DataFrame:
    yr = pd.to_datetime(m["date"]).dt.year
    long = pd.concat([pd.DataFrame({"team": m.team1, "y": yr, "id": m.id}),
                      pd.DataFrame({"team": m.team2, "y": yr, "id": m.id})])
    g = long.groupby("team").agg(first_year=("y", "min"), last_year=("y", "max"),
                                 matches=("id", "nunique")).reset_index()
    rows = []
    for _, r in g.iterrows():
        std, mtype, status = FRANCHISE_RULES.get(r.team, (r.team, "unchanged", "NO CHANGE"))
        rows.append({
            "team_original": r.team,
            "franchise": std,
            "franchise_short": TEAM_SHORT[std],
            "mapping_type": mtype,
            "decision_status": f"{status} {APPROVAL_DATE}" if status == "APPROVED" else status,
            "first_year": r.first_year, "last_year": r.last_year, "matches": r.matches,
            "note": FRANCHISE_NOTES.get(r.team, ""),
        })
    return pd.DataFrame(rows).sort_values(["franchise", "first_year"]).reset_index(drop=True)


# --------------------------------------------------------------------------- #
# 2. VENUE MAPPING
#    Each original string -> (standard venue, mapping type, reason, verification, source)
# --------------------------------------------------------------------------- #
SRC = {
    "data": "Internal: same base name, same city in raw data, non-overlapping/consistent usage",
    "kotla": "DDCA renamed Feroz Shah Kotla to Arun Jaitley Stadium, 12-Sep-2019 (The Week; Scroll.in; Wikipedia 'Arun_Jaitley_Cricket_Stadium')",
    "motera": "Motera/Sardar Patel Stadium renamed Narendra Modi Stadium on 24-Feb-2021 (Al Jazeera; The Week; Scroll.in)",
    "bindra": "PCA Stadium Mohali named after I.S. Bindra in April 2015 (Business Standard/PTI 12-Apr-2015; Wikipedia 'I._S._Bindra_Stadium')",
    "sahara": "MCA Stadium, Gahunje carried Sahara naming rights (Subrata Roy Sahara Stadium) and reverted to MCA name (Wikipedia 'Maharashtra_Cricket_Association_Stadium'); raw data uses both names for Pune games in 2013",
    "zayed": "'Zayed Cricket Stadium' and 'Sheikh Zayed Cricket Stadium' are two names in use for the same Abu Dhabi ground; no formal rename found (Wikipedia redirect; Khaleej Times)",
}

V = {}  # original -> (standard, type, reason, status, source_key)


def _add(original, standard, mtype, reason, status="VERIFIED", src="data"):
    V[original] = (standard, mtype, reason, status, src)


# --- city/locality suffix or punctuation variants (safe: same base name, same city in data)
for orig, std in [
    ("Arun Jaitley Stadium, Delhi", "Arun Jaitley Stadium"),
    ("Barsapara Cricket Stadium, Guwahati", "Barsapara Cricket Stadium"),
    ("Bharat Ratna Shri Atal Bihari Vajpayee Ekana Cricket Stadium, Lucknow", "Bharat Ratna Shri Atal Bihari Vajpayee Ekana Cricket Stadium"),
    ("Brabourne Stadium, Mumbai", "Brabourne Stadium"),
    ("Dr DY Patil Sports Academy, Mumbai", "Dr DY Patil Sports Academy"),
    ("Dr. Y.S. Rajasekhara Reddy ACA-VDCA Cricket Stadium, Visakhapatnam", "Dr. Y.S. Rajasekhara Reddy ACA-VDCA Cricket Stadium"),
    ("Eden Gardens, Kolkata", "Eden Gardens"),
    ("Himachal Pradesh Cricket Association Stadium, Dharamsala", "Himachal Pradesh Cricket Association Stadium"),
    ("M Chinnaswamy Stadium, Bengaluru", "M Chinnaswamy Stadium"),
    ("MA Chidambaram Stadium, Chepauk", "MA Chidambaram Stadium"),
    ("MA Chidambaram Stadium, Chepauk, Chennai", "MA Chidambaram Stadium"),
    ("Maharaja Yadavindra Singh International Cricket Stadium, Mullanpur", "Maharaja Yadavindra Singh International Cricket Stadium"),
    ("Maharashtra Cricket Association Stadium, Pune", "Maharashtra Cricket Association Stadium"),
    ("Narendra Modi Stadium, Ahmedabad", "Narendra Modi Stadium"),
    ("Punjab Cricket Association IS Bindra Stadium, Mohali", "Punjab Cricket Association IS Bindra Stadium"),
    ("Punjab Cricket Association IS Bindra Stadium, Mohali, Chandigarh", "Punjab Cricket Association IS Bindra Stadium"),
    ("Rajiv Gandhi International Stadium, Uppal", "Rajiv Gandhi International Stadium"),
    ("Rajiv Gandhi International Stadium, Uppal, Hyderabad", "Rajiv Gandhi International Stadium"),
    ("Sawai Mansingh Stadium, Jaipur", "Sawai Mansingh Stadium"),
    ("Vidarbha Cricket Association Stadium, Jamtha", "Vidarbha Cricket Association Stadium"),
    ("Wankhede Stadium, Mumbai", "Wankhede Stadium"),
]:
    _add(orig, std, "city/locality suffix removed",
         "Trailing city or locality suffix only; base name identical and city identical in raw data.")
_add("M.Chinnaswamy Stadium", "M Chinnaswamy Stadium", "punctuation variant",
     "'M.' vs 'M ' punctuation only; same city (Bangalore/Bengaluru).")

# --- historical renames / alternate names (verified with external sources)
_add("Feroz Shah Kotla", "Arun Jaitley Stadium", "historical rename",
     "Same Delhi ground renamed in 2019. Raw data already uses the new name for 2018 matches too.", src="kotla")
_add("Sardar Patel Stadium, Motera", "Narendra Modi Stadium", "historical rename",
     "Same Motera (Ahmedabad) site renamed in 2021. NOTE: stadium was demolished and rebuilt 2015-2020; same site, rebuilt venue.",
     src="motera")
_add("Punjab Cricket Association Stadium, Mohali", "Punjab Cricket Association IS Bindra Stadium", "historical rename",
     "Same Mohali ground renamed after I.S. Bindra in 2015 (data: old name 2008-2015, new name 2016+).", src="bindra")
_add("Punjab Cricket Association IS Bindra Stadium", "Punjab Cricket Association IS Bindra Stadium", "unchanged",
     "Already standard name.")
_add("Subrata Roy Sahara Stadium", "Maharashtra Cricket Association Stadium", "sponsorship name",
     "Sahara naming-rights name of the MCA Stadium, Gahunje (Pune). Used for 2012-13 Pune Warriors home games.", src="sahara")
_add("Zayed Cricket Stadium, Abu Dhabi", "Sheikh Zayed Stadium", "alternate name",
     "Alternate name of the same Abu Dhabi ground (only IPL venue in Abu Dhabi). Not a formal rename.",
     status="VERIFIED (same ground; naming inconsistent, not a formal rename)", src="zayed")

# Explicit "do NOT merge" notes for look-alikes
DO_NOT_MERGE = {
    "Maharaja Yadavindra Singh International Cricket Stadium, Mullanpur":
        "NEW ground opened 2024 in Mullanpur; NOT the PCA IS Bindra Stadium although both serve Punjab Kings.",
    "Brabourne Stadium": "Different Mumbai ground from Wankhede Stadium and DY Patil Sports Academy.",
    "Dr DY Patil Sports Academy": "Different ground from Wankhede/Brabourne (located in Navi Mumbai).",
    "Nehru Stadium": "Kochi ground (Kochi Tuskers Kerala 2011). Unrelated to any Pune stadium.",
}

# City standardisation: applied per STANDARD venue. Only used where raw data is
# missing or inconsistent for the same ground; otherwise city kept as recorded.
CITY_BY_STD_VENUE = {
    "Dubai International Cricket Stadium": ("Dubai", "Filled missing: same venue recorded with city 'Dubai' in 13 other matches (2021)"),
    "Sharjah Cricket Stadium": ("Sharjah", "Filled missing: same venue recorded with city 'Sharjah' in 10 other matches (2021)"),
    "M Chinnaswamy Stadium": ("Bengaluru", "Unify 'Bangalore'/'Bengaluru' for the same ground to the current official spelling"),
    "Dr DY Patil Sports Academy": ("Navi Mumbai", "Unify 'Mumbai'/'Navi Mumbai' for same ground; stadium is in Nerul, Navi Mumbai"),
}


def build_venue_mapping(m: pd.DataFrame) -> pd.DataFrame:
    yr = pd.to_datetime(m["date"]).dt.year
    g = (m.assign(y=yr).groupby("venue")
           .agg(matches=("id", "size"), first_year=("y", "min"), last_year=("y", "max"),
                city_values_raw=("city", lambda s: ", ".join(sorted(s.fillna("<missing>").unique()))))
           .reset_index())
    rows = []
    for _, r in g.iterrows():
        std, mtype, reason, status, src = V.get(
            r.venue, (r.venue, "unchanged", "Single spelling in raw data; already standard.", "NO CHANGE", "data"))
        rows.append({
            "venue_original": r.venue, "venue_standardized": std, "mapping_type": mtype,
            "reason": reason, "verification_status": status, "verification_source": SRC[src],
            "do_not_merge_note": DO_NOT_MERGE.get(r.venue, ""),
            "city_values_raw": r.city_values_raw,
            "matches": r.matches, "first_year": r.first_year, "last_year": r.last_year,
        })
    vm = pd.DataFrame(rows)

    # standardized city per standard venue
    city_raw = (m.assign(vs=m.venue.map(vm.set_index("venue_original").venue_standardized))
                  .dropna(subset=["city"]).groupby("vs").city.agg(lambda s: sorted(s.unique())))
    def city_std(vs):
        if vs in CITY_BY_STD_VENUE:
            return CITY_BY_STD_VENUE[vs]
        vals = city_raw.get(vs, [])
        if len(vals) == 1:
            return vals[0], "As recorded (single consistent value in raw data)"
        raise ValueError(f"Unresolved city for venue {vs}: {vals}")
    vm[["city_standardized", "city_rule"]] = vm.venue_standardized.apply(lambda v: pd.Series(city_std(v)))
    vm["owner_approval"] = f"APPROVED {APPROVAL_DATE}"
    vm.loc[vm.mapping_type == "unchanged", "owner_approval"] = "N/A (name unchanged)"
    city_changed = vm.venue_standardized.isin(CITY_BY_STD_VENUE)
    vm.loc[city_changed & (vm.mapping_type == "unchanged"), "owner_approval"] = f"APPROVED {APPROVAL_DATE} (city rule)"
    return vm.sort_values(["venue_standardized", "venue_original"]).reset_index(drop=True)


def main():
    cfg.REFERENCE_DIR.mkdir(parents=True, exist_ok=True)
    m = pd.read_csv(cfg.RAW_MATCHES)

    fm = build_franchise_mapping(m)
    vm = build_venue_mapping(m)

    # --- validation of mapping completeness
    teams = set(m.team1) | set(m.team2)
    assert set(fm.team_original) == teams, "franchise mapping does not cover every raw team"
    assert set(vm.venue_original) == set(m.venue), "venue mapping does not cover every raw venue"
    unused = set(V) - set(m.venue)
    assert not unused, f"mapping rules reference venues not in data: {unused}"
    # each standard venue must resolve to exactly one standardized city
    assert vm.groupby("venue_standardized").city_standardized.nunique().max() == 1

    fm.to_csv(cfg.REFERENCE_DIR / "franchise_mapping.csv", index=False)
    vm.to_csv(cfg.REFERENCE_DIR / "venue_mapping.csv", index=False)
    print(f"[ok] franchise_mapping.csv : {len(fm)} raw names -> {fm.franchise.nunique()} franchises")
    print(f"[ok] venue_mapping.csv     : {len(vm)} raw venues -> {vm.venue_standardized.nunique()} grounds")
    print(vm.mapping_type.value_counts().to_string())


if __name__ == "__main__":
    main()
