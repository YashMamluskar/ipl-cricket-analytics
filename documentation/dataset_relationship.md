# Dataset Relationship

```
matches (1,095 rows)                       deliveries (260,920 rows)
┌──────────────────────┐                   ┌────────────────────────────────┐
│ PK id                │ 1 ────────── N    │ FK match_id                    │
│ season, date, venue  │                   │ inning, over, ball   ← natural │
│ team1, team2         │                   │   composite key with match_id  │
│ toss_*, winner,      │                   │ batting_team, bowling_team     │
│ result, target_*     │                   │ batter, bowler, non_striker    │
└──────────────────────┘                   │ runs / extras / wicket fields  │
                                           └────────────────────────────────┘
```

**Join:** `matches.id = deliveries.match_id` (one-to-many).

## Verified integrity (Phase 1 checks)

| Check | Result |
|---|---|
| `matches.id` unique | ✅ 1,095 / 1,095 |
| Delivery rows whose `match_id` is missing from matches (orphans) | ✅ 0 |
| Matches with no deliveries | ✅ 0 |
| `(match_id, inning, over, ball)` unique | ✅ 0 duplicates, so it works as the deliveries primary key |
| Delivery `batting_team`/`bowling_team` = the match's team1/team2 pair | ✅ 0 mismatches |
| `super_over = 'Y'` ⇔ the match has deliveries with `inning ≥ 3` | ✅ same 14 matches |
| `target_runs` = innings-1 runs + 1 (non-DLS) | ✅ 1,071 / 1,071 |
| Winner recomputed from delivery runs (decided, non-DLS) | ✅ 1,055 / 1,055 |
| `runs` margin recomputed | ✅ 0 mismatches |
| `wickets` margin = 10 − wickets lost in chase (excluding retired hurt) | ✅ 0 mismatches |
| Toss winner + decision → innings-1 batting team | ✅ 1,095 / 1,095 |

## Rules for analysis

1. **Batting order comes from deliveries (`inning`), not from `team1`.** `team1` bats first in only 72.6% of matches.
2. **Regulation stats use `inning ∈ {1, 2}`.** Super-over balls (inning 3–6, 161 deliveries) decide tied matches but are normally left out of career batting/bowling stats and team totals. This will be a documented Phase 2 flag, not a deletion.
3. **Match-level attributes** (season, venue, toss, winner) reach the deliveries through the join. Deliveries never need to repeat them.
4. **No-result matches** (5) have partial ball-by-ball data (51–130 deliveries). These balls are real and count toward player stats, but the matches must be left out of win/loss and win-percentage denominators.
