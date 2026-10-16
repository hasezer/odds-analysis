# Your 10-game system (3-4-5): how to pick the games

**Data:** our own collection only (Nesine closing odds via Mackolik), every finished match of the 26 leagues: 2024/25, 2025/26 and 2026/27 so far. One coupon per day, or per weekend (Friday to Monday, Turkey time).
**Validation:** the same luck controls as before.

## The short answer
1. **A 6+ coupon cannot win over time, whichever 10 games you pick.**
   - 6+ is one of Nesine's worst-priced bets: 1 unit returns only about **0.70** over time.
   - A system multiplies that loss in every combo: a treble keeps 0.70³ = 0.34 of its stake.
   - Your coupon, replayed every day since 2024, lost **87%** of the stakes.
   - In 20,000 simulated seasons, none ended in profit.
2. **It is the bet, not the games.** I found nothing that picks 6+ games better than Nesine's own 6+ odds. I tested whether games are linked, league "hot streaks", same-day momentum, the start of the season, leagues, 555 signals and 5,168 rules.
3. **For the same "lots of goals" idea at high odds, "draw & over 2.5" (MS X ve 2,5 Üst: 2-2, 3-3 …) is priced far better.**
   - 1 unit returns 0.86 on average (6+: 0.68).
   - **In Portugal it returns 1.57.** It made money in every season (+27 / +65 / +144 per 100). This is the only bet in our data that has done so.
4. **The recipe ("Goals coupon"):**
   - every weekend, take every Portugal game as "draw & over 2.5";
   - fill up to 10 games with the lowest "draw & over 2.5" odds from the leagues where this bet has paid best.
   - Over three seasons, its games returned **1.29–1.79 per unit**.
5. **How you play it decides how often you see that profit.**
   - **As singles** it made money in every season.
   - **As a 3-4-5 system** it is a lottery. 3+ hits came in only 5–18% of weekends, so most seasons end down. One good weekend pays hundreds of times the stake.

The daily scan now prints both coupons for the coming weekend, and the tracker replays them every weekend.

## 1. How your coupon pays
- 10 games, system 3-4-5 = every treble (120), four-fold (210) and five-fold (252): **582 combos at 1 unit**.
- A combo pays only if all of its games win.
- **3 hits give your money back only if the average odds are 8.35 or more.**

| Odds of each game | 3 hits pay | 4 hits pay | 5 hits pay |
|---|---|---|---|
| 4.7 (the 10 lowest 6+ odds of a weekend in 2026/27) | 0.2× the stake | 1.6× | 10× |
| 6.7 (the same, all seasons) | 0.5× | 5.5× | 46× |
| 9.1 (the 10 lowest 6+ odds of a day) | 1.3× | 17× | 179× |
| 14 ("draw & over 2.5", 10 games) | 4.7× | 85× | 1,301× |
| 17 (Portugal "draw & over 2.5", 9 games) | 15× | 307× | 5,600× |

Picking the most likely 6+ games lowers their odds, so 3 hits then pay back only a fraction of the stake.

## 2. Your coupon, replayed

| | Every day (485 days) | Every weekend (134 weekends) |
|---|---|---|
| Average odds per game | 9.1 | 6.7 |
| Coupons with 3+ hits | 7.8% | 17.9% |
| Coupons with 4+ hits | 2.1% | 6.7% |
| Coupons with 5+ hits | 0.2% | 1.5% |
| System 3-4-5 result | **−87 per 100** | **−79 per 100** |
| The same games as singles | −30 | −30 |

- **Weekend pool:** picking from the whole weekend (Friday to Monday, about 120 games) instead of one day doubles the chance of 3+ hits. The losses stay the same.
- **Seasons:** in simulations, fewer than 4 in 100 seasons end up.
- **By season (weekend coupon):** −84 / −77 / −67 per 100.

## 3. Ideas I tested to pick better 6+ games (none worked)

