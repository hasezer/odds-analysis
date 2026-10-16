# Rule hunt v5: new information sources

Data: our own collection only.
Seasons: 2024/25 + 2024 (find), 2025/26 + 2025 (confirm), 2026/27 + 2026 so far (exam).
Every study is judged by the hit rate needed to break even at Nesine's closing odds and by return per 100 staked, on seasons the method did not see.

| # | Idea (why it could work) | Result |
|---|---|---|
| 1 | **Corners from team statistics** (`v5_corners.py`): corners won/conceded, crosses, shots, possession, home/away; LightGBM, train on earlier seasons only | Predicts total corners as well as Nesine's line, no better: average error 2.68 vs 2.68, correlation with the line 0.85 in 2026/27. Where they disagree the hit rate does rise (51% → 57–64%), but corner bets need 61–70% to break even. Every band loses 3–18%. **No edge; corners carry a ~20% cut.** |
| 2 | **First/second-half habits** (`v5_halves.py`): do "slow starters / late scorers" beat Nesine's half split? | A team's past 1st-half goal surplus vs its next match: correlation −0.004 / −0.010 / −0.026. **Not a real habit.** |
| 3 | **Late-season motivation** (`v5_motivation.py`): league tables rebuilt match by match; relegation fight, title race, nothing to play for; 3 pre-registered hypotheses | No steady effect: motivated team vs nothing to play −18 / +3 / −13; two teams with nothing to play were under-scoring, not over. **The odds already price motivation.** |
| 4 | **Popular-team shading** (`v5_popular.py`): Turkey's big 4 and 12 global giants vs other teams at the same odds | Backing them loses like anyone else. Backing their **opponents** loses 41–56% (vs about 30%): the big clubs beat their odds. **Nesine does not over-price them.** |
| 5 | **All non-odds conditions × all bet types** (`v5_conditions.py`): 915 conditions (form, previous match, last meeting, disagreement, calendar, cut, corners) × 162 bets ≈ 148,000 cells | Kept: only **Portugal draw with 3+ goals**. Shuffled runs: 0, 0, 0, 0, 0. |

## Portugal deep-dive
- **Winning scores:** 2-2 (53), 3-3 (8), 4-4 (1).
- **Spread:** across 22 different teams, so it is league-wide, not a few clubs.
- **Draw shape:** 36% of Portuguese draws are 2-2 or higher, against 28% elsewhere. Nesine prices them as if Portugal were average.
- **Pays even with a big favourite (odds ≤ 1.60):** +86 / +42 / +59 per 100 staked.
- **Status:** still "promising". About 645 matches; long shot at odds ~15. The live tracker follows it.
