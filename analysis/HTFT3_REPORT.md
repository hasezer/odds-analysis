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

**A fair race:** every technique picks the 1 game in 10 it rates most likely, in each later season. That is about 1,000 games per technique in 2025/26 and 2026/27 together. Each cell shows how many times more often the result happened than normal (1.00× = no better than random).

| Technique | X/1 | X/2 | 1/2 | 2/1 | 1/X | 2/X |
|---|---|---|---|---|---|---|
| **its own HT/FT odds** | **1.38×** | **1.84×** | **1.63×** | **1.27×** | 1.04× | 1.21× |
| HT/FT price rebuilt from the other markets | 1.38× | 1.82× | 1.72× | 1.15× | 1.04× | 1.25× |
| best other single sign (chosen on 2024/25) | 1.41× | 1.83× | 1.51× | 1.26× | 1.22× | 1.12× |
| machine learning: logistic | 1.40× | 1.85× | 1.63× | 1.31× | 1.15× | 1.21× |
| machine learning: boosted trees | 1.22× | 1.37× | 1.42× | 1.23× | 0.81× | 0.96× |
| team comeback / blown-lead habits | 1.29× | 1.30× | 1.13× | 1.20× | 0.95× | 0.92× |
| league history | 1.05× | 1.10× | 0.63× | 0.96× | 0.87× | 0.91× |
| calendar, kick-off time, rest days | 1.05× | 1.09× | 0.96× | 0.99× | 0.93× | 1.18× |

**What the own odds give in that top 10%:** X/1 20%, X/2 20%, 1/2 3.8%, 2/1 3.2%, 1/X 5.5%, 2/X 6.3%.

**How much is luck?** Luck alone moves a cell by about ±0.2× for X/1 and X/2, ±0.3× for 1/X and 2/X, and ±0.4–0.5× for 1/2 and 2/1. So the top four rows are the same.

**What this means:**
- **The result's own HT/FT odds are the sign.** Nesine's prices already "know" what can be known.
- **Nesine's other markets tell the same story.** An HT/FT price rebuilt only from its goals and result markets ranks the games the same way. So do the best of the 390 other signs and logistic regression.
- **Team habits, league history and the calendar add nothing.** Boosted trees did worse than the odds: they learned noise.

**Correction to an earlier draft:** it said the other markets help for 1/2 and 2/1. That came from comparing groups of different sizes. In a fair race they don't.

## Rules against the plain odds

The best 2-condition rule for each result (found on 2024/25, held in 2025/26), next to simply taking the same number of games with the lowest odds for that result. Hits are 2025/26 and 2026/27 together.

| Result | Rule | In the book | Games | Rule hits | Lowest-odds hits |
|---|---|---|---|---|---|
| X/1 | "home wins & under 3.5" chance ≥ 39.2% AND "away under 1.5 goals" ≤ 1.07 | no | 162 | 29 | **43** |
| X/2 | "home wins both halves" ≥ 13.35 AND "away wins a half" chance ≥ 68.8% | yes | 293 | 64 | **70** |
| 1/2 | "away wins & over 4.5" ≤ 5.66 AND 1/2 ≤ 22.00 | yes | 495 | **23** | 19 |
| 2/1 | score 2-1 chance ≥ 9.3% AND "home wins a half" chance ≥ 56.2% | yes | 310 | **17** | 13 |
| 1/X | "1/X or 2/X" chance ≥ 11.9% AND half-time 1-1 ≤ 6.72 | no | 305 | 19 | **20** |
| 2/X | corners over 9.5 ≥ 1.86 AND double chance X2 ≤ 1.31 | no | 611 | 39 | 39 |

**No rule clearly beats the plain odds:**
- for X/1 and X/2 the rules are worse;
- for 1/2 and 2/1 they are 4 hits better, which is luck-sized;
- for 1/X and 2/X they are the same.

## Result by result

### X/1: level at half-time, home wins (normal 14.6%)

**Odds ladder** (chart `htft3_1_ladders.png`):

