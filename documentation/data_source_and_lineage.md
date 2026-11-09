# Data Source, Coverage, Lineage & Limitations

## 1. Source

| Item | Value |
|---|---|
| Origin | Kaggle download supplied by the project owner (two CSVs: `matches.csv`, `deliveries.csv`) |
| Likely Kaggle dataset | *"IPL Complete Dataset (2008-2024)"*. **Inferred from the schema, not confirmed.** The owner should add the exact Kaggle URL and licence here. |
| Likely upstream source | Cricsheet ball-by-ball data. **Inferred:** match IDs are ESPNcricinfo IDs and player names use Cricsheet-style initials (e.g. `V Kohli`, `Arshad Khan (2)`). |
| Received | 2026-11-08 |
| Integrity | SHA-256 recorded in `python/ipl_config.py`. Every script checks the hashes before reading. |

| File | Bytes | SHA-256 |
|---|---|---|
| matches.csv | 225,266 | `8a0394246d2a76b44526565f2245d8f4feff91babe57ab16676a2c3d67aa0846` |
| deliveries.csv | 27,019,953 | `142236ea52950795dab266d4aa392c7645bd1a0db4704f0b8058afd96e24e2c2` |

## 2. Coverage (computed from the data)

- **17 seasons: IPL 2008 – IPL 2024.** First match 2008-04-18, last match 2024-05-26 (the 2024 final).
- **1,095 matches**, every one with ball-by-ball data. **260,920 deliveries** (260,759 in regulation innings and 161 in super overs).
- **347,470 runs** in regulation innings. **251,319 legal deliveries.**
- **15 franchises** under **19 name strings**. **58 venue strings.** **741 distinct people.** **70 umpires.**
- Overseas seasons are visible in the data: 2009 was played entirely in South Africa (8 SA cities). Part of 2014 and all of 2020 were played in the UAE (2020 used only 3 venues: Abu Dhabi, Dubai and Sharjah).

Per-season details: `reports/profiling/season_coverage.csv`.

## 3. Lineage

```
data/raw/*.csv            (read-only; never modified; hash-verified)
    │  python/01_data_profiling.py         → reports/profiling/*, reports/validation/phase1_*
    │  python/02_... (Phase 2 cleaning)    → data/processed/*
    │  python/03_... (feature engineering) → data/final/*
    ▼
MySQL (Phase 4) ── Power BI (Phase 6)
```

Every output file will be produced by a script in `python/` or `sql/`. Nothing is edited by hand.

## 4. Limitations (known at the end of Phase 1)

| # | Limitation | Impact |
|---|---|---|
| L1 | **Matches abandoned without a ball being bowled appear to be absent.** Every match in the file has deliveries. Several seasons have fewer matches than the usual schedule (e.g. 2024 has 71; 2008 has 58). The schedule sizes are general knowledge and are not in this data. | Season match counts are "matches with play", not "matches scheduled". Points-table reconstruction is not possible. |
| L2 | Data ends at IPL 2024. | No 2025 or later seasons. |
| L3 | No player metadata (role, batting hand, bowling style, nationality, age, squad/auction). | Cannot analyse overseas vs Indian players or bowling types, and cannot assign a player's team for seasons they didn't play. |
| L4 | No home-team field. | "Home advantage" has to be approximated by mapping franchises to home cities. That mapping is an assumption, and neutral seasons (2009, 2020, part of 2014) need to be left out. |
| L5 | **One `extras_type` per ball.** A no-ball that also gave byes or leg-byes is recorded only as `noballs`, with all extras combined in `extra_runs`. | Bowler runs conceded on such balls may be slightly overstated, because byes off a no-ball should not count against the bowler. The effect is small: 1,069 no-ball rows in total. |
| L6 | 29 overs have **7 legal deliveries** recorded. | Probably umpire miscounts that really happened, or scoring errors. They will be kept as recorded and documented, because "fixing" them would mean making up data. |
| L7 | Player names are short forms with initials; there is no player ID. | Two different players could share a name. The source already separates one such pair (`Arshad Khan` / `Arshad Khan (2)`), and that split must be kept. |
| L8 | Franchise renames (e.g. Delhi Daredevils → Delhi Capitals) and changes of ownership (Deccan Chargers vs Sunrisers Hyderabad) are not marked. | A franchise-mapping decision is needed in Phase 2 (see the project log). |
| L9 | DLS matches (21) have revised targets and shortened chases. | Comparisons of "average first-innings score" and chases should keep or remove them deliberately. |
