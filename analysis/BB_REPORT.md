# Both teams score in both halves: how to spot it

**The bet:** Nesine's "1. Yarı / 2. Yarı Karşılıklı Gol: Evet/Evet". Both teams score in the 1st half, and both score again in the 2nd half.

**Goal:** the hit rate only, not beating Nesine.

**Data:** our own collection only (Nesine closing odds via Mackolik). 20,996 finished games:
- 2024/25 + 2024: 9,003
- 2025/26 + 2025: 8,911
- 2026/27 + 2026 so far: 3,082

**The rule for every test:** found on 2024/25, then checked on 2025/26 and 2026/27. Nesine's own price for this bet only starts in 2025/26 (about half the games then, most games now). So signs that use it are found on 2025/26 and checked on 2026/27. Every rule search also ran on shuffled results, as a luck control.

## The short answer

- **It happens in 5.8% of games** (5.5% / 5.7% / 7.2% across the three seasons): about 1 game in 17.
- **One thing decides it: both teams are expected to score a lot.** Every one of these games had 4+ goals. Most ended 2-2 (23%) or 3-2 / 2-3 (31%).
- **The best you can do is about 1 in 8 or 9.**
  - The 5% of games where both sides are expected to score most hit **11–12%**, twice normal.
  - The top 2% hit about 13%.
  - The current season runs higher (15–18% in its top 2–5%), but that is one season.
- **Nothing pushes it further.** Three very different methods all stop at the same 11–12%:
  - Nesine's own price for the bet;
  - a model built only from Nesine's goal markets;
  - the best rules from 28,000+ combinations.
- **"Confident" isn't possible with this bet.** Even in the best games, about 7 bets in 8 lose.

## How to pick them (stored in the strategy book; the daily scan flags them)

| Pick | 2024/25 | 2025/26 | 2026/27 | Games a week |
|---|---|---|---|---|
| **Nesine's both-halves odds ≤ 8.34** (its cheapest 5%) | no price yet | 10.3% (232) | 11.9% (210) | about 5–6 |
| **BTTS "yes" odds ≤ 1.36 AND 1st-half "under 1.5 goals" odds ≥ 1.49** | 12.3% (367) | 10.7% (447) | 10.9% (330) | about 9 |
| normal | 5.5% | 5.7% | 7.2% | |

- The second rule means: both teams are very likely to score, and the 1st half is expected to be lively.
- Requiring both picks at once doesn't help (11.1% in 2026/27).
- The tipster's "lowest both-halves odds of the day" picks are the same idea as the first pick.

## What I tried

1. **Every single sign (440):**
   - every market's odds and chances;
   - full-time and half-time correct scores;
   - Nesine's own price for the bet;
   - a "goals model": four goal rates (home and away, each half) fitted to Nesine's team-goals, total-goals and half-result prices. It gives a second, independent chance for this bet in every season.
   - each team's last 10 and last 20 games and previous season: scored or conceded in each half, scored in both halves, both teams scored in each half;
   - the same at home only or away only;
   - league history, kick-off hour, weekday, month, days into the season, rest days.
2. **Pre-set "logic" signs:**
   - the weaker attack's expected goals;
   - both teams 2+ goals;
   - Nesine's 1st-half BTTS × 2nd-half BTTS prices;
   - correct scores with both teams on 2+;
   - how strongly Nesine links the two halves.
3. **Every 1- and 2-condition rule** from the 40 best signs (about 28,000), plus the same search on shuffled results.
4. **Machine learning:** logistic regression (25 signs) and boosted trees (all 440 signs).
5. **A statistics-only team model:** each team's own goals per half from past results, no odds.
6. **Maps, leagues, scorelines, and the two halves** (half-time live table).

## The fair race (chart `bb_3_fair_race.png`)

Every technique picks the same share of games (its top 10%, 5% or 2%) in each later season. The table shows how many times more often than normal the bet won. Both later seasons are pooled: about 1,200 / 600 / 240 games.

| Technique | top 10% | top 5% | top 2% |
|---|---|---|---|
| **goals model** | **1.60×** | **1.92×** | **2.12×** |
| best other single sign: BTTS "yes" chance | 1.62× | 1.81× | 1.74× |
| machine learning: logistic | 1.60× | 1.70× | 1.85× |
| machine learning: boosted trees | 1.40× | 1.64× | 1.64× |
| team habits: both teams score in both halves | 1.35× | 1.50× | 1.62× |
| statistics-only team model | 1.37× | 1.70× | 1.78× |
| league history | 1.25× | 1.20× | 1.13× |
| calendar, kick-off time, rest days | 0.97× | 0.99× | 0.96× |
| *games where Nesine prices the bet:* | | | |
| Nesine's own both-halves price | 1.51× | 1.79× | 2.07× |
| goals model, the same games | 1.49× | 1.83× | 2.07× |

- **How much is luck?** A cell can move by about ±0.3× (top 10%), ±0.4× (top 5%) or ±0.7× (top 2%). So the top rows are the same.
- **Nesine's own price and the goals model pick the same games.** Nesine's goal markets already contain everything.
- **Team habits, past results, league history and the calendar add nothing.** Boosted trees learned noise again.

## How often it happened, by price (chart `bb_1_ladders.png`)

**By Nesine's own odds** (2025/26 + 2026/27, normal 6.2%):

