# HT/FT (İY/MS) deep dive 2: which game ends in which result

**Data:** our own collection only: Nesine closing odds via Mackolik. 17,942 matches with all 9 HT/FT prices:
- 2024/25 + 2024: 7,773
- 2025/26 + 2025: 7,701
- 2026/27 + 2026 so far: 2,468

**How to read it:** everything is seen from the **favourite's side**, as set by Nesine's 1X2 odds.
- **F** = favourite, **U** = underdog ("dog"), **X** = level. So **F/F** = the favourite leads at half-time and wins.
- If the favourite plays at home, F/F is Nesine's **1/1**; if it plays away, F/F is **2/2**.
- Seeing it this way lets home-favourite and away-favourite games be pooled, which makes the patterns much clearer.

**Earlier work:** this builds on the first HT/FT study (`HTFT_REPORT.md`). Those findings still hold:
- the 35 cap on turnaround odds;
- the other markets mainly tell you what not to bet;
- no model beat the HT/FT price;
- past-result patterns ("3-2 last week…") did not repeat.

## The short answer
1. **Which game will be which:**
   - The favourite's strength decides most of it (chart 1).
   - F/F goes from 21% of games (favourite below 40% to win) to 56% (favourite 70%+).
   - X/X is most common in close, low-scoring games: 19–22%.
   - Turnarounds stay rare at every strength: 1–4%.
   - Nesine's own HT/FT odds pick out each result about as well as any rule. When its most likely result is priced at 50%+, it happens 63% of the time.
2. **No HT/FT bet makes money.**
   - Every result loses at every favourite strength: 0.41–0.89 back per unit staked.
   - I scanned 311 groups of games, outcome by outcome. One group was above break-even in the first two seasons, and luck alone produces about one. It is on the watch list.
3. **Nesine gives the underdog too much in the second half.**
   - When the game is level or the favourite leads at half-time, the underdog goes on to win less often than Nesine's HT/FT prices imply. That holds in every season: by 0.4–2 points overall, and 1–10 points with a strong favourite.
   - So **the underdog's HT/FT results are the worst bets** (down to 0.20 back per unit).
4. **Two tools you can use live** (charts 2 and 5):
   - from the half-time score and the pre-match odds, how often the favourite wins, draws or loses;
   - how often goals come in the second half.
   - They are stable across all three seasons. Compare them with Nesine's live odds at half-time.
5. **If you like half-time ideas, bet them outside the HT/FT market.**
   - Both teams score in both halves (0.89), half-time 1-1 (0.88) and both teams score in the 2nd half (0.87) lose much less.
   - HT/FT results return only 0.63–0.76.

## 1. The HT/FT map (chart `htft2_1_map.png`)

Share of matches by the favourite's chance to win (Nesine's 1X2 odds, cut removed):

| Result | under 40% | 40-50% | 50-60% | 60-70% | 70%+ |
|---|---|---|---|---|---|
| F/F fav ahead at HT, fav wins | 21% | 26% | 33% | 43% | 56% |
| X/F level at HT, fav wins | 14% | 16% | 18% | 19% | 19% |
| X/X level, ends level | 18% | 17% | 15% | 11% | 9% |
| U/U dog ahead, dog wins | 18% | 14% | 10% | 7% | 4% |
| X/U level at HT, dog wins | 12% | 10% | 8% | 5% | 2% |
| F/X fav ahead, ends level | 6% | 6% | 6% | 5% | 4% |
| U/X dog ahead, ends level | 6% | 6% | 5% | 4% | 4% |
| U/F dog ahead, fav wins | 3% | 3% | 3% | 4% | 3% |
| F/U fav ahead, dog wins | 2% | 2% | 2% | 1% | 1% |

- **It is the same every season.** For example, F/F with a 60–70% favourite: 42.6% / 43.9% / 43.7%.
- **The sheet "Map favourite x goals"** also splits each strength by expected goals. Example: with a favourite below 40% and low goals expected, X/X is the most likely result (21%).

**How to spot each result** (sheet "Spot each result"). The best group of games was chosen on the first two seasons only.

