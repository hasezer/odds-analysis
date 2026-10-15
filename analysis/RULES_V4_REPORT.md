# Rule hunt v4: where does Nesine's pricing slip, every season? (money scans)

Data: our own Nesine/Mackolik collection only. Every priced bet type (~160) at closing odds.
Seasons: 2024/25 + 2024, 2025/26 + 2025, 2026/27 + 2026 so far.

## Method
Each bet type was split into cells along ten dimensions:
- its own odds band (10 bands);
- Nesine's cut on that market in that match (5 bands);
- league;
- weekday, kick-off hour, month, season stage;
- days of rest of the home and of the away team;
- league × odds tercile.

A cell is kept when it made money in **all three seasons** (at least 60 bets in each of the first two and 15 in 2026/27) and its return z-score over all seasons is 2 or more.

Luck control: 20 runs per dimension with the labels shuffled across matches within each season.

## Result

| Dimension | Real cells kept | Shuffled (average / most) |
|---|---|---|
| league | 2 (the same Portugal bet listed twice) | 0 / 0 |
| league × odds | 3 | 0.15 / 1 |
| all other dimensions | 0 | 0 / 0 |

- **Portugal, draw with 3+ goals:** confirmed again and sharpened. It is strongest when its odds are above 13.95: +39 / +45 / +173 per 100 staked.
  - In Portugal the plain 1-1 loses heavily (−37 / −61 / −59), while 2-2 and 3-3 pay.
  - So Portugal's draws are unusually high-scoring, and the price does not follow.
- **La Liga, "under 2.5 & both score" (a 1-1) at odds 5.61–6.48:** made money in every season, but the whole market loses in La Liga (−10 / −3 / −9). Kept on the watch list only.
- **No money in** weekday, kick-off hour, month, season stage, rest days, Nesine's cut, or odds band on its own.

Both leads are in the strategy book (kind `league_rule`). The tracker follows them on new matches.

Code: `rules_v4.py`. Rebuild with `python analysis/rules_v4.py`, then `python analysis/build_strategy_book.py`.
