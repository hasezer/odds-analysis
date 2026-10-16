# How to spot 1/X, 2/X, X/1, X/2, 1/2 and 2/1

**Goal:** the hit rate only, not beating Nesine.

**Data:** our own collection only (Nesine closing odds via Mackolik). 17,942 matches with all 9 HT/FT prices:
- 2024/25 + 2024: 7,773
- 2025/26 + 2025: 7,701
- 2026/27 + 2026 so far: 2,468

**The rule for every test:** found on 2024/25 only, then checked on 2025/26 and 2026/27. Searches also ran on shuffled results, as a luck control.

| Result | What happens | Normal |
|---|---|---|
| X/1 | level at half-time, home wins | 14.6% |
| X/2 | level at half-time, away wins | 10.9% |
| 1/X | home ahead at half-time, ends level | 5.4% |
| 2/X | away ahead at half-time, ends level | 5.3% |
| 2/1 | away ahead at half-time, home wins | 2.7% |
| 1/2 | home ahead at half-time, away wins | 2.3% |

## What I tried, for every one of the six results

1. **Every single sign (about 390):**
   - every market's odds and chances;
   - full-time and half-time correct scores;
   - the HT/FT prices themselves;
   - an HT/FT price rebuilt from Nesine's *other* markets (goals per half);
   - Nesine's "after half-time" chances;
   - each team's last-10 habits: leading, trailing, blowing leads, coming back, 1st- and 2nd-half goals;
   - league history, kick-off hour, weekday, days into the season, rest days.
2. **Every 1- and 2-condition rule** built from the 40 best signs: about 28,000 rules per result. The same search on shuffled results is the luck control.
3. **Machine learning:** boosted trees on all 390 signs, and logistic regression.
4. **"Two-part" signs:** chance of the half-time state × chance of the full-time result.
5. **"Score paths":** e.g. half-time 1-0 chance × full-time 1-1 chance, for 1/X.
6. **Team comeback and blown-lead records** over the last 20 matches and the previous season, for both teams.
7. **Two-driver maps:** half-time state chance × full-time result chance.
8. **Pairs:** X/1 or X/2, 1/X or 2/X, 1/2 or 2/1.

## The answer in one picture (chart `htft3_2_what_works.png`)

How much each technique raised the hit rate on 2025/26 and 2026/27 (1.00× = no better than random):

| Technique | X/1 | X/2 | 1/2 | 2/1 | 1/X | 2/X |
|---|---|---|---|---|---|---|
| **its own HT/FT odds (lowest 10%)** | **1.62×** | **1.75×** | 1.45× | 1.27× | 1.09× | 1.21× |
| HT/FT price rebuilt from the other markets | 1.63× | 1.79× | **1.63×** | **1.44×** | 1.02× | 1.35× |
| best 2-condition rule (chosen on 2024/25) | 1.15× | **1.91×** | **1.82×** | **2.10×** | 1.16× | 1.15× |
| machine learning: boosted trees | 1.19× | 1.54× | 1.34× | 1.10× | 0.76× | 0.82× |
| machine learning: logistic | 1.44× | 1.81× | 1.60× | 1.21× | 1.18× | 1.20× |
| team comeback / blown-lead habits | 1.29× | 1.26× | 1.04× | 1.28× | 1.05× | 0.89× |
| league history | 0.87× | 1.17× | 0.52× | 1.00× | 0.90× | 1.42× |
| calendar, kick-off time, rest days | 1.05× | 1.12× | 0.41× | 1.07× | 0.92× | 1.31× |

**What this means:**
- **The result's own HT/FT odds are the main sign.** Nesine's prices already "know" most of what can be known.
- **For the turnarounds (1/2, 2/1), the other markets help.** Their HT/FT odds are squeezed below the 35 cap and stop separating games. Odds like "away wins & over 4.5" or "score 2-1" still do.
- **Team habits, league history, the calendar and boosted trees add nothing.** The boosted trees did worse than the odds: they learned noise.

## Result by result

### X/1: level at half-time, home wins (normal 14.6%)