| Odds | ≤ 8.34 | 8.34–9.34 | 9.34–10.80 | 10.80–13.00 | 13.00–15.25 | 15.25–17.85 | 17.85–21.30 | 21.30–24.85 | > 24.85 |
|---|---|---|---|---|---|---|---|---|---|
| Happened | **11.1%** | 7.6% | 7.1% | 7.2% | 7.4% | 6.8% | 4.6% | 3.7% | 2.8% |

Only the cheapest 5% clearly stands out. Between 8.34 and 17.85 the odds hardly separate the games.

**By the goals model's chance** (all three seasons, normal 5.8%):

| Model chance | > 9.3% | 8.3–9.3% | 7.2–8.3% | 5.9–7.2% | 5.1–5.9% | 4.3–5.1% | 3.5–4.3% | 2.8–3.5% | ≤ 2.8% |
|---|---|---|---|---|---|---|---|---|---|
| Happened | **11.1%** | 8.1% | 7.4% | 6.5% | 5.7% | 5.2% | 4.9% | 3.8% | 2.5% |

The top band held in every season: 11.3% / 10.4% / 11.9%. That is the steadiest result in this study.

## The map (chart `bb_2_map.png`)

How often it happened by each team's expected goals (from Nesine's goal markets):
- **Both attacks must be good. One strong team is not enough.**
  - A home side expected to score 1.9+ against a weak away attack: 5.1%.
  - Home 1.9+ and away 1.5+: 11.5%.
- Home 1.36–1.58 with away 1.48+: 10.7% (839 games).
- Both weak: about 2%.

## The two halves

- **Both teams score in the 1st half in 20.5% of games, and in the 2nd half in 27.3%.** The 1st half is the harder part.
- **The halves are almost independent.** Both-halves happens about as often as 1st-half chance × 2nd-half chance (1.01× / 1.04× / 1.13× across the seasons).
- **At half-time (live):** if both teams have already scored, both score again after the break **28%** of the time.
  - It depends little on the score: 1-1 28%, 2-1 28%, 1-2 30%, 2-2 28%.
  - It depends more on the pre-match goal expectation for the 2nd half: 21% in the lowest fifth, 33% in the highest.

## Scorelines

- **Full-time scores of these games:**
  - 2-2: 23%
  - 3-2: 18%
  - 2-3: 13%
  - 3-3: 12%
  - 4-2: 8%
  - 4-3: 5%
- **Half-time:** 1-1 in 52%, 2-1 in 18%, 1-2 in 15%.
- 19% of all games with 4+ goals are both-halves games.

## Leagues

- **Most often:**
  - USA 8.6%
  - Netherlands 8.2%
  - Switzerland 8.2%
  - Germany 2 7.7%
  - Germany 7.6%
- **Least often:**
  - Argentina 2.5%
  - England 2 3.4%
  - Brazil 4.2%
- **The goal markets already explain these differences.** A league's rate above or below the model doesn't carry over to the next season (correlation 0.04).

## What does NOT help
Checked on later seasons, every one of these added nothing beyond the goal expectation:
- **Team habits:** how often a team scores in both halves, concedes in both halves, or plays both-halves games. This covers the last 10, the last 20, home or away only, and the previous season.
- **A statistics-only team model** from past results: weaker than the odds, and nothing beyond them.
- **League history** and **calendar** (kick-off hour, weekday, month, stage of the season, rest days).
- **Boosted trees** on all 440 signs: worse than the simple goals model.
- **Nesine's 1st- and 2nd-half BTTS markets:** they add very little over the goals model. Their "NO" side is missing in about 45% of games, so read their "YES" odds.
- **Corners:** a weak sign that the goal markets already contain.

## Money, for information

- Overall the bet loses money at Nesine's prices.
  - **All both-halves bets:** −15 per 100 (2025/26), −4 (2026/27).
  - **Cheapest odds (≤ 8.34):** −28 and −16.
  - **The BTTS + 1st-half rule:** −19 and −28 (average odds 7.5).
- The middle odds (13.00–17.85) came out at +5 to +11 per 100, but that is within luck.

## If you want to win more often

The both-halves bet needs four things to happen, so even the best games win only about 1 time in 8. Related bets on the same kind of game win far more often. All are already in the strategy book:
- **1st-half BTTS "yes" at odds ≤ 3.00:** 29–34% (the harder half on its own).
- **Both halves over 1.5 goals at odds ≤ 2.84:** 28–34%.
- **Live:** wait for half-time. Only if both teams have scored, back 2nd-half BTTS: 28% (33% in high-goal games).

## Files
- **Excel:** `output/bb.xlsx`. Sheets:
  - ladders by own odds (with money) and by model chance;
  - the fair race;
  - best rules and luck control;
  - the map (rates, games, by season);
  - live tables;
  - leagues;
  - scorelines;
  - machine learning and what it used;
  - all single signs.
- **Charts:**
  - `output/bb_1_ladders.png` (by own odds and by model chance);
  - `output/bb_2_map.png` (home × away expected goals);
  - `output/bb_3_fair_race.png` (every technique on the same number of games).
- **Code:**
  - `bb_data.py` (data and features)
  - `bb_signs.py` (single signs)
  - `bb_ml.py` (machine learning)
  - `bb_rules.py` (rules and luck control)
  - `bb_report.py` (fair race, tables, Excel and charts)
- **Strategy book:** 2 new entries, plus 2 lessons.
  - `bb-odds-5`: promising, because the price only exists for two seasons.
  - `bb-rule`: proven.