| X/1 odds | ≤ 3.66 | 3.66–3.82 | 3.82–4.07 | 4.07–4.44 | 4.44–4.85 | 4.85–5.94 | > 5.94 |
|---|---|---|---|---|---|---|---|
| Happened | 22% | 17% | 20% | 19% | 17% | 15% | 8% |

**Stored:** X/1 odds ≤ 3.66 → 20.1% / 27.0% / 40.0% across the three seasons (408 / 74 / 30 matches).
- Nesine rarely prices X/1 that low since 2025/26, so it fires only 1–3 times a week.

**What makes X/1 likely:** a home favourite that is likely to be level at half-time. In Nesine terms: a low "1st-half result X" price and a low home-win price.

**Nothing beat the X/1 odds:**
- 2-condition rules: 51 held in 2025/26 (luck: about 3), but none beat the X/1 odds in the later seasons;
- team habits and league history: no gain.

### X/2: level at half-time, away wins (normal 10.9%)

**Odds ladder:**

| X/2 odds | ≤ 4.14 | 4.14–4.50 | 4.50–5.13 | 5.13–5.94 | 5.94–6.77 | 6.77–9.00 | > 9.00 |
|---|---|---|---|---|---|---|---|
| Happened | 21% | 19% | 16% | 13% | 12% | 10% | 5.5% |

**Stored rule:** "home wins both halves" odds ≥ 13.35 AND "away wins at least one half" chance ≥ 68.8% → 24.3% / 22.6% / 19.0% (173 / 230 / 63 matches).
- That is a strong away favourite in a game with no clear home push.
- The same number of games with the lowest X/2 odds did slightly better: 24.3% / 22.2% in 2025/26 / 2026/27.
- The book's older X/2 odds band (≤ 4.21) gives 17.4% / 22.0% / 20.3%.

**The X/2 sign is clearly real:** 272 rules held in 2025/26, against about 2–3 in the luck runs. But it is the same sign as the X/2 odds.

### 1/2: home ahead at half-time, away wins (normal 2.3%)

**Odds ladder:**

| 1/2 odds | ≤ 22 | 22–23.85 | 23.85–27 | 27–31.5 | 31.5–34.5 | > 34.5 |
|---|---|---|---|---|---|---|
| Happened | 4.5% | 3.6% | 3.2% | 2.5% | 1.7% | 1.9% |

**Stored rule:** "away wins & over 4.5 goals" odds ≤ 5.66 AND 1/2 odds ≤ 22.00 → 7.3% / 5.1% / 3.4% (314 / 350 / 145 matches). That is 2–3× normal, but the 1/2 odds alone do almost as well: 4.0% / 3.4% on the same number of games.

**What makes 1/2 likely:** a strong away side in an open game. The home team scores first, then the away team scores 2+.
- The book's older 1/2 odds band (≤ 21.70) gives 5.9% / 4.3% / 3.8%.
- "Away wins & both teams score" picks a few more than the 1/2 odds on its top 5% (23 / 19 / 6 hits against 21 / 15 / 5), and the same on its top 10%. That is too small to count.

### 2/1: away ahead at half-time, home wins (normal 2.7%)

**Odds ladder:**

| 2/1 odds | ≤ 20.1 | 20.1–22.9 | 22.9–25 | 25–28 | 28–34 | > 34 |
|---|---|---|---|---|---|---|
| Happened | 3.6% | 3.6–3.7% | 3.1% | 2.7% | 2.4% | 1.6% |