**Odds ladder** (chart `htft3_1_ladders.png`):

| X/1 odds | ≤ 3.66 | 3.66–3.82 | 3.82–4.07 | 4.07–4.44 | 4.44–4.85 | 4.85–5.94 | > 5.94 |
|---|---|---|---|---|---|---|---|
| Happened | 22% | 17% | 20% | 19% | 17% | 15% | 8% |

**Best rule (stored):** X/1 odds ≤ 3.66 → 20.1% / 27.0% / 40.0% across the three seasons (408 / 74 / 30 matches).
- Nesine rarely prices X/1 that low since 2025/26, so it fires only 1–3 times a week.

**What makes X/1 likely:** a home favourite that is likely to be level at half-time. In Nesine terms: a low "1st-half result X" price and a low home-win price.

**Nothing beat the X/1 odds:**
- 2-condition rules: 51 held in 2025/26 (luck: about 3), but none beat the X/1 odds in both later seasons;
- team habits and league history: no gain.

### X/2: level at half-time, away wins (normal 10.9%)

**Odds ladder:**

| X/2 odds | ≤ 4.14 | 4.14–4.50 | 4.50–5.13 | 5.13–5.94 | 5.94–6.77 | 6.77–9.00 | > 9.00 |
|---|---|---|---|---|---|---|---|
| Happened | 21% | 19% | 16% | 13% | 12% | 10% | 5.5% |

**Best rule (stored):** "home wins both halves" odds ≥ 13.35 AND "away wins at least one half" chance ≥ 68.8% → 24.3% / 22.6% / 19.0% (173 / 230 / 63 matches).
- That is a strong away favourite in a game with no clear home push. It is about the same as X/2 odds ≤ 4.14 (18–25%).

**This one is clearly real:** 272 rules held in 2025/26, against about 2–3 in the luck runs.

### 1/2: home ahead at half-time, away wins (normal 2.3%)

**Odds ladder:**

| 1/2 odds | ≤ 22 | 22–23.85 | 23.85–27 | 27–31.5 | 31.5–34.5 | > 34.5 |
|---|---|---|---|---|---|---|
| Happened | 4.5% | 3.6% | 3.2% | 2.5% | 1.7% | 1.9% |

**Best rule (stored):** "away wins & over 4.5 goals" odds ≤ 5.66 AND 1/2 odds ≤ 22.00 → 7.3% / 5.1% / 3.4% (314 / 350 / 145 matches). That is roughly 2–3× normal.

**Why it works:**
- 1/2 needs a strong away side in an open game: the home team scores first, then the away team scores 2+.
- The 1/2 price is squeezed under the 35 cap. "Away wins & over 4.5" and "away wins & both teams score" show it better.
- On the top 5% of games, "away wins & both teams score" chance ≥ 27% alone gives 5.9% / 4.9% / 3.9%. Taking the same number of games by the 1/2 odds gives 5.4% / 3.9% / 3.2%.

### 2/1: away ahead at half-time, home wins (normal 2.7%)

**Odds ladder:**

| 2/1 odds | ≤ 20.1 | 20.1–22.9 | 22.9–25 | 25–28 | 28–34 | > 34 |
|---|---|---|---|---|---|---|
| Happened | 3.6% | 3.6–3.7% | 3.1% | 2.7% | 2.4% | 1.6% |

**Best rule (stored):** score 2-1 chance ≥ 9.3% AND "home wins at least one half" chance ≥ 56% → 6.4% / 7.0% / 3.6% (451 / 172 / 138 matches).
- That is a home favourite with a likely 2-1 score: it concedes first and comes back.
- It is weaker in 2026/27 so far, so watch the tracker.
- The mirror of the 1/2 sign ("home wins & both teams score") adds nothing for 2/1.

### 1/X and 2/X: the half-time leader is pegged back to a draw (normal 5.4% and 5.3%)

**They are almost unpredictable.** At every odds level they happen about 4–7% of the time.

