# High-odds bets: how to raise the hit rate (all 26 leagues)

Data: our own Nesine/Mackolik collection only, 20,670 matches.
Seasons: 2024/25 + 2024 (find), 2025/26 + 2025 (confirm), 2026/27 + 2026 so far (exam).
Targets: 66 high-odds bets (typical odds 4+) and combined bets, settled from the score so every match counts.
The goal here is hit rate, not beating Nesine's prices.

## 1. The strongest filter is the bet's own odds
- **Method:** rank the matches four ways and bet only the top 1/2/5/10/20%:
  - by Nesine's own odds for the bet;
  - by a goal model fitted to Nesine's main odds;
  - by machine learning on ~400 features (all odds, disagreement, form, last match, league, calendar);
  - by the number of confirmed rules agreeing.
- **Testing:** train on earlier seasons only, test on the next (2025/26 and 2026/27).
- **Result:** across all 66 bets, the bet's own odds pick best, at about **2.8× the normal hit rate for the top 1%, 2.2× for the top 5% and 1.9× for the top 10%**.
  - Machine learning: 1.7–2.2×.
  - Rule counts: 1.8–2.2×.
  - "Odds + corrections" (ML that starts from the odds and only learns adjustments): below the odds on every level.
- **What this means:** the extra information adds noise, not hits.
- Chart `hi_methods.png`; sheet "Best way to pick matches".

**Odds ladder** (chart `hi_odds_ladder.png`, sheet "Odds ladder"): the hit rate by the bet's own odds band, per season. Examples for the cheapest 5% of matches in 2026/27:

| Bet | Hit rate | Normal | Average odds |
|---|---|---|---|
| 6+ goals | 22.5% | 7.6% | 3.9 |
| over 4.5 goals | 39% | 17% | 2.3 |
| HT/FT X/2 | 21% | 10.6% | 4.1 |
| score 2-2 (cheapest 10%) | 10.2% | 5.8% | 9.0 |

The odds fall as the hit rate rises.

## 2. Packs
Back the 1–3 most likely selections of a market together. Optionally, play only the matches where they are most likely (chart `hi_packs.png`). Results for 2026/27:

| Pack | Every match | Top 10% most predictable matches |
|---|---|---|
| 3 correct scores | 30.5% at 2.3 | 37.9% at 2.1 |
| 3 half-time scores | 24% at 3.5 | 34% at 2.7 |
| 2 high-odds HT/FT results | 37% at 2.2 | 57% at 1.5 |

## 3. Readable rules (decision trees)
- **Method:** up to 3 conditions with exact cut-offs, found on 2024/25 and confirmed on 2025/26.
- **Result:**
  - 3,020 rules were kept, against 22 with shuffled results.
  - 91% still raise the hit rate by at least 1.3× in 2026/27.
  - Only 17% beat a plain "cheapest odds" filter of the same size.
- Sheet "Readable rules (trees)".

## 4. League tendencies
- **Result:** 50 league × bet pairs were above normal in both earlier seasons, against 1.0 on average with shuffled leagues (at most 3), and 90% held up in 2026/27.
- Most are already in the odds. A few beat the odds every season:
  - Argentina: low-scoring draws.
  - MLS: away team scores 3+.
  - Ligue 1: half-time away lead with both teams scoring.
- Portugal "draw with 3+ goals" also made money in every season (from rule hunt v3).
- Sheet "League tendencies".

## 5. Rules versus the odds of their own matches (2026/27)
- **Result:** of 166,136 confirmed rules, 1,230 hit clearly more often than the odds of their own matches predicted. The "no edge" twin, which draws results from the odds, gives 4,047.
  - This is after removing this season's general goal surplus.
  - **Rules do not add hits beyond the odds.**
- Two clusters stand out, but each is a single effect, so they are kept as "watch" only:
  - **1st-half 0-2** when the away team is a strong favourite: 17% in 2026/27, where the odds said 10%.
  - **Both teams score in the 1st half:** one cluster of rules.

## 6. Not usable
- **Goal surplus:** 2026/27 so far has more goals than the odds expect, in all leagues. It is not a yearly pattern; no month repeats it in 2024/25 or 2025/26.

## Where it is kept
Every strategy is in `analysis/strategies.yaml` and `analysis/STRATEGIES.md` (committed). `daily_scan.py` checks them every day.

Code:
- `hi_data.py`, `hi_rank.py`, `hi_boost.py`, `hi_trees.py`, `hi_leagues.py`, `hi_compare.py`, `hi_study.py`
- `build_strategy_book.py`, `daily_scan.py`, `daily_scan.sh`

Rebuild:
```
python analysis/hi_data.py
python analysis/hi_rank.py
python analysis/hi_boost.py
python analysis/hi_leagues.py
python analysis/hi_trees.py
python analysis/hi_compare.py
python analysis/hi_study.py
python analysis/build_strategy_book.py
```