| Result | Normal | Best group (2024/25 / 2025/26 / 2026/27) | Top 10% by its own HT/FT odds |
|---|---|---|---|
| F/F | 29% | fav 70%+ and high goals: 57 / 61 / 56% | odds ≤ 2.0: 51 / 49 / 53% |
| X/F | 17% | fav 60–70%, goals 45–55%: 20 / 22 / 15% | odds ≤ 4.3: 18 / 22 / 22% |
| X/X | 15% | fav under 40% and low goals: 19 / 22 / 22% | odds ≤ 4.1: 23 / 24 / 23% |
| U/U | 14% | fav under 40%, goals 45–55%: 20 / 19 / 14% | odds ≤ 4.5: 25 / 26 / 22% |
| X/U | 9% | fav under 40% and low goals: 15 / 11 / 12% | odds ≤ 6.5: 15 / 14 / 13% |
| U/F | 3% | fav 60–70% and high goals: 7 / 3 / 6% | odds ≤ 21.7: 6 / 4 / 4% |

**The result's own HT/FT odds** are as good a guide as any group of games, and steadier. Nesine's prices already "know" which game will be which.

**Nesine's most likely HT/FT result** (sheet "Most likely result"):

| Nesine says (cut removed) | It happened |
|---|---|
| up to 25% | 22.7% |
| 30–35% | 32.3% |
| 40–50% | 46.6% |
| over 50% | **63.2%** (Nesine said 55.1%) |

- Its two most likely results together cover 49% of games.

## 2. The half-time table, a live aid (chart `htft2_2_halftime.png`)

After each half-time score, how often each full-time result really happened, by the favourite's pre-match strength. A few examples:

| Half-time | Fav 40–50% | Fav 50–60% | Fav 60–70% |
|---|---|---|---|
| 0-0 | fav wins 36%, draw 40%, dog 23% | fav 44%, draw 38%, dog 18% | fav 56%, draw 33%, dog 11% |
| fav 1 ahead | fav wins 70%, draw 22%, dog 8% | fav 77%, draw 17%, dog 6% | fav 82%, draw 14%, dog 4% |
| dog 1 ahead | fav wins 15%, draw 29%, dog 56% | fav 21%, draw 28%, dog 51% | fav 28%, draw 31%, dog 40% |

**How to use it live:** a bet is worth it only if Nesine's live odds are **above 100 ÷ chance**. Example: a 50–60% favourite at 0-0 at half-time wins 44% of the time. The live odds for "favourite wins" must therefore be above 100 ÷ 44 = 2.27.
- We have no live odds in our data, so I can't tell you how often that happens. You can check it yourself on Nesine at half-time.
- **It is steady:** a 50–60% favourite at 0-0 went on to win 44.8% / 43.2% / 43.2% of the time in the three seasons.

**Goals in the second half** (chart `htft2_5_halftime_goals.png`):
- **The pre-match goal odds matter, not the first-half goals.** With a 45–55% pre-match chance of over 2.5, the 2nd half had at least one goal 75–80% of the time, whether the first half had 0, 1, 2 or 3+ goals.
- **With a high-goal game (65%+), 0-0 at half-time is not a warning sign:** the 2nd half still had a goal 87% of the time, and 2+ goals 58%.

## 3. Nesine's HT/FT prices: where they are wrong, and why it doesn't pay

**After half-time** (sheet "Implied vs actual"):
- I turned Nesine's pre-match HT/FT prices into "after half-time" chances and compared them with what happened.
- When the game is level or the favourite leads at half-time, **the underdog goes on to win less often than the prices imply**. Pooled, that is 1.3 / 1.9 / 2.1 points less when level and 1.2 / 0.9 / 0.4 points less when the favourite leads.
- With a 60%+ favourite the gap is 1–10 points.
- The favourite's comebacks and late wins are slightly under-priced.

**What 1 unit returns on each result** (chart `htft2_3_value.png`):
- **Everything loses.** The underdog's results lose the most: with a 70%+ favourite, X/U returns 0.41 and F/U 0.20.
- **The least bad:**
  - F/F with a 70%+ favourite: 0.84 (0.84 / 0.82 / 0.87);
  - U/X (underdog ahead, then pegged back): 0.83–0.89 with a 60%+ favourite.
- **F/F by its own odds:** at odds of 1.3–1.7 it returns 0.80–0.92. That is the nearest any HT/FT result gets to break-even.
- **Nesine keeps about 25% of HT/FT stakes** on average. The second-half error above is much smaller than that.

**Scan with a luck control** (sheet "Scan (luck control)"):