**Stored rule:** score 2-1 chance ≥ 9.3% AND "home wins at least one half" chance ≥ 56% → 6.4% / 7.0% / 3.6% (451 / 172 / 138 matches).
- That is a home favourite with a likely 2-1 score: it concedes first and comes back.
- The same number of games with the lowest 2/1 odds: 3.5% / 5.1%. The rule won 2025/26 and lost 2026/27.
- The book's older 2/1 odds band (≤ 19.85) gives 5.1% / 3.4% / 3.9%.
- Use **chances**, not odds, for correct scores. Nesine's correct-score odds are longer since 2024/25 (a smaller margin), so a rule like "2-1 odds ≤ 6.75" picked 441 games in 2024/25 and just 1 in each later season.
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
- **Best single signs in the fair race:**
  - 1/X: "the other-markets model fits Nesine's prices badly", 6.5% against 5.3% normal;
  - 2/X: the 2/X odds, 6.3% against 5.2%.
  - Both are within luck.
- **The honest answer:** these two results can't be picked reliably. The best you can do is about 6–7%.

### The pairs
- **X/1 or X/2** ("level at half-time, then someone wins"): about 25% in almost every kind of game. A likely half-time draw also makes a full-time draw likely, so the two cancel out. No sign helps.
- **1/X or 2/X** ("leader pegged back"): about 10–11%, the same story. Nothing held up.
- **1/2 or 2/1** ("any turnaround"): open, high-scoring games with goals expected from both sides reach about 5–7% (normal 5%). Picking the same number of games by the 1/2 and 2/1 odds does as well.

## What does NOT help
Checked on later seasons, every one of these added nothing beyond the result's own odds:
- **Nesine's other markets:** rebuilt into an HT/FT price, they rank games the same way. Nesine's prices agree with each other.
- **Team habits** (comeback rate, blown leads, pegged-back leads, results after half-time draws), over the last 10, the last 20 or the previous season. They reach 0.9–1.3× normal, always below the odds.
- **League history** (a league's recent extra 1/2, X/1 …): unstable from season to season.
- **Kick-off hour, weekday, stage of the season, rest days:** nothing.
- **Machine learning on all 390 signs:** worse than the odds. Logistic regression equals the odds.
- **Two-part and score-path signs:** the same as the odds.
- **2-condition rules:** no better than the same number of lowest-odds games (table above).

## How to use it
1. **Use the result's own HT/FT odds: the lower, the likelier.** The strategy book's odds bands:
   - X/1 ≤ 3.66: 20–40% (new);
   - X/2 ≤ 4.21: 17–22%;
   - 1/2 ≤ 21.70: about 4–6%;
   - 2/1 ≤ 19.85: about 3–5%.
2. **The three new rules (X/2, 1/2, 2/1) flag the same kind of games.** They hit about as often as the odds bands. They are long shots: most 1/2 and 2/1 bets still lose.
3. **Don't pay for 1/X and 2/X "signs".** Nothing picks them out.
4. **The daily scan flags the stored rules and bands automatically.** The tracker follows them on new matches.
   - **Money, for information:** only the later seasons count, because 2024/25 is where the rules were found. Per 100 staked in 2025/26 / 2026/27:
     - 1/2 rule: +1 / −35;
     - 2/1 rule: +46 / −24;
     - X/2 rule: −7 / −21;
     - X/1 ≤ 3.66: −3 / +43 (only 30 games).
   - There is no reliable profit.

## Files
- **Excel:** `output/htft3.xlsx`. Sheets:
  - odds ladders;
  - best techniques (the fair race);
  - rules vs own odds;
  - single signs;
  - best rules;
  - luck control;
  - machine learning;
  - what the models used;
  - two-part and team habits;
  - two-driver maps.
- **Charts:**
  - `output/htft3_1_ladders.png` (each result by its own odds);
  - `output/htft3_2_what_works.png` (the fair race: each technique × result).
- **Code:**
  - `htft3_data.py` (features)
  - `htft3_signs.py` (single signs)
  - `htft3_rules.py` (rules and luck control)
  - `htft3_ml.py` (machine learning)
  - `htft3_extra.py` (two-part, team habits, maps)
  - `htft3_report.py` (fair race, rules vs odds, Excel and charts)
- **Strategy book:** 4 new entries, plus a lesson.
  - `htft3-X/1-odds-5`
  - `htft3-X/2-rule`
  - `htft3-1/2-rule`
  - `htft3-2/1-rule`