| 1/X odds | ≤ 12.35 | 12.35–12.60 | … | 13.95–15.50 | > 15.50 |
|---|---|---|---|---|---|
| Happened | 6.0% | 6.7% | 5–6% | 5.4% | 4.2% |

- Nesine's 1/X and 2/X prices sit in a narrow band (12–16), so they can't separate games.
- **Nothing held up beyond luck:**
  - rules found on 2024/25 held in 2025/26 no more often than on shuffled results:
    - 1/X: 7–9 rules, against about 16–19 in the luck runs;
    - 2/X: 4–66 rules, against about 16–24 (up to 72);
  - the 2/X rules that also held in 2026/27 mix league history with a strong-away sign (about 7–9%). In 2026/27 they were no better than taking the same number of games with the lowest 2/X odds;
  - "low-scoring game" signs (under 2.5, score 1-1, half-time 1-0 / 0-1) stay near normal.
- **The one small exception:** for 2/X, "both halves over 1.5: NO" priced ≤ 1.05 gives 8.3% / 8.1% / 9.5%. But that is only 264 / 149 / 74 matches, and the 1/X mirror doesn't confirm it, so treat it as luck.
- **The honest answer:** these two results can't be picked reliably. The best you can do is about 6–7%.

### The pairs
- **X/1 or X/2** ("level at half-time, then someone wins"): about 25% in almost every kind of game. A likely half-time draw also makes a full-time draw likely, so the two cancel out. No sign helps.
- **1/X or 2/X** ("leader pegged back"): about 10–11%, the same story. Nothing held up.
- **1/2 or 2/1** ("any turnaround"): open, high-scoring games with goals expected from both sides reach about 5–8%. The 1/2 and 2/1 rules above are better on their own.

## What does NOT help
Checked on later seasons, every one of these added nothing:
- **Team habits** (comeback rate, blown leads, pegged-back leads, results after half-time draws), over the last 10, the last 20 or the previous season. The best is about 1.0–1.3×, and nothing beyond the odds.
- **League history** (a league's recent extra 1/2, X/1 …): unstable from season to season.
- **Kick-off hour, weekday, stage of the season, rest days:** nothing beyond the odds.
- **Machine learning on all 390 signs:** worse than the odds. Logistic regression is about the same as the odds.
- **Two-part and score-path signs:** the same as the odds.

## How to use it
1. **Pick X/1 and X/2 by their own odds:** the lower, the likelier. X/1 ≤ 3.66 → 20–40%; X/2 ≤ 4.14 → about 20–25%.
2. **For 1/2 and 2/1, add the other markets:**
   - 1/2: "away wins & over 4.5" ≤ 5.66 with 1/2 ≤ 22.00;
   - 2/1: 2-1 score likely and "home wins at least one half" likely.
   - Expect about 5–7% in a good season and 3–4% in a bad one. These are long shots: most bets still lose.
3. **Don't pay for 1/X and 2/X "signs".** Nothing picks them out.
4. **The daily scan flags the four stored rules automatically.** The tracker follows them on new matches.
   - For information: the 1/2 and 2/1 rules also made money in two of three seasons (1/2: +49 / +2 / −35 per 100; 2/1: +42 / +46 / −24). The X/1 and X/2 rules lost 3–29 per 100 in most seasons.

## Files
- **Excel:** `output/htft3.xlsx`. Sheets: odds ladders, best techniques, single signs, best rules, luck control, machine learning, what the models used, two-part and team habits, two-driver maps.
- **Charts:**
  - `output/htft3_1_ladders.png` (each result by its own odds);
  - `output/htft3_2_what_works.png` (each technique × result).
- **Code:**
  - `htft3_data.py` (features)
  - `htft3_signs.py` (single signs)
  - `htft3_rules.py` (rules and luck control)
  - `htft3_ml.py` (machine learning)
  - `htft3_extra.py` (two-part, team habits, maps)
  - `htft3_report.py` (Excel and charts)
- **Strategy book:** 4 new rules, plus a lesson.
  - `htft3-X/1-odds-5`
  - `htft3-X/2-rule`
  - `htft3-1/2-rule`
  - `htft3-2/1-rule`
