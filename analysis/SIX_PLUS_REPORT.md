# 6+ goals: deep dive

Data: our own collection, 20,667 finished matches across 2024/25, 2025/26 and 2026/27; 1,311 ended with 6+ goals (6.3%).
Tested on later seasons; luck controls throughout.

## What 6+ games look like
- **Kinds:** 75% are **shootouts** (both teams 2+); 25% are one-sided routs.
- **Most common scores:** **3-3** (256 games), 4-2 (212), 5-1 (136), 2-4 (119), 3-4, 4-3.
- **First half:** usually busy, typically 3 goals by half-time.
- **Odds that differ most from other matches** (separation 0.68, the same as the 6+ price itself):
  - 1st-half 0-0 odds high;
  - score 0-0 odds high;
  - "other" correct score cheap;
  - over 4.5 cheap;
  - 0-1 goals odds high.
  All of these measure "how many goals Nesine expects".

## Can anything see 6+ coming better than Nesine's 6+ price? No.
- **All signals** (`six_plus.py`): 555 signals were tested (every market's price and chance, market disagreements, team form, previous match, league, calendar). Among matches with the same 6+ price, none separates 6+ games by more than about 0.02 in the same direction in all three seasons.
- **Structure signals** (`six_plus3.py`): built from Nesine's own markets (both teams 3+, 5+ vs 6+, "other" score, busy first half, high-scoring draw, both halves 2+, 4-5 goals, both teams to score). None holds steadily.
- **Small combined model** (chosen without 2026/27): no better than the 6+ price on 2026/27.
- **Exhaustive 1–2 threshold rules** over 12 key markets (`six_plus4.py`): 5,168 rules raise the 6+ hit rate to 22–25% in every season. Only 1 beats taking the same number of matches with the cheapest 6+ price, and only barely.
- **Teams:** no team keeps producing 6+ beyond its odds (0 teams; shuffled 0.8).

## Where does Nesine misprice 6+?
- **It overstates 6+, almost everywhere** (`six_plus2.py`). For example, at 6+ odds of 4.50–6 Nesine's price implies 15.4%, but 6+ happened in 11.7%.
- **The overstatement is largest** in low-scoring matches with a big favourite.
- **Betting 6+ loses 22–42 per 100 at every odds level.** No band, and no expected-goals × favourite cell, is profitable in every season.

## The 6+ ladder (all seasons)

| 6+ odds | Matches | 6+ happened | Needed to break even |
|---|---|---|---|
| ≤ 4.50 | 469 | 20.3% | 26.2% |
| 4.50–6 | 1,194 | 11.7% | 19.0% |
| 6–7.50 | 1,772 | 10.3% | 14.8% |
| 7.50–9 | 2,280 | 9.6% | 12.2% |
| 9–11 | 2,486 | 7.1% | 10.0% |
| > 20 | 4,945 | 2.2% | 3.7% |

## If you expect a 6+ game, play something else
In the 5% of matches where 6+ is most likely:

| Bet | Hit rate | Return per 100 |
|---|---|---|
| 1st-half over 1.5 | 51% | −16 |
| over 3.5 | 52% | −18 |
| home team 3+ | 42% | −20 |
| over 4.5 | 32% | −22 |
| 6+ itself | 17% | −29 |
| "other" correct score | 8% | −43 |

The 6+ market carries a much bigger cut.

## Bottom line
Nesine's 6+ price is the best 6+ signal we have. Every 6+ rule we or the tipsters found is that price in disguise, and the price is set generously against the bettor.

Best hit-rate tools (stored in `strategies.yaml`):
- the 6+ odds bands (6+ odds ≤ 4.50 → about 20%);
- tipster rules 9b and 11.

If you play the idea "lots of goals", over 3.5 or 1st-half over 1.5 cost far less than 6+.

Files: `output/six_plus.xlsx`, `output/six_plus_ladder.png`.
Code: `six_plus.py`, `six_plus2.py`, `six_plus3.py`, `six_plus4.py`, `six_plus_report.py`.
