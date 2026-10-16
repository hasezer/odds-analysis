# Rule hunt v3: new kinds of information, every bet type

Data: our own Nesine/Mackolik collection only. 20,670 matches.
Seasons: 2024/25 + 2024 (find), 2025/26 + 2025 (confirm), 2026/27 + 2026 so far (exam).

## What was new this time

- **All ~160 bet types Nesine prices** were used as targets (before: 46). This includes corners, team goals, halves and combos.
- **4,298 conditions.** These are the odds conditions from before plus six new kinds:
  - **disagree:** Nesine's chance for a bet vs the chance its *other* markets imply.
  - **form:** each team's last 6 and last 15 matches: goals, shots on target, corners, points, and scoring above or below what the odds expected.
  - **last:** what happened in each team's previous match (score, comeback, 4+ goals…) and in the last meeting of the two teams.
  - **context:** league, part of the season, weekday, kick-off time, month.
  - **margin:** the cut Nesine takes, and how well its main prices fit one goal model.
  - **corners:** expected corners.
- **Two tests.** "Hit": does the bet hit clearly more often than normal? "Price": does it hit more often than Nesine's price says?
- **A luck twin** (the same search on shuffled results) for every test.
- **Team, league and rule-stacking tests.**

Referee data turned out to be empty. Odds movement exists for only 11 settled matches, too few to use.

## Results

1. **Rules can push hit rates far above normal**, but the odds fall just as much.
   - 504,203 hit-rate rules passed find + confirm + exam; with shuffled results, 1,806 passed.
   - Examples: over 2.5 goals goes from 52% to about 78%, and home win from 43% to about 74%.
   - At those odds you still need even more to break even (chart `v3_hit_ceiling.png`).
2. **The new information adds about 1 point.** The best rule per bet averaged 39.7% with odds conditions only, against 40.7% with the new kinds. The odds already contain almost everything.
3. **42 rules hit 80%+ in every season**, e.g. "no over 1.5 in both halves" at 89% and "home team under 2.5 goals" at 87%. All are short-odds bets that still lose 3–8% of the stake (sheet "80%+ rules").
4. **"Price says" is a trap for short odds.** Nesine has minimum odds and loads its cut unevenly, so a favourite can "beat the fair price" by 10 points and still lose money. All tables now show **hit % needed to break even** instead.
5. **Clean test of stacking** (`v3_stacking.png`, sheet "Rule stacking 2026-27"). Rules were picked on 2024/25 + 2025/26 only, then bet on 2026/27.
   - The more rules agree, the more often the bet wins: 22% → 50%.
   - Returns improve only from −25 to −14 per 100.
   - Rules that made money in both earlier seasons lost 20–43% in 2026/27.
   - **No general edge.**
6. **Teams:** no team keeps beating Nesine's price. The real data and the luck twin give the same counts (34 vs 33, 37 vs 32, 44 vs 34).
7. **Leagues: one standout, Portugal.** "Draw with 3+ goals" (2-2, 3-3…) in the Primeira Liga made money in every season. Chart `v3_portugal_draws.png`:

   | Season | Matches | Hit | Needed | Return per 100 |
   |---|---|---|---|---|
   | 2024/25 | 298 | 7.7% | 6.4% | +27 |
   | 2025/26 | 277 | 10.8% | 6.4% | +65 |
   | 2026/27 so far | 70 | 12.9% | 6.2% | +144 |

   - Of ~4,200 league × bet combinations, this is the only one that made money in all three seasons with a return z-score of 2 or more.
   - The luck twin (20 runs) found one such combination in 1 of 20 runs.
   - Promising, not proven. It is a long shot (about 1 match in 10 wins, odds ~15), so long losing runs are normal.

## Files

- `output/rules_v3.xlsx`: Read me, Luck check, Best rules per bet, 80%+ rules, New info vs price-only, Beats Nesine's price, Made money every period, Teams beating price, League x bet winners, League scan luck, Rule stacking 2026-27, Teams luck check.
- `output/v3_portugal_draws.png`, `output/v3_hit_ceiling.png`, `output/v3_stacking.png`.
- Code: `rules_v3_data.py` (conditions), `rules_v3.py` (search; `--keep-ab` for the clean test), `rules_v3_vote.py` (stacking), `rules_v3_teams.py`, `rules_v3_leagues.py`, `rules_v3_study.py` (tables), `rules_v3_charts.py`.

Rebuild:
```
python analysis/rules_v3_data.py
python analysis/rules_v3.py
python analysis/rules_v3.py --keep-ab
python analysis/rules_v3_vote.py
python analysis/rules_v3_teams.py
python analysis/rules_v3_leagues.py
python analysis/rules_v3_study.py
python analysis/rules_v3_charts.py
```