| Idea | Result |
|---|---|
| Are 6+ games linked? (same league or same day: weather, refereeing style, a "goal day") | No. Two 6+ games on the same day in the same league happen 0.96× as often as chance predicts (95% range 0.82–1.13); different leagues 0.99×; the same league 7 days apart (check) 1.06×. Goals above expectation: correlation 0.00. |
| League "hot streak": a league scoring more than the odds expect in the last 10 days | Predicts nothing (correlation 0.00; same-price test 0.50). |
| Same-day momentum: earlier games of the day were goal-rich | Predicts nothing. |
| Start of the season: more goals than the odds expect | Not a pattern. 2024/25 Aug–Oct had fewer goals than expected, 2025/26 none; 2026/27 is a one-off. |
| 6+ by league | A league's 6+ return does not carry over to the next season (correlation 0.04–0.30). |
| 6+ odds bands (e.g. only odds 7.50–9) | Every band loses 20–40 per 100. Smaller slices that look better are within luck. |
| Earlier deep dive (SIX_PLUS_REPORT) | 555 signals and 5,168 rules: none beats Nesine's own 6+ odds. |

**Conclusion:** Nesine's 6+ odds are already the best way to rank 6+ games. The problem is the price of the 6+ bet itself.

## 4. The bet matters more than the games
What 1 unit returns over time (hit rate × odds), all matches (chart `six_system_1_bet_value.png`):

| Bet | Odds ≈ | Returns per 1 unit |
|---|---|---|
| **Draw & over 2.5 — Portugal** | 17.2 | **1.57** |
| Draw & over 2.5 — the 7 best other leagues (chosen on earlier seasons, tested on the next) | 13.7 | 0.95 |
| Both teams score in both halves | 16.5 | 0.89 |
| Half-time 1-1 | 8.0 | 0.88 |
| Both teams score | 1.6 | 0.87 |
| Draw & over 2.5 — all leagues | 13.1 | 0.86 |
| Over 2.5 | 1.7 | 0.85 |
| 1st-half over 1.5 | 2.5 | 0.82 |
| 4-5 goals | 3.7 | 0.81 |
| Over 3.5 | 2.9 | 0.79 |
| Draw & over 2.5 — the other 18 leagues | 12.7 | 0.78 |
| Over 4.5 | 5.7 | 0.70 |
| **6+ goals** | 15.3 | **0.68** |

**What the system does to these numbers** (chart `six_system_2_multiplier.png`):
- A size-k combo returns the per-game value to the power k.
- Your 3-4-5 system returns:
  - about −76 per 100 with 6+ (0.71 in your games);
  - −47 per 100 with "draw & over 2.5" in all leagues (0.86);
  - well above zero when the games return more than 1.
- **Below 1 per game, the system sinks faster than singles. Above 1, it climbs faster.**

## 5. Portugal "draw & over 2.5": the one bet where the maths is on your side

| | Bets | Won | Return per 100 |
|---|---|---|---|
| 2024/25 | 298 | 7.7% | +27 |
| 2025/26 | 277 | 10.8% | +65 |
| 2026/27 so far | 70 | 12.9% | +144 |

**It is really a Portugal 2-2 effect.** Of the 62 wins, 53 were 2-2, 8 were 3-3 and 1 was 4-4.
- Portuguese draws are high-scoring for a league with only 2.64 goals a game: 2-2 happens 75% as often as 1-1. In Spain that figure is 28%, in Argentina 18%.
- Nesine prices Portuguese draws as if they were low-scoring: "draw & under 2.5" there returns only 0.51–0.64 per unit.

**It holds wherever I look:**
- 22 different teams;
- every part of the season (returns of 1.29–1.82 per unit);
- every odds band: all bands pooled are at least 1.01 per unit, and each band is at least 0.95 in nearly every season.

It survived every money scan (about 4,200 league × bet combinations and 148,000 condition × bet cells). With shuffled labels, nothing survives.

**Other leagues:**
- The leagues where this bet paid best in earlier seasons keep doing better the next season: 1.00 and 1.19 per unit, against 0.78 for the rest.
- Without Portugal, they are only about break-even (0.92 / 1.05). In shuffled tests this edge looks real (p ≤ 0.06).
- The current list is: Netherlands, Italy Serie B, Brazil, Italy Serie A, Denmark, Scotland, England Premier League.

## 6. The Goals coupon (recipe) and its record
**Recipe** (every weekend, Friday to Monday):
1. Every Portugal game: **"MS X ve 2,5 Üst"**. "MS X ve 3,5 Üst" is the same result (a draw with 4+ goals), so take whichever price is higher.
2. To reach 10 games, add the lowest "draw & over 2.5" odds from the best leagues for this bet (list above).