| Groups scanned | Groups | At break-even in 2024/25 AND 2025/26 | Same luck test on fake no-edge data |
|---|---|---|---|
| result × favourite strength × goals | 180 | 1 | 1.1 on average (up to 4) |
| result × its own odds (10 steps) | 86 | 0 | 0.05 |
| result × favourite strength | 45 | 0 | 0.05 |

- **The one group:** "favourite ahead at half-time, ends level" (F/X) with a 60–70% favourite and high goals (65%+). It returned 1.38 / 1.15 / 1.32 per unit on 134 / 150 / 81 games.
- **Why it is probably luck:**
  - the neighbouring groups don't confirm it;
  - moving the limits a little breaks it;
  - the home-favourite and away-favourite versions each lose in one season.
- **Status:** stored as a **watch** lead, tracked live.

## 4. Half-time ideas: the cheapest way to bet them (chart `htft2_4_family.png`)
What 1 unit returns over time on all matches, 2024–2026 (sheet "Half-time bets"):

| Bet | Odds ≈ | Returns per unit |
|---|---|---|
| Both teams score in both halves (Evet/Evet) | 16.6 | 0.89 |
| Half-time score 1-1 | 8.0 | 0.88 |
| Both teams score in the 2nd half | 3.2 | 0.87 |
| 1st half over 0.5 goals | 1.2 | 0.86 |
| 2nd half ends level | 2.4 | 0.84 |
| Favourite wins the 2nd half | 2.2 | 0.84 |
| Favourite leads at half-time | 2.4 | 0.84 |
| Level at half-time | 2.1 | 0.83 |
| **HT/FT results** | 3–33 | **0.63–0.76** |

- **"Favourite wins the 2nd half" vs X/F:** the 2nd-half bet catches part of the same idea for 0.84 per unit, against 0.76 for X/F.
- **"Level at half-time" vs X/X:** 0.83 against 0.75.

## 5. Other ideas tested (sheets "Leagues late", "Hypotheses")
- **Leagues that score late:**
  - No league keeps scoring later, or earlier, than the odds expect. The season-to-season correlation between leagues is −0.42 / 0.48 / −0.28, which is noise.
  - Nesine prices the second half's share of goals almost exactly: 55.5% happened, 56.0% expected.
- **Portugal, following the 2-2 effect from the system study:**
  - Portuguese draws are high-scoring, so draws that are already level at half-time are rare. Portugal X/X loses 39 / 38 / 17 per 100.
  - "Home ahead at half-time, ends level" (1/X): +15 / −3 / +10 per 100. It fits the 2-2 story, but it is not proven, and the away version (2/X) loses. **Watch lead.**
- **High-scoring draws in high-goal games:** no. Draws, "draw & over 2.5", 2-2 and X/X are all priced *worse* in high-goal games.

## What to do with it
- **Before the match:**
  - Use chart 1 or the HT/FT odds to know what to expect. Don't expect to beat the price.
  - If you play HT/FT, the least bad bet is F/F with a strong favourite at odds of 1.3–1.7.
  - Avoid the underdog's results and the capped turnarounds.
- **At half-time:** use chart 2 (results) and chart 5 (2nd-half goals) against the live odds. Bet only when the live odds are above 100 ÷ chance.
- **Half-time ideas:** prefer "both teams score in both halves", "half-time 1-1" or "both teams score in the 2nd half" to the HT/FT market.
- **Watch leads** (in the strategy book, tracked live from today, not for betting yet):
  - F/X with a 60–70% favourite and over 2.5 at 65%+ (home and away versions);
  - Portugal 1/X.

## Files
- **Excel:** `output/htft2.xlsx`, 17 sheets.
- **Charts:**
  - `output/htft2_1_map.png`
  - `output/htft2_2_halftime.png`
  - `output/htft2_3_value.png`
  - `output/htft2_4_family.png`
  - `output/htft2_5_halftime_goals.png`
- **Code:**
  - `htft2_data.py` (favourite-side dataset)
  - `htft2_study.py` (all tables and the luck-controlled scan)
  - `htft2_report.py` (Excel and charts)
- **Strategy book:** lessons added, and 3 watch leads: `watch-htft-fav-ahead-draw-home`, `watch-htft-fav-ahead-draw-away` and `watch-POR-1-HT_FT||1/X`.