Record, one coupon per weekend (charts `six_system_3_money.png` and `six_system_4_hits.png`):

| | 2024/25 | 2025/26 | 2026/27 so far |
|---|---|---|---|
| Weekends | 55 | 47 | 11 |
| Average odds per game | 14.3 | 14.1 | 15.1 |
| Games won | 9.8% | 9.6% | 10.9% |
| Return per 1 unit per game | 1.32 | 1.29 | 1.79 |
| Weekends with 3+ hits | 5.5% | 6.4% | 18.2% |
| **Played as singles** | **+32 per 100** | **+29** | **+79** |
| Played as system 3-4-5 | −91 | −71 | +4,573 |

Notes on the table:
- **Leagues:** the extra leagues for 2024/25 were chosen on 2024/25 itself, while 2025/26 and 2026/27 used earlier seasons only.
- **Portugal only (9 games):** singles +30 / +62 / +151. System 3-4-5: −100 / −9 / +13,857. One 4-hit weekend in August 2026 paid 1,637× the stake.
- **Rounds:** in 86 Portugal rounds, 3+ hits came 3 times.

## 7. What if Portugal's edge is smaller than measured?
I replayed the real weekend coupons with smaller edges for Portugal: 30 weekends a season, 4,000 simulated seasons. Portugal's measured return is 1.57 per unit.

**Best honest guess of the real edge:** about **1.00–1.16 per unit**, not 1.57. Part of any league's past return is luck; comparing Portugal with all 26 leagues pulls its 1.57 down to that range. Treat the 1.15 row below as the realistic case.

| Portugal returns | Singles: long run / seasons up | System 3-4-5: long run / seasons up |
|---|---|---|
| 0.86 (no edge) | −14 / 26% | −46 / 5% |
| 1.00 | 0 / 48% | 0 / 7% |
| 1.15 | +15 / 70% | +78 / 12% |
| 1.30 | +30 / 85% | +199 / 19% |
| 1.50 | +50 / 95% | +452 / 29% |

**Even with an edge, the 3-4-5 system ends most seasons down.** It wins big but rarely: a 9-game Portugal coupon needs 3 of 9 high-odds draws. Singles and doubles turn the same edge into a steady result.

## 8. How to play it
1. **The legs:**
   - Play "draw & over 2.5" in Portugal's games, not 6+.
   - If you want more games, add the best-league legs. They are only about break-even, so each one dilutes the edge.
2. **The format:**
   - **Steady:** singles, or doubles, on the Portugal legs.
   - **Your format (3-4-5):** use a small fixed stake every weekend and expect to lose most weekends. The profit comes from the rare 3–4-hit weekend: 3 hits ≈ 5–15×, 4 hits ≈ 85–300× the stake.
   - Never raise the stake to chase.
3. **If you still play 6+:**
   - Pick from the whole weekend: the 10 lowest 6+ odds give the most hits.
   - Know that 3 hits will not return the stake at those odds (about 0.5×).
   - Expect to lose about 80% over time.
4. **Watch the edge:**
   - The tracker replays the Goals coupon every weekend from now on, as stored.
   - Judge it after a full season, not a few weekends.

## Files
- **Excel:** `output/six_system.xlsx`. Sheets: payout table, bet types, every strategy by season, season odds, "if the edge is smaller", Portugal by odds, draw & over 2.5 by league, theory, linked games, momentum, every coupon.
- **Charts:**
  - `output/six_system_1_bet_value.png` (what 1 unit returns per bet);
  - `output/six_system_2_multiplier.png` (how the system multiplies it);
  - `output/six_system_3_money.png` (money curves);
  - `output/six_system_4_hits.png` (chance of 3/4/5 hits and what they pay).
- **Code:**
  - `six_sys_data.py` (dataset);
  - `six_sys_corr.py` (linked games and momentum);
  - `six_sys_backtest.py` (your daily coupon);
  - `six_sys_legs.py` (which bet per game);
  - `six_sys_study.py` (strategies, weekend pooling, Portugal, best leagues, season odds, sensitivity);
  - `six_sys_report.py` (Excel and charts).
- **Strategy book:**
  - `system-goals-coupon` (promising) and `system-6plus-lowest` (info, for comparison);
  - lessons added for everything that did not work.
