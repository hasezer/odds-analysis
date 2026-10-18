"""Build the strategy book: every strategy we found, as checkable criteria plus its evidence by season.

Writes analysis/strategies.yaml (read by daily_scan.py) and analysis/STRATEGIES.md (plain language).
Both files are committed: they are the project's memory of what was found; the caches they come from are not.
Every criterion needs only the current Nesine odds of a match (and its league), so the daily scan can check it.

Kinds of strategy (status: proven = held in every season incl. the 2026/27 exam; promising = held every season
but small or not yet proven beyond chance; watch = only seen in 2026/27):
  odds_band   a high-odds bet when its own odds are among the cheapest 5% / 10% of matches     (hi_rank study)
  pack        back the k most likely selections of a market, only in the most predictable matches (packs)
  league      a league that produces a result more often than normal (and than the odds) every season
  odds_rule   readable rule with exact odds cut-offs (decision trees; found 2024/25, confirmed 2025/26)
  watch       2026/27 patterns beyond the odds, not yet proven
  system      a whole coupon for the owner's 10-game system (3-4-5): which games, which bet, and its record per
              season as one coupon per weekend (six_sys_study.py); status info = shown for comparison only
Sources: cache/hi_data.npz, hi_leagues.parquet, hi_trees.parquet, rules_v3_leagues.parquet, six_sys*.parquet.

Nothing is ever lost: a strategy from the previous book that no longer passes is KEPT with status "retired" (date
and reason); every strategy keeps its "first_added" date; each build that changes the book saves a dated copy in
strategy_history/ and adds a line to strategy_history/CHANGELOG.md. LESSONS records what did NOT work.
Live retirements: strategies that monthly_review.py lists in live_review.yaml (live record far below the book's
evidence) are retired the same way, in every rebuild. `python analysis/build_strategy_book.py --live-only` applies
that list to the current book without a rebuild (no caches needed; only statuses change).
"""
import datetime as dt
from pathlib import Path
import re
import sys

import numpy as np
import pandas as pd
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import hi_data  # noqa: E402
from dashboard import leagues  # noqa: E402
from htft_data import CACHE  # noqa: E402
from rule_miner import nice  # noqa: E402
from rules_targets import tr_labels  # noqa: E402

HERE = Path(__file__).resolve().parent
HIST = HERE / "strategy_history"
LIVE = HERE / "live_review.yaml"          # written by monthly_review.py
LESSONS = [
    "No strategy beats Nesine's prices in general: ML on all markets, 21M mined patterns, sure-bet scans, rule "
    "stacking and 'price + corrections' all lost money on unseen seasons (reports: ML_REPORT, MINER_REPORT, "
    "RULES_V3_REPORT). Only exception so far: Portugal draw with 3+ goals (promising).",
    "For hit rate on high-odds bets, the bet's own odds are the best filter (top 1% = 2.8x normal). Machine "
    "learning, rule counts and 'odds + corrections' were all worse on unseen seasons (HIGH_ODDS_REPORT).",
    "Rules raise hit rates 1.5-3x, but the odds fall with them; only ~17% of readable rules beat a plain odds filter "
    "of the same size, and confirmed rules do not hit more than the odds of their own matches predict.",
    "Team-level 'beats the price' effects do not persist from season to season (same count as shuffled data).",
    "League tendencies that beat the normal rate and the goal model every season still LOSE 10-25% at Nesine's real "
    "odds (Argentina draws, MLS away 3+, Bundesliga goals...). Only Portugal draw with 3+ goals made money every "
    "season; Ligue 1 half-time 'away ahead & both scored' is near break-even (+19.6 / -2.5 / -2.7).",
    "Rule hunt v4 (money scans, every bet type x odds band, Nesine's cut, league, weekday, kick-off hour, month, "
    "season stage, rest days, league x odds): nothing made money in all three seasons except Portugal draws with "
    "3+ goals (strongest at odds > 13.95) and a weak La Liga 1-1 slice; shuffled labels give ~0 (RULES_V4_REPORT).",
    "Portugal 'draw & over 2.5' is really a Portugal 2-2 effect: 53 of its 62 wins were 2-2 (8 were 3-3), 22 teams, "
    "every part of the season, every odds band >= 0.95. Portugal draws are high-scoring for its goal rate (2-2 is "
    "75% as common as 1-1; Spain 28%, Argentina 18%) and Nesine prices X & under 2.5 there at 0.51-0.64.",
    "Rule hunt v5 (new information): corners from team corner/cross/shot stats predict exactly as well as Nesine's "
    "line (error 2.68 vs 2.68) and corner bets need 61-70% to break even (lose 8-18%); teams' first/second-half habits "
    "do not persist (correlation ~0); late-season motivation from rebuilt league tables shows no steady effect; "
    "popular teams (Turkey big 4, global giants) are NOT over-priced - their opponents lose 41-56%; a money scan of "
    "915 non-odds conditions x 162 bet types (~148,000 cells) kept only Portugal draw with 3+ goals (shuffled: 0) "
    "(RULES_V5_REPORT).",
    "Every bet type loses over time at Nesine's closing odds: the least bad lose ~11-15 per 100 (both score in both "
    "halves, 1st-half 1-1, BTTS yes, 2nd-half BTTS, low totals); correct scores lose ~47 on average and capped long "
    "shots 55-93; HT/FT ~26; corners ~18 (output/bet_type_returns.xlsx).",
    "Owner's tipster list (16 Oct 2026, tipster_rules.py, output/tipster_rules.xlsx): 21 of 22 rules testable; "
    "many raise the hit rate (e.g. 0-1 goals odds > 4.20 -> over 3.5: 42% vs 30%; HT score 'other' < 5 & score "
    "'other' < 8 -> 6+ goals: 23% vs 6%) but every rule stays below break-even (-8 to -33 per 100); 'all three "
    "half-by-half BTTS bets every game' loses 16%; the only plus (#21, HT/FT 2/1, +88) is 2 wins in 34 matches.",
    "Tipster rule 5 by league (tipster_rule5.py, output/rule5_by_league.xlsx/.png): a higher 'total goals 0-1' price "
    "raises 6+ goals in every league (all leagues: 3.6% at <= 3.50 -> 19-23% above 7.00), but no league x odds range "
    "made money in all three seasons (0 cells; shuffled leagues 0.6). Closest: Switzerland, 0-1 > 5.00: 19% vs "
    "break-even 18% (-0.4 per 100, 126 bets).",
    "6+ goals deep dive (SIX_PLUS_REPORT): Nesine's 6+ price is the best 6+ signal; 555 signals, structure ratios, a "
    "small combined model and 5,168 confirmed threshold rules add nothing beyond it (1 rule beat the cheapest-6+ filter "
    "of the same size). Nesine OVERSTATES 6+ almost everywhere; 6+ loses 22-42 per 100 at every odds level. If you "
    "expect a 6+ game, over 3.5 (-18) or 1st-half over 1.5 (-16) lose far less than 6+ (-29). 75% of 6+ games are "
    "shootouts; 3-3 is the most common 6+ score.",
    "System coupons (owner's 10 games, system 3-4-5; SIX_SYSTEM_REPORT): a combo returns the PRODUCT of its games' "
    "returns, so the cut is multiplied. 6+ returns ~0.70 per unit in the games a 6+ player picks, so 10 lowest-6+ "
    "coupons lost 87% (daily) / ~80% (weekend pool); 0 of 20,000 simulated seasons ended up. Picking from the whole "
    "weekend doubles the chance of 3+ hits (8% -> 15-18% of coupons) but not the return; at those odds (~7-8) 3 hits "
    "only gives the stake back.",
    "6+ games are NOT linked between matches (same league same day: joint 6+ lift 0.96, different leagues 0.99, "
    "placebo 7 days apart 1.06; goal-residual correlation ~0); league 'hot streaks' and same-day momentum predict "
    "nothing (correlation ~0, beyond-price AUC ~0.5) -> no correlated-combo edge for system coupons.",
    "Which bet per game matters more than which games: in the same 10 games, 'draw & over 2.5' returns ~0.9 per "
    "unit vs ~0.7 for 6+; over 3.5 / 1st-half over 1.5 / 4-5 goals ~0.82; BTTS ~0.86. Within a bet type, odds "
    "bands that look better (e.g. draw & over 2.5 at 14-19) are not beyond luck (no-edge twin gives as many).",
    "6+ value by league does not persist (season-to-season correlation 0.04-0.30); 'draw & over 2.5' value by "
    "league does (8 best leagues of earlier seasons: 1.00 / 1.19 next season vs 0.78 for the rest; without "
    "Portugal 0.92 / 1.05; shuffled leagues p <= 0.06) - Portugal is the only league clearly above 1.",
    "Both teams score in both halves (1. Yari / 2. Yari KG Evet/Evet; data only since Nov 2025, 7,190 games): 6.2% "
    "won, 0.89 back per unit overall; the most likely games (odds <= 10) return only 0.59-0.74, odds 12-20 return "
    "0.91-1.04. The tipster way (3 lowest odds of the day) returned 0.77 per unit; as daily trebles 1 win in 254 days. "
    "One season only: not confirmed. Outside tipsters' picks are graded in tipster_log.csv / tipster_log.py.",
    "HT/FT deep dive 2 (HTFT2_REPORT, favourite's side): every HT/FT result loses at every favourite strength "
    "(0.41-0.89 back per unit; least bad: favourite ahead at HT & wins with a 70%+ favourite, 0.84). After each "
    "half-time state Nesine's HT/FT gives the UNDERDOG 1-10 points too much, so the underdog's results lose most. "
    "180 result x favourite x goals cells + 86 own-odds deciles + 45 result x favourite cells: 1 cell at break-even "
    "in 2024/25 and 2025/26 (luck twin 1.1 on average) - kept as a watch lead. Nesine's most likely HT/FT result "
    "happens as often as it says (63% vs 55% when it says 50%+). The 2nd-half share of goals is priced right (55.5% "
    "vs 56.0%) and no league keeps scoring late (season-to-season correlation -0.42 / 0.48 / -0.28). First-half "
    "goals barely change the chance of 2nd-half goals; the pre-match goal odds do.",
    "Half-time ideas are cheaper outside the HT/FT market: both score in both halves 0.89, half-time 1-1 0.88, both "
    "score in the 2nd half 0.87, 1st half over 0.5 0.86, 2nd-half draw / favourite wins 2nd half 0.84 per unit, "
    "against 0.63-0.76 for HT/FT results. Portugal HT/FT X/X loses 18-39% (its draws are high-scoring).",
    "HT/FT 1/X, 2/X, X/1, X/2, 1/2, 2/1 (HTFT3_REPORT, hit rate only): the result's own HT/FT odds are the sign. "
    "In a fair race (each technique picks 1 game in 10 per season, 2025/26 + 2026/27) the own odds give X/1 1.4x, "
    "X/2 1.8x, 1/2 1.6x, 2/1 1.3x, 1/X 1.0x, 2/X 1.2x normal; an HT/FT price rebuilt from Nesine's other markets, "
    "the best of ~390 other signs and logistic regression rank games the same way; boosted trees, team comeback / "
    "blown-lead habits, league history and calendar do worse. The best 2-condition rules (~28,000 per result, "
    "luck-controlled) hit no more often than the same number of lowest-odds games. 1/X and 2/X (leader pegged back "
    "to a draw) can't be picked (~5-7%). Compare techniques on the same number of games: groups of different sizes "
    "made the other markets look useful for 1/2 and 2/1.",
    "Correct scores: Nesine listed them for only 33% of 2025/26 matches (99% in 2024/25, 93% in 2026/27), and its "
    "correct-score odds got longer after 2024/25 (sum of 1/odds 1.60 -> 1.50). Fixed odds cut-offs on scores stop "
    "firing (2-1 odds <= 6.75: 441 games in 2024/25, 1 in each later season); use the normalised chance.",
    "Both teams score in both halves (BB_REPORT, hit rate only): the sign is how many goals BOTH teams are expected "
    "to score (it needs 4+ goals; 2-2 and 3-2 most often). Fair race (each technique picks its top 5% of games per "
    "season, 2025/26 + 2026/27): a model from Nesine's goal markets 1.9x normal (11.7%; top 2%: 12.9%), Nesine's own "
    "both-halves price the same, BTTS-yes chance and logistic regression the same; boosted trees, team habits "
    "(scoring in both halves), a statistics-only team model, league history (its extra beyond the model does not "
    "carry over: corr 0.04) and calendar do worse. The best rules (e.g. BTTS yes <= 1.36 & 1st-half under 1.5 >= "
    "1.49: 12.3/10.7/10.9%) hit the same. The halves are almost independent: after 1st-half BTTS, 2nd-half BTTS "
    "28% (21-33% by pre-match 2nd-half goal expectation). The cheapest both-halves odds (<= 8.34) lose 16-28 per 100.",
    "HT_BTTS / 2H_BTTS: the NO side is missing for ~45% of matches, so their 'fair' chance exists only for a biased "
    "subset; use the YES odds. Label-swapped HT_2H_BTTS prices show YES/YES at 1.10-2.02 (real ones 4.66+): a "
    "YES/YES odds floor of 4 screens them out.",
    "Correct scores (cs_study.py; 35 full- and half-time scores, 0-5/0-6/1-5/6-0 too rare): Nesine's own score "
    "chance and a goal-markets model rank games the same for every score. Fair race (top 5% of games, 2025/26 + "
    "2026/27): 0-0 2.2x, 1-0 1.9x, 0-1 1.9x, 2-0 2.0x, 3-0 3.6x, 0-3 2.9x, 4-0 3.6x normal, but 1-1 1.5x, 2-1 1.7x, "
    "1-2 1.6x, 2-2 1.3x, 3-2 1.1x; half time 0-0 1.6x, 1-0 1.5x, 0-1 1.7x, 2-0 2.1x, 0-2 2.9x, 1-1 1.1x. One-sided "
    "scores can be picked, level and middle scores hardly. The best 2-condition rules beat luck for most scores but "
    "matched or beat the plain price on the same games only for 0-0, 0-2, 1-3, 3-1 and HT 0-1, 1-0, 1-2, 2-2, other.",
    "Correct scores, no help beyond the price: team score habits (draw, 0-0, 1-1, low-scoring and half-time-draw rates, "
    "last 20 and previous season), league x score tendencies (20 of 1,014 pairs beat normal and the price every "
    "season; shuffled leagues give ~10, 95th pct 17), calendar.",
    "Correct-score prices: 2-1, 1-2, 2-2 (full time) and 1-1 (half time) happen 10-20% more than Nesine's evenly "
    "spread chance and lose least (-25 to -28 per 100; half-time 1-1 -12); scores with a 5-6 goal side happen 2-5x "
    "less than priced (-60 to -92 per 100). Every score loses at closing odds.",
    "Live, half time -> full time: the half-time score is the final score ~20% of the time (0-0 24%): 27-29% when few "
    "2nd-half goals were expected before kick-off (bottom third), 15-18% when many. Half-time 2-0 ends 3-0 (19%) more "
    "often than 2-0 (17%); half-time 1-1 ends 1-1 21%, 2-1 19%, 1-2 15%.",
    "High-scoring correct scores 3-2, 2-3, 3-3, 2-4, 4-2 (cs_high.py, focused second pass): Nesine's own score "
    "chance, the goals model and the markets that describe them (result & over 4.5, both teams 2+, 4-5 / 6+ goals) "
    "pick the same games. 3-3, 2-4, 4-2 reach 2.5-4x normal on their top 5% (from 1-1.5% to ~4%), 3-2 and 2-3 only "
    "1.1-1.7x. Rules: 3-2 and 2-3 stored (1.3-1.7x in later seasons); 3-3 rules collapsed in 2026/27 (0 winners in "
    "197 games); 2-4 and 4-2 too few winners. The three most likely of the five together in the top 5% of games: "
    "11.8 / 8.7 / 11.0% vs 6-7% every game (stored; -31 to -39 per 100). Live: after half-time 2-2 the game ends 2-3 "
    "17%, 3-2 16%, 3-3 11%, 4-2 8%; after 2-1, 3-2 12%; after 1-2, 2-3 12%.",
    "How teams play vs their results (perf_study.py; team match statistics, last 10 matches): shots, shots on "
    "target, possession, corners and 'luck' (goals minus what the shots on target were worth at the league's rate) "
    "add nothing beyond Nesine's price for home win, draw, away win, over/under 2.5 and BTTS: out-of-sample log-loss "
    "gain about 0 (-1.1 to +0.9 per 1,000), the same AUC. The 5-10% of games where the stats disagree most with the "
    "price beat shuffled stats in 2 of 28 checks, neither repeating in the other season; Nesine's cut leaves at most "
    "9 bets a season with a 5% edge. Backing the 'unlucky' side (results far below its shots) hits exactly its fair "
    "chance (home 35-38% vs 34-37%, away 19-23% vs 24-26%): -13 to -31 per 100.",
    "Corners, second pass (corners_study.py; first pass v5_corners.py): Nesine's corner cut is 21-22% on every line "
    "(8.5-12.5) and corners are mostly noise (Nesine's expected corners correlate 0.16 with the real total, team "
    "habits 0.14, goal expectation 0.13). Nesine's line already blends team corner habits (corr 0.69), the league "
    "average (0.71) and goal expectation (0.48). Fair race (top 10% of games, 2025/26 + 2026/27): Nesine's own corner "
    "chance picks best or ties (over 8.5 67%, over 9.5 59%, under 10.5 66%); team habits, same-venue habits, "
    "favourite strength and a fitted 'price + all signs' model add nothing beyond shuffled-sign luck. Low goal "
    "expectation picks under 9.5 / 10.5 corners about as well (61% / 69%) and loses least (-7 to -12 per 100). All 99 "
    "price bands with 300+ bets lose 9-30 per 100; no corner strategy is stored.",
    "Own play (own_play.py; every pick since July 2025 at closing odds, 1 stake each, 5,000 simulated years): the "
    "hit-rate strategies lose steadily when bet flat: both teams score in both halves -25 per 100 (38 picks a month, "
    "a typical year -110 stakes, a 1-in-20 losing run of 61, bankroll ~200 stakes), the high-scoring score pack -38, "
    "correct-score bands and rules -27, every single-bet strategy together -23. Portugal draw & over 2.5 singles "
    "+81 per 100 (23 a month, ahead in 99% of simulated years, losing runs up to ~50, bankroll ~60 stakes; found on "
    "these same seasons, so the tracker must confirm it). The Goals coupon as a 3-4-5 system is a lottery: one weekend "
    "in 104 since Aug 2024 (7 Aug 2026, 512x the stake) decides it; without it -80%; 37% chance to end a year ahead.",
    "6+ goal 'waves' (six_waves.py; 19,810 games, 141 weeks; luck control: every game redrawn 2,000 times from its "
    "own 6+ price): the weekly NUMBER of 6+ games follows the number of matches played (correlation 0.86; "
    "international-break weeks 25-60 matches, busy weeks 250+), while the SHARE stays at what Nesine's prices expect "
    "(6.3%). Week-to-week swings are within luck (p 0.11); no cycle of 1-10 weeks beyond luck (strongest: 5-6 weeks, "
    "p 0.06-0.08; as a signal, 5 weeks after a hot week gave 0.94 / 1.11 / 1.08x expected); no waves inside a league; "
    "after international breaks 0.97 / 1.51 / 0.94x; weeks 3-4 of the month 1.07 / 1.15 / 0.97x. 6+ bets lose 32 per "
    "100 at closing odds.",
    "No early-season goal surplus: 2024/25 Aug-Oct had fewer goals than the odds expected and 2025/26 ~0; the "
    "2026/27 surplus (mostly August) is a one-off.",
    "Team form, last match, market disagreement, calendar and Nesine's cut add only ~1 point of hit rate over odds.",
    "'Fair price' with the cut spread evenly is biased for short odds (Nesine has minimum odds): judge rules by the "
    "hit rate needed to break even at the odds paid, not by the 'fair' chance.",
    "2026/27 (so far) has more goals than the odds expect in all leagues; it is not a yearly pattern (no month repeats "
    "it in 2024/25 or 2025/26). Remove this drift before calling a rule 'beyond the odds'.",
    "Data traps: HT_2H_BTTS prices are label-swapped for 211 matches in Oct-Nov 2025 (excluded); 37 TUR-1 'macko*' "
    "placeholder fixtures (excluded); referee data is empty; odds movement exists for only ~11 settled matches.",
]
PER = {"A": "2024/25", "B": "2025/26", "C": "2026/27"}


def stats(y, m, per, odds=None):
    out = {}
    for p, nm in PER.items():
        mp = m & (per == p) & ~np.isnan(y)
        base = (per == p) & ~np.isnan(y)
        out[nm] = {"matches": int(mp.sum()), "hit_pct": round(float(y[mp].mean() * 100), 1) if mp.sum() else None,
                   "normal_pct": round(float(y[base].mean() * 100), 1)}
        if odds is not None:
            mo = mp & ~np.isnan(odds)
            out[nm]["avg_odds"] = round(float(np.nanmean(odds[mo])), 2) if mo.sum() else None
    return out


def holds(st, lift=1.3, min_c=30):
    s = list(st.values())
    return all(x["hit_pct"] is not None and x["hit_pct"] >= lift * x["normal_pct"] for x in s) and \
        s[-1]["matches"] >= min_c


def odds_bands(d, trn):
    per, O, Y = d["per"], d["O"], d["Y"]
    AB = np.isin(per, ["A", "B"])
    out = []
    for j, (tn, tk, ti) in enumerate(zip(d["tnames"], d["tkeys"], d["tprice"])):
        if ti < 0 or (~np.isnan(O[AB, ti])).mean() < .5:
            continue
        o, y = O[:, ti], Y[:, j]
        ok = ~np.isnan(o) & ~np.isnan(y)
        for share in (.05, .10):
            thr = float(np.round(np.nanquantile(o[AB & ok], share), 2))
            m = ok & (o <= thr)
            st = stats(y, m, per, o)
            if not holds(st):
                continue
            out.append({"id": f"band-{tk}-{int(share * 100)}", "kind": "odds_band", "status": "proven",
                        "bet": tk, "bet_name": tn, "bet_name_tr": trn.get(tk, tn),
                        "criteria": [{"bet": tk, "op": "<=", "odds": thr}],
                        "summary": f"{tn} when its odds are ≤ {thr:.2f} (cheapest {int(share * 100)}% of matches)",
                        "evidence": st})
    return out


def packs(d):
    per, O, F, Y = d["per"], d["O"], d["F"], d["Y"]
    names, tk = list(d["names"]), list(d["tkeys"])
    AB = np.isin(per, ["A", "B"])
    out = []
    for gname, pre, k in (("Correct score", "CORRECT_SCORE|", 3), ("Correct score", "CORRECT_SCORE|", 2),
                          ("1st-half score", "HT_CORRECT_SCORE|", 3), ("HT/FT", "HT_FT|", 2)):
        ks = [x for x in tk if x.startswith(pre)]
        ti, oi = [tk.index(x) for x in ks], [names.index(x) for x in ks]
        P, Yk, Ok = F[:, oi], Y[:, ti], O[:, oi]
        ok = ~np.isnan(Yk).any(1) & (np.isnan(P).mean(1) < .5)
        order = np.argsort(-np.nan_to_num(P, nan=-1), axis=1)[:, :k]
        pp = np.take_along_axis(np.nan_to_num(P), order, 1).sum(1)
        hit = np.take_along_axis(Yk, order, 1).max(1)
        eff = 1 / (1 / np.take_along_axis(Ok, order, 1)).sum(1)
        for share in (.10, .30):
            thr = float(np.round(np.nanquantile(pp[AB & ok], 1 - share), 4))
            m = ok & (pp >= thr)
            st = stats(hit, m, per, eff)
            for p in st.values():                         # "normal" for a pack = the same pack in every match
                p["normal_pct"] = None
            allm = stats(hit, ok, per, eff)
            for nm in st:
                st[nm]["every_match_pct"] = allm[nm]["hit_pct"]
            out.append({"id": f"pack-{pre.rstrip('|')}-{k}-{int(share * 100)}", "kind": "pack", "status": "proven",
                        "market": pre.rstrip("|"), "k": k, "min_pack_chance": thr,
                        "selections": [x for x in ks],
                        "summary": f"{gname}: back the {k} most likely together, only when they add up to "
                                   f"≥ {thr * 100:.1f}% (top {int(share * 100)}% most predictable matches)",
                        "evidence": st})
    return out


def league_items(d, trn, lgn):
    out = []
    lg = pd.read_parquet(CACHE / "hi_leagues.parquet")
    lg["beyond"] = (lg["hit_A"] > lg["model_A"]) & (lg["hit_B"] > lg["model_B"]) & (lg["hit_C"] > lg["model_C"])
    name2key = dict(zip(d["tnames"], d["tkeys"]))
    for r in lg[lg["beyond"] & lg["held_in_C"]].itertuples():
        key = name2key[r.target]
        st = {PER[p]: {"matches": int(getattr(r, f"matches_{p}")), "hit_pct": round(getattr(r, f"hit_{p}"), 1),
                       "normal_pct": round(getattr(r, f"normal_{p}"), 1),
                       "odds_say_pct": round(getattr(r, f"model_{p}"), 1)} for p in "ABC"}
        if key in list(d["names"]):                      # what it paid at Nesine's actual odds, per season
            i = list(d["names"]).index(key)
            y, o = d["Y"][:, list(d["tkeys"]).index(key)], d["O"][:, i]
            for p in "ABC":
                mm = (d["league"].astype(str) == r.league) & (d["per"] == p) & ~np.isnan(o) & ~np.isnan(y)
                if mm.sum():
                    st[PER[p]]["return_per_100"] = round(float((y[mm] * o[mm] - 1).mean() * 100), 1)
        out.append({"id": f"league-{r.league}-{key}", "kind": "league", "status": "promising", "league": r.league,
                    "league_name": lgn.get(r.league, {}).get("en", r.league), "bet": key, "bet_name": r.target,
                    "bet_name_tr": trn.get(key, r.target),
                    "summary": f"{lgn.get(r.league, {}).get('en', r.league)}: {r.target} — above normal AND above "
                               f"what the odds say, every season",
                    "evidence": st})
    pt = pd.read_parquet(CACHE / "rules_v3_leagues.parquet")
    for r in pt.drop_duplicates("league").itertuples():
        st = {PER[p]: {"matches": int(getattr(r, f"matches_{p}")), "hit_pct": round(getattr(r, f"hit_{p}"), 1),
                       "return_per_100": round(getattr(r, f"return_per_100_{p}"), 1)} for p in "ABC"}
        out.append({"id": f"money-{r.league}-{r.bet_key}", "kind": "league", "status": "promising",
                    "league": r.league, "league_name": lgn.get(r.league, {}).get("en", r.league), "bet": r.bet_key,
                    "bet_name": r.bet, "bet_name_tr": trn.get(r.bet_key, r.bet),
                    "summary": f"{lgn.get(r.league, {}).get('en', r.league)}: {r.bet} — made money in every "
                               f"season (only league x bet out of ~4,200 to do so)",
                    "evidence": st})
    return out


COND = [(re.compile(r"^(.*) odds (≤|>) ([\d.]+)$"), "odds"),
        (re.compile(r"^Nesine's chance for (.*) (≤|>) ([\d.]+)%$"), "chance"),
        (re.compile(r"^Nesine's cut on (.*) (≤|>) ([\d.]+)%$"), "cut")]


def parse_rule(text, nice2key):
    out = []
    for part in text.split("  AND  "):
        for rx, kind in COND:
            m = rx.match(part)
            if m:
                what, op, v = m.group(1), "<=" if m.group(2) == "≤" else ">", float(m.group(3))
                if kind == "cut":
                    out.append({"cut": what, "op": op, "pct": v})
                elif what in nice2key:
                    out.append({"bet": nice2key[what], "op": op, ("odds" if kind == "odds" else "chance_pct"): v})
                else:
                    return None
                break
        else:
            return None                    # needs form / disagreement / other data: not checkable from odds alone
    return out


def tree_rules(d, trn):
    f = CACHE / "hi_trees.parquet"
    if not f.exists():
        return []
    t = pd.read_parquet(f)
    nice2key = {nice(n): n for n in d["names"]}
    name2key = dict(zip(d["tnames"], d["tkeys"]))
    t = t[(t["matches_C"] >= 30) & (t["hit_C"] >= 1.3 * t["normal_C"]) & (t["hit_A"] >= 1.3 * t["normal_A"])]
    out = []
    for tn, g in t.sort_values("hit_B", ascending=False).groupby("target"):
        n = 0
        for r in g.itertuples():
            crit = parse_rule(r.rule, nice2key)
            if not crit:
                continue
            st = {PER[p]: {"matches": int(getattr(r, f"matches_{p}")), "hit_pct": round(getattr(r, f"hit_{p}"), 1),
                           "normal_pct": round(getattr(r, f"normal_{p}"), 1)} for p in "ABC"}
            st["2026/27"]["odds_say_pct"] = round(r.odds_say_C, 1)
            st["2026/27"]["odds_filter_same_size_pct"] = round(r.odds_filter_same_size_C, 1)
            key = name2key[tn]
            out.append({"id": f"tree-{key}-{n}", "kind": "odds_rule", "status": "proven", "bet": key, "bet_name": tn,
                        "bet_name_tr": trn.get(key, tn), "criteria": crit, "summary": f"{tn} when {r.rule}",
                        "evidence": st})
            n += 1
            if n == 3:
                break
    return out


def v4_items(trn, lgn):
    """Rule hunt v4 (money scans): league + odds-range cells that made money in every season."""
    f = CACHE / "rules_v4.parquet"
    if not f.exists():
        return []
    r = pd.read_parquet(f)
    out = []
    cells = {("1X2_AND_OU|2.5|X&OVER", "POR-1"): (">", 13.95, "promising"),
             ("OU_AND_BTTS|2.5|UNDER&YES", "ESP-1"): ("range", (5.61, 6.48), "watch")}
    for (key, league), (op, thr, status) in cells.items():
        g = r[(r["bet_key"] == key) & (r["dimension"] == "league_x_odds") &
              r["cell"].str.startswith(lgn.get(league, {}).get("en", league))]
        if not len(g):
            continue
        x = g.iloc[0]
        crit = [{"bet": key, "op": ">", "odds": thr}] if op == ">" else \
            [{"bet": key, "op": ">", "odds": thr[0]}, {"bet": key, "op": "<=", "odds": thr[1]}]
        rng = f"odds > {thr:.2f}" if op == ">" else f"odds {thr[0]:.2f}–{thr[1]:.2f}"
        st = {PER[p]: {"matches": int(x[f"bets_{p}"]), "hit_pct": round(float(x[f"hit_{p}"]), 1),
                       "return_per_100": round(float(x[f"return_per_100_{p}"]), 1)} for p in "ABC"}
        note = "" if status == "promising" else " — but the same market loses in La Liga overall (-10/-3/-9): " \
                                                "likely a slicing artefact"
        out.append({"id": f"v4-{league}-{key}-{rng}", "kind": "league_rule", "status": status, "league": league,
                    "league_name": lgn.get(league, {}).get("en", league), "bet": key, "bet_name": nice(key),
                    "bet_name_tr": trn.get(key, nice(key)), "criteria": crit,
                    "summary": f"{lgn.get(league, {}).get('en', league)}: {nice(key)} when its {rng} — made money "
                               f"in every season{note}",
                    "evidence": st})
    return out


between = lambda k, lo, hi: [{"bet": k, "op": ">=", "odds": lo}, {"bet": k, "op": "<=", "odds": hi}]
TIPSTER = [  # (rule name in tipster_rules.py, id suffix, criteria, bet)
    ("1. Home or away odds 1.81-1.90 -> both teams score: yes", "1",
     [{"any": [between("1X2||1", 1.81, 1.90), between("1X2||2", 1.81, 1.90)]}], "BTTS||YES"),
    ("3. 1st-half BTTS yes ~ half-by-half 'No/Yes' (within 0.10) -> 1st-half BTTS yes", "3",
     [{"near": ["HT_BTTS||YES", "HT_2H_BTTS||NO/YES"], "tol": 0.10}], "HT_BTTS||YES"),
    ("6. Total goals 4-5 odds 2.75-3.10 -> over 3.5", "6a", between("GOAL_RANGE||4-5", 2.75, 3.10), "OU|3.5|OVER"),
    ("6. Total goals 4-5 odds 2.75-3.10 -> 1st-half over 1.5", "6b", between("GOAL_RANGE||4-5", 2.75, 3.10),
     "HT_OU|1.5|OVER"),
    ("7. Total goals 0-1 odds > 4.20 -> over 3.5", "7", [{"bet": "GOAL_RANGE||0-1", "op": ">", "odds": 4.20}],
     "OU|3.5|OVER"),
    ("8. Total goals 2-3 odds 1.80-2.00 -> total goals 2-3", "8", between("GOAL_RANGE||2-3", 1.80, 2.00),
     "GOAL_RANGE||2-3"),
    ("9. 1st-half score 'other' < 5 & score 'other' < 8 -> over 3.5", "9a",
     [{"bet": "HT_CORRECT_SCORE||OTHER", "op": "<", "odds": 5}, {"bet": "CORRECT_SCORE||OTHER", "op": "<", "odds": 8}],
     "OU|3.5|OVER"),
    ("9. 1st-half score 'other' < 5 & score 'other' < 8 -> 6+ goals", "9b",
     [{"bet": "HT_CORRECT_SCORE||OTHER", "op": "<", "odds": 5}, {"bet": "CORRECT_SCORE||OTHER", "op": "<", "odds": 8}],
     "GOAL_RANGE||6+"),
    ("11. Over 4.5 ~ both halves over 1.5 (within 0.20) -> 6+ goals", "11",
     [{"near": ["OU|4.5|OVER", "BOTH_HALVES_OVER|1.5|YES"], "tol": 0.20}], "GOAL_RANGE||6+"),
    ("12. 1st-half home/away lead & both scored < 8 -> both halves over 1.5", "12",
     [{"any": [[{"bet": "HT_1X2_AND_HT_BTTS||1&YES", "op": "<", "odds": 8}],
               [{"bet": "HT_1X2_AND_HT_BTTS||2&YES", "op": "<", "odds": 8}]]}], "BOTH_HALVES_OVER|1.5|YES"),
    ("13. 1st-half score 2-2 odds < 38 -> 1st-half BTTS yes", "13",
     [{"bet": "HT_CORRECT_SCORE||2-2", "op": "<", "odds": 38}], "HT_BTTS||YES"),
    ("14. BTTS no odds > 2.20 -> BTTS yes", "14", [{"bet": "BTTS||NO", "op": ">", "odds": 2.20}], "BTTS||YES"),
    ("16. A team's odds exactly 1.65 / 1.67 / 1.75 -> that team wins the 1st half", "16h",
     [{"bet": "1X2||1", "op": "in", "values": [1.65, 1.67, 1.75]}], "HT_1X2||1"),
    ("16. A team's odds exactly 1.65 / 1.67 / 1.75 -> that team wins the 1st half", "16a",
     [{"bet": "1X2||2", "op": "in", "values": [1.65, 1.67, 1.75]}], "HT_1X2||2"),
    ("19. Draw & under 2.5 odds 2.86-2.99 -> HT/FT X/X", "19", between("1X2_AND_OU|2.5|X&UNDER", 2.86, 2.99),
     "HT_FT||X/X"),
    ("20. Home 2.04-2.77 & away 2.64-2.77 -> HT/FT 1/2", "20", between("1X2||1", 2.04, 2.77) + between("1X2||2", 2.64,
                                                                                                    2.77), "HT_FT||1/2"),
]


def tipster_items(trn):
    """The owner's tipster rules that raised the hit rate: above normal in EVERY season and >= 15% above overall."""
    f = CACHE / "tipster_rules.parquet"
    if not f.exists():
        return []
    r = pd.read_parquet(f)
    names = {"2024/25": "2024/25", "2025/26": "2025/26", "2026/27": "2026/27"}
    out = []
    for name, suffix, crit, bet in TIPSTER:
        g = r[r["rule"] == name].set_index("period")
        if "all" not in g.index or g.loc["all", "matches"] < 50:
            continue
        seasons = [p for p in names if p in g.index and g.loc[p, "matches"] > 0]
        held = all(g.loc[p, "hit_pct"] > g.loc[p, "normal_pct"] for p in seasons)
        if not held or g.loc["all", "hit_pct"] < 1.15 * g.loc["all", "normal_pct"]:
            continue
        st = {p: {"matches": int(g.loc[p, "matches"]), "hit_pct": round(float(g.loc[p, "hit_pct"]), 1),
                  "normal_pct": round(float(g.loc[p, "normal_pct"]), 1),
                  "return_per_100": round(float(g.loc[p, "return_per_100"]), 1)} for p in seasons}
        text = name.split(". ", 1)[1]
        if suffix in ("16h", "16a"):
            text = text.replace("A team's odds", "Home team's odds" if suffix == "16h" else "Away team's odds") \
                .replace("that team", "home" if suffix == "16h" else "away") + " (record: home and away together)"
        out.append({"id": f"tipster-{suffix}", "kind": "tipster", "status": "proven", "bet": bet, "bet_name": nice(bet),
                    "bet_name_tr": trn.get(bet, nice(bet)), "criteria": crit,
                    "summary": f"Tipster rule {suffix}: {text}", "evidence": st})
    return out


def watch_items(trn):
    return [{
        "id": "watch-ht02-away-fav", "kind": "watch", "status": "watch", "bet": "HT_CORRECT_SCORE||0-2",
        "bet_name": "1st-half score 0-2", "bet_name_tr": trn.get("HT_CORRECT_SCORE||0-2", "İY skor 0-2"),
        "criteria": [{"bet": "1X2_AND_OU|4.5|2&UNDER", "op": "<=", "odds": 2.01},
                     {"bet": "HT_FT||1/1", "op": ">", "odds": 5.83}],
        "summary": "1st-half score 0-2 when Result & goals away & under 4.5 odds ≤ 2.01 AND HT/FT 1/1 odds > 5.83 "
                   "(strong away favourite)",
        "evidence": {"2025/26": {"matches": 173, "hit_pct": 9.2, "normal_pct": 4.4},
                     "2026/27": {"matches": 167, "hit_pct": 16.8, "normal_pct": 4.4, "odds_say_pct": 10.1}}}]


XO = ["1X2_AND_OU|2.5|X&OVER", "1X2_AND_OU|3.5|X&OVER"]   # the same result (draw with 4+ goals): take the higher price


def system_items():
    """The owner's 10-game system (3-4-5): the recommended 'Goals coupon' and his 6+ coupon for comparison."""
    f, fc = CACHE / "six_sys.parquet", CACHE / "six_sys_study_coupons.parquet"
    if not f.exists() or not fc.exists():
        return []
    import six_sys_study as ss
    S = pd.read_parquet(f)
    C = pd.read_parquet(fc)
    C = C[(C["windows"] == "weekend / midweek") & (C["window kind"] == "weekend")]
    top = ss.xo_leagues(S, ["A", "B", "C"])

    def evidence(strategy, leg):
        g = C[(C["strategy"] == strategy) & (C["leg"] == leg)]
        out = {}
        for p, nm in PER.items():
            x = g[g["season"] == nm]
            if not len(x):
                continue
            st = x[["stake 3", "stake 4", "stake 5"]].sum(axis=1)
            ret = x[["return 3", "return 4", "return 5"]].sum(axis=1)
            out[nm] = {"coupons": len(x), "games_per_coupon": round(float(x["legs"].mean()), 1),
                       "avg_odds": round(float(x["avg odds"].mean()), 2),
                       "hit_pct": round(float(x["hits"].sum() / x["legs"].sum() * 100), 1),
                       "return_per_unit_per_game": round(float((x["leg value"] * x["legs"]).sum() / x["legs"].sum()), 3),
                       "coupons_3plus_hits_pct": round(float((x["hits"] >= 3).mean() * 100), 1),
                       "coupons_4plus_hits_pct": round(float((x["hits"] >= 4).mean() * 100), 1),
                       "return_per_100": round(float((x["return 1"].sum() / x["stake 1"].sum() - 1) * 100), 1),
                       "system_345_return_per_100": round(float((ret.sum() / st.sum() - 1) * 100), 1)}
        return out

    d6 = S[S["o6"].notna()]
    bins = [0, 4.5, 6, 7.5, 9, 11, 14, 20, 1000]
    lad = d6.groupby(pd.cut(d6["o6"], bins), observed=True).apply(lambda g: (g["y6"] * g["o6"]).mean())
    ladder6 = [[float(b.right), round(float(v), 3)] for b, v in lad.items()]
    return [
        {"id": "system-goals-coupon", "kind": "system", "status": "promising", "name": "Goals coupon",
         "bet": XO[0], "bet_name": "Result & goals X & over 2.5 (draw with 4+ goals: 2-2, 3-3 ...)",
         "bet_name_tr": "MS ve 2,5 Alt/Üst: X ve Üst",
         "summary": "Goals coupon for your 10-game system (3-4-5), every weekend (Fri-Mon): every Portugal game as "
                    "'draw & over 2.5' (MS X ve 2,5 Üst), then the lowest 'draw & over 2.5' odds from the leagues "
                    "where it paid best, up to 10 games. Same result under 'X & over 3.5': take the higher price.",
         "window": "weekend", "legs": 10, "sizes": [3, 4, 5],
         "groups": [{"name": "Portugal", "leagues": ["POR-1"], "bets": XO, "value_for_chances": 1.15},
                    {"name": "best leagues for this bet", "leagues": [x for x in top if x != "POR-1"], "bets": XO,
                     "value_for_chances": 0.90}],
         "note": "Portugal returned 1.57 per unit on this bet over all seasons (1.28 / 1.65 / 2.44); chances shown "
                 "in the scan assume only 1.15 (Portugal) and 0.90 (others). As a 3-4-5 system it is a lottery: "
                 "3+ hits in ~4-8% of weekends; singles were profitable in every season.",
         "evidence": evidence("Portugal first, then 8 best 'draw & over 2.5' leagues, lowest odds",
                              "draw & over 2.5"),
         "evidence_portugal_only": evidence("Portugal only (all its games in the window, 3-10)", "draw & over 2.5")},
        {"id": "system-6plus-lowest", "kind": "system", "status": "info", "name": "Your 6+ coupon (for comparison)",
         "bet": "GOAL_RANGE||6+", "bet_name": "Total goals 6+", "bet_name_tr": "Toplam Gol Aralığı: 6+",
         "summary": "Your 6+ coupon, for comparison: the 10 lowest 6+ odds of the weekend (all 26 leagues), 6+ on "
                    "each, system 3-4-5. Loses ~80% over time: 6+ returns only ~0.70 per unit.",
         "window": "weekend", "legs": 10, "sizes": [3, 4, 5],
         "groups": [{"name": "all leagues", "leagues": "all", "bets": ["GOAL_RANGE||6+"], "value_ladder": ladder6}],
         "evidence": evidence("10 lowest 6+ odds", "6+ goals")},
    ]


def htft2_items(trn):
    """HT/FT deep dive 2 watch leads (HTFT2_REPORT): not proven, tracked live."""
    f = CACHE / "htft2.parquet"
    if not f.exists():
        return []
    d = pd.read_parquet(f)
    lgn = leagues()

    def ev(mask, label_of):
        out = {}
        for p, nm in PER.items():
            x = d[d["per"] == p]
            m = mask(x)
            y = (x["htft_f"] == label_of).astype(float)
            o = x[f"o_{label_of}"]
            out[nm] = {"matches": int(m.sum()), "hit_pct": round(float(y[m].mean() * 100), 1),
                       "normal_pct": round(float(y.mean() * 100), 1),
                       "return_per_100": round(float(((y * o)[m].mean() - 1) * 100), 1)}
        return out
    items = []
    for side, k, lab in (("home", "1X2||1", "HT_FT||1/X"), ("away", "1X2||2", "HT_FT||2/X")):
        fav_home = side == "home"
        items.append({
            "id": f"watch-htft-fav-ahead-draw-{side}", "kind": "watch", "status": "watch", "bet": lab,
            "bet_name": f"HT/FT {lab.split('|')[-1]} ({side} favourite ahead at half-time, ends level)",
            "bet_name_tr": trn.get(lab, lab),
            "criteria": [{"bet": k, "op": ">", "chance_pct": 60}, {"bet": k, "op": "<=", "chance_pct": 70},
                         {"bet": "OU|2.5|OVER", "op": ">", "chance_pct": 65}],
            "summary": f"HT/FT {lab.split('|')[-1]} when the {side} team is a 60-70% favourite and over 2.5 goals is "
                       f"65%+ likely (favourite ahead at half-time, match ends level) - one lone cell above "
                       f"break-even in every season; neighbouring cells do not confirm it, so likely luck",
            "evidence": ev(lambda x: (x["fav_home"] == fav_home) & (x["fav_p"] > .6) & (x["fav_p"] <= .7) &
                           (x["over25_p"] > .65), "F/X")})
    hd = pd.read_parquet(CACHE / "htft_wide.parquet")
    hd = hd[hd["league_id"] == "POR-1"]
    import htft2_data as h2
    st = {}
    for p, nm in PER.items():
        x = hd[hd["season"].map(h2.PER) == p]
        y = (x["htft"] == "1/X").astype(float)
        st[nm] = {"matches": len(x), "hit_pct": round(float(y.mean() * 100), 1),
                  "return_per_100": round(float(((y * x["o_1/X"]).mean() - 1) * 100), 1)}
    items.append({"id": "watch-POR-1-HT_FT||1/X", "kind": "league_rule", "status": "watch", "league": "POR-1",
                  "league_name": lgn.get("POR-1", {}).get("en", "POR-1"), "bet": "HT_FT||1/X",
                  "bet_name": "HT/FT 1/X (home ahead at half-time, ends level)",
                  "bet_name_tr": trn.get("HT_FT||1/X", "HT_FT||1/X"), "criteria": [],
                  "summary": "Portugal: HT/FT 1/X (home ahead at half-time, ends level) - follows from the Portugal "
                             "2-2 effect (+15 / -3 / +10 per 100); not proven, the away version 2/X loses",
                  "evidence": st})
    return items


def htft3_items(trn):
    """HT/FT study 3: hit-rate rules for the six changing results that held in all three seasons (>= 1.3x normal)."""
    f, fr = CACHE / "htft3.parquet", CACHE / "htft3_rules.parquet"
    if not f.exists() or not fr.exists():
        return []
    import json
    d = pd.read_parquet(f)
    R = pd.read_parquet(fr)
    ylab = {"1/X": "y_1X", "2/X": "y_2X", "X/1": "y_X1", "X/2": "y_X2", "1/2": "y_12", "2/1": "y_21"}

    def ev(mask, y):
        out = {}
        for p, nm in PER.items():
            m = d["per"] == p
            out[nm] = {"matches": int((mask & m).sum()),
                       "hit_pct": round(float(d.loc[mask & m, y].mean() * 100), 1) if (mask & m).sum() else None,
                       "normal_pct": round(float(d.loc[m, y].mean() * 100), 1)}
        return out
    items = []
    A = d["per"] == "A"
    for share in (0.05, 0.10):                      # X/1 has no odds band in the book yet
        thr = round(float(d.loc[A, "o_X/1"].quantile(share)), 2)
        st = ev(d["o_X/1"] <= thr, "y_X1")
        if holds(st):
            items.append({"id": f"htft3-X/1-odds-{int(share * 100)}", "kind": "odds_rule", "status": "proven",
                          "bet": "HT_FT||X/1", "bet_name": nice("HT_FT||X/1"),
                          "bet_name_tr": trn.get("HT_FT||X/1", "HT_FT||X/1"),
                          "criteria": [{"bet": "HT_FT||X/1", "op": "<=", "odds": thr}],
                          "summary": f"HT/FT X/1 (level at half-time, home wins) when its odds are <= {thr:.2f} "
                                     f"(lowest {int(share * 100)}% of 2024/25)", "evidence": st})
    for lab, y in ylab.items():                    # the 2-condition rule ranked best on 2024/25, if it held
        r = R[(R["result"] == lab) & (R["pool"] == "scan-ready") & R["confirmed"] & (R["conditions"] == 2)]
        r = r[r["criteria"].notna()]
        if not len(r):
            continue
        rb = r.iloc[0]
        crit = json.loads(rb["criteria"])
        st = {}
        for p, nm in PER.items():
            st[nm] = {"matches": int(rb[f"matches {nm}"]), "hit_pct": round(float(rb[f"hit % {nm}"]), 1),
                      "normal_pct": round(float(rb[f"normal % {nm}"]), 1)}
        if not holds(st):
            continue
        key = f"HT_FT||{lab}"
        items.append({"id": f"htft3-{lab}-rule", "kind": "odds_rule", "status": "proven", "bet": key,
                      "bet_name": nice(key), "bet_name_tr": trn.get(key, key), "criteria": crit,
                      "summary": f"HT/FT {lab} when {rb['rule']}", "evidence": st})
    return items


def bb_items(trn):
    """Both teams score in both halves (BB_REPORT): Nesine's own odds band (that price starts in 2025/26, so two
    seasons) and the best rule found on 2024/25 that held in 2025/26 and 2026/27."""
    f, fr = CACHE / "bb.parquet", CACHE / "bb_rules.parquet"
    if not f.exists() or not fr.exists():
        return []
    import json
    d = pd.read_parquet(f)
    R = pd.read_parquet(fr)
    key = "HT_2H_BTTS||YES/YES"
    name, name_tr = nice(key), trn.get(key, key)
    items = []
    thr = round(float(d.loc[d["per"] == "B", "o_bb"].quantile(0.05)), 2)
    m = (d["o_bb"] > 4.0) & (d["o_bb"] <= thr)        # real prices start at 4.66; swapped ones sit at 1.10-2.02
    st = {}
    for p, nm in PER.items():
        if p == "A":
            continue
        mm = d["per"] == p
        st[nm] = {"matches": int((m & mm).sum()), "hit_pct": round(float(d.loc[m & mm, "y_bb"].mean() * 100), 1),
                  "normal_pct": round(float(d.loc[mm, "y_bb"].mean() * 100), 1)}
    if holds(st):
        items.append({"id": "bb-odds-5", "kind": "odds_band", "status": "promising", "bet": key, "bet_name": name,
                      "bet_name_tr": name_tr,
                      "criteria": [{"bet": key, "op": ">", "odds": 4.0}, {"bet": key, "op": "<=", "odds": thr}],
                      "summary": f"{name} when its odds are <= {thr:.2f} (cheapest 5% of 2025/26; the price exists "
                                 "only from 2025/26)", "evidence": st})
    r = R[(R["found on"] == "2024/25") & (R["pool"] == "scan-ready") & R["confirmed"] & (R["conditions"] == 2)]
    r = r[r["criteria"].notna()]
    if len(r):
        rb = r.iloc[0]
        st = {nm: {"matches": int(rb[f"matches {nm}"]), "hit_pct": round(float(rb[f"hit % {nm}"]), 1),
                   "normal_pct": round(float(rb[f"normal % {nm}"]), 1)} for nm in PER.values()}
        if holds(st):
            items.append({"id": "bb-rule", "kind": "odds_rule", "status": "proven", "bet": key, "bet_name": name,
                          "bet_name_tr": name_tr, "criteria": json.loads(rb["criteria"]),
                          "summary": f"{name} when {rb['rule']}", "evidence": st})
    return items


def enough_hits(st, n=5):
    return all(v["matches"] * v["hit_pct"] / 100 >= n - 0.01 for v in st.values())


def cs_items(trn):
    """Correct scores, full time and half time (cs_study.py). For every score:
    1. Nesine's own chance band: its top 5% by chance (or top 10% if the 5% band misses), cut-off from 2024/25
       (chance, not odds: score odds got longer after 2024/25), kept if it held in all three seasons;
    2. the best scan-ready rule found on 2024/25 and confirmed on 2025/26, kept only if the search for that score beat
       luck (more confirmed rules than any shuffled run), the rule held in 2026/27 too, and it hit at least as often
       as the same number of games taken by Nesine's own chance (2025/26 + 2026/27, games where scores are listed).
    Both also need at least 5 winners in every season (rare scores otherwise 'hold' on one or two lucky hits)."""
    ft, fr, fl = CACHE / "cs_targets.parquet", CACHE / "cs_rules.parquet", CACHE / "cs_luck.parquet"
    if not (ft.exists() and fr.exists() and fl.exists()):
        return []
    import json
    T = pd.read_parquet(ft)
    R = pd.read_parquet(fr)
    L = pd.read_parquet(fl)
    items = []
    for score in R["score"].unique():
        half, sc = score.split(" ")
        mk = "CORRECT_SCORE" if half == "FT" else "HT_CORRECT_SCORE"
        key = f"{mk}||{sc}"
        name, name_tr = nice(key), trn.get(key, key)
        y, own = T[f"y_{half}_{sc}"], T[f"own_{half}_{sc}"]
        for share in (0.05, 0.10):
            cut = float(own[(T["per"] == "A") & own.notna()].quantile(1 - share))
            m = own >= cut
            st = {}
            for p, nm in PER.items():
                mm = T["per"] == p
                st[nm] = {"matches": int((m & mm).sum()), "hit_pct": round(float(y[m & mm].mean() * 100), 1),
                          "normal_pct": round(float(y[mm].mean() * 100), 2)}
            if holds(st) and enough_hits(st):
                pct = int(share * 100)
                items.append({"id": f"cs-{half}-{sc}-chance-{pct}", "kind": "odds_band", "status": "proven",
                              "bet": key, "bet_name": name, "bet_name_tr": name_tr,
                              "criteria": [{"bet": key, "op": ">=", "chance_pct": round(cut * 100, 2)}],
                              "summary": f"{name} when Nesine's chance for it is >= {cut * 100:.1f}% (its top {pct}% "
                                         "of 2024/25; chance, not odds)", "evidence": st})
                break
        g = R[(R["score"] == score) & (R["pool"] == "scan-ready")]
        luck = L[(L["score"] == score) & (L["pool"] == "scan-ready")]["confirmed"]
        r = g[g["confirmed"] & g["criteria"].notna()]
        if not len(r) or g["confirmed"].sum() <= luck.max():
            continue
        rb = r.iloc[0]
        st = {nm: {"matches": int(rb[f"matches {nm}"]), "hit_pct": round(float(rb[f"hit % {nm}"]), 1),
                   "normal_pct": round(float(rb[f"normal % {nm}"]), 2)} for nm in PER.values()}
        rule_hits = rb["rule hits there 2025/26"] + rb["rule hits there 2026/27"]
        own_hits = rb["own-price hits, same games 2025/26"] + rb["own-price hits, same games 2026/27"]
        if holds(st) and enough_hits(st) and rule_hits >= own_hits:
            items.append({"id": f"cs-{half}-{sc}-rule", "kind": "odds_rule", "status": "proven", "bet": key,
                          "bet_name": name, "bet_name_tr": name_tr, "criteria": json.loads(rb["criteria"]),
                          "summary": f"{name} when {rb['rule']}", "evidence": st})
    return items


def cs_high_items(trn):
    """High-scoring correct scores 3-2, 2-3, 3-3, 2-4, 4-2 (cs_high.py): the pack of the three most likely of the five
    when their chances add up to the top 5% of 2024/25, and the focused rules that pass the same gates as cs_items."""
    ft, fr, fl = CACHE / "cs_targets.parquet", CACHE / "cs_high_rules.parquet", CACHE / "cs_high_luck.parquet"
    if not (ft.exists() and fr.exists() and fl.exists()):
        return []
    import json
    sc = ["3-2", "2-3", "3-3", "2-4", "4-2"]
    keys = [f"CORRECT_SCORE||{x}" for x in sc]
    T = pd.read_parquet(ft, columns=["match_id", "per"] + [f"own_FT_{x}" for x in sc] + [f"y_FT_{x}" for x in sc])
    O = pd.read_parquet(CACHE / "bb.parquet", columns=["match_id"] + [f"odds_{k}" for k in keys])
    T = T.merge(O, on="match_id", how="left")
    P, Y = T[[f"own_FT_{x}" for x in sc]].to_numpy(float), T[[f"y_FT_{x}" for x in sc]].to_numpy(float)
    Od = T[[f"odds_{k}" for k in keys]].to_numpy(float)
    per = T["per"].to_numpy()
    ok = ~np.isnan(P).any(axis=1)
    items, k = [], 3
    order = np.argsort(-np.nan_to_num(P, nan=-1), axis=1)[:, :k]
    pp = np.take_along_axis(np.nan_to_num(P), order, 1).sum(1)
    hit = np.take_along_axis(Y, order, 1).max(1)
    po = np.take_along_axis(Od, order, 1)
    win = (np.take_along_axis(Y, order, 1) * po).sum(1)
    thr = float(np.round(np.nanquantile(pp[ok & (per == "A")], 0.95), 4))
    m = ok & (pp >= thr)
    st, good = {}, True
    for p_, nm in PER.items():
        mp, base = m & (per == p_), ok & (per == p_)
        mo = mp & ~np.isnan(po).any(axis=1)
        st[nm] = {"matches": int(mp.sum()), "hit_pct": round(float(hit[mp].mean() * 100), 1), "normal_pct": None,
                  "every_match_pct": round(float(hit[base].mean() * 100), 1),
                  "avg_odds": round(float(np.nanmean(1 / (1 / po[mo]).sum(1))), 2),
                  "return_per_100": round(float((win[mo].sum() / (k * mo.sum()) - 1) * 100), 1)}
        good &= st[nm]["hit_pct"] >= 1.3 * st[nm]["every_match_pct"] and hit[mp].sum() >= 5
    if good and st["2026/27"]["matches"] >= 30:
        items.append({"id": "pack-CORRECT_SCORE-high-3-5", "kind": "pack", "status": "proven",
                      "market": "CORRECT_SCORE", "k": k, "min_pack_chance": thr, "selections": keys,
                      "summary": f"High-scoring correct scores (3-2, 2-3, 3-3, 2-4, 4-2): back the {k} most likely of "
                                 f"the five together, only when they add up to >= {thr * 100:.1f}% (top 5% of games)",
                      "evidence": st})
    R, L = pd.read_parquet(fr), pd.read_parquet(fl)
    for x in sc:
        g = R[R["score"] == x]
        r = g[g["confirmed"] & g["criteria"].notna()]
        if not len(r) or g["confirmed"].sum() <= L.loc[L["score"] == x, "confirmed"].max():
            continue
        rb = r.iloc[0]
        st = {nm: {"matches": int(rb[f"matches {nm}"]), "hit_pct": round(float(rb[f"hit % {nm}"]), 1),
                   "normal_pct": round(float(rb[f"normal % {nm}"]), 2)} for nm in PER.values()}
        rule_hits = rb["rule hits there 2025/26"] + rb["rule hits there 2026/27"]
        own_hits = rb["own-price hits, same games 2025/26"] + rb["own-price hits, same games 2026/27"]
        if holds(st) and enough_hits(st) and rule_hits >= own_hits:
            key = f"CORRECT_SCORE||{x}"
            items.append({"id": f"cs-high-FT-{x}-rule", "kind": "odds_rule", "status": "proven", "bet": key,
                          "bet_name": nice(key), "bet_name_tr": trn.get(key, key),
                          "criteria": json.loads(rb["criteria"]), "summary": f"{nice(key)} when {rb['rule']}",
                          "evidence": st})
    return items


def to_md(book):
    L = ["# Strategy book", "",
         "Every strategy found so far, with its exact criteria and its record by season. Built by "
         "`build_strategy_book.py`; checked every day by `daily_scan.py`. Data: our own Nesine/Mackolik collection.",
         "", "Status: **proven** = held in 2024/25, 2025/26 and the 2026/27 exam. **promising** = held every season, "
         "not yet proven beyond chance. **watch** = only seen in 2026/27. **info** = shown for comparison only.", "",
         "None of these beats Nesine's prices in general (the Portugal draw bet is the only one that made money in "
         "every season). They raise the hit rate; the odds usually fall with it.", ""]
    titles = {"odds_band": "Odds bands (bet a high-odds market only when its odds are low for it)",
              "pack": "Packs (the most likely scores / results together)", "league": "League tendencies",
              "league_rule": "League + odds rules (money scans, v4)",
              "tipster": "Tipster rules that raised the hit rate (owner's list, 16 Oct 2026)",
              "odds_rule": "Readable odds rules (decision trees)", "watch": "Watch list (not proven)",
              "system": "Your 10-game system (3-4-5): whole coupons, one per weekend"}
    for kind, title in titles.items():
        items = [s for s in book["strategies"] if s["kind"] == kind and s["status"] != "retired"]
        if not items:
            continue
        L += [f"## {title} ({len(items)})", ""]
        for s in items:
            if kind == "system":
                ev = "; ".join(f"{p}: {v['coupons']} coupons, {v['hit_pct']}% of games won, 3+ hits in "
                               f"{v['coupons_3plus_hits_pct']}% of coupons, system 3-4-5 "
                               f"{v['system_345_return_per_100']:+} per 100, singles {v['return_per_100']:+}"
                               for p, v in s["evidence"].items())
                L.append(f"- **{s['summary']}** [{s['status']}, since {s.get('first_added', '?')}] — {ev}")
                continue
            ev = "; ".join(f"{p}: {v.get('hit_pct')}%" + (f" (normal {v['normal_pct']}%)" if v.get("normal_pct") else "")
                           + (f", return {v['return_per_100']:+}" if "return_per_100" in v else "")
                           for p, v in s["evidence"].items())
            L.append(f"- **{s['summary']}** [{s['status']}, since {s.get('first_added', '?')}] — {ev}")
        L.append("")
    ret = [x for x in book["strategies"] if x["status"] == "retired"]
    if ret:
        L += [f"## Retired ({len(ret)}) — kept for the record, not checked any more", ""]
        L += [f"- {x['summary']} — retired {x['retired_on']}: {x['retired_reason']}" for x in ret]
        L.append("")
    L += ["## Lessons: what did NOT work (do not redo without a new idea)", ""]
    L += [f"- {x}" for x in book.get("lessons", [])]
    L += ["", "## Rule book (older study)", "", "The 150,822 hit-rate rules of `rules_deep.py` (odds ranges and equal "
          "odds, 1–3 conditions) are checked too, through the Matchday Radar engine (`dashboard.compute`). They raise "
          "hit rates 1.5–3x, but the price already follows them.", ""]
    return "\n".join(L)


def plain(x):
    """numpy scalars/strings -> plain Python, so the YAML stays readable."""
    if isinstance(x, dict):
        return {str(k): plain(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [plain(v) for v in x]
    if isinstance(x, np.generic):
        return x.item()
    return x


def live_retirements():
    """Strategies the monthly review (monthly_review.py) found far below their book evidence on live matches."""
    if not LIVE.exists():
        return {}
    return {x["id"]: x for x in (yaml.safe_load(LIVE.read_text()) or {}).get("retire", [])}


def retire_live(x, old, fails, today):
    """Retire x if the monthly review listed it, keeping the first retirement's date and reason."""
    if x["id"] not in fails:
        return x
    if old and old.get("status") == "retired":
        return {**x, "status": "retired", "retired_on": old["retired_on"], "retired_reason": old["retired_reason"]}
    return {**x, "status": "retired", "retired_on": today, "retired_reason": fails[x["id"]]["reason"]}


def merge_with_previous(items, today):
    """Keep every earlier strategy: update the ones still passing, retire (never delete) the ones that do not or
    that the monthly review listed in live_review.yaml."""
    f = HERE / "strategies.yaml"
    prev = yaml.safe_load(f.read_text())["strategies"] if f.exists() else []
    prev_by_id = {p["id"]: p for p in prev}
    new_ids = {x["id"] for x in items}
    fails = live_retirements()
    for x in items:
        old = prev_by_id.get(x["id"])
        x["first_added"] = old.get("first_added", today) if old else today
        x["last_confirmed"] = today
    items = [retire_live(x, prev_by_id.get(x["id"]), fails, today) for x in items]
    kept = []
    for p in prev:
        if p["id"] in new_ids:
            continue
        if p.get("status") != "retired":
            p = {**p, "status": "retired", "retired_on": today,
                 "retired_reason": "no longer passed the gates when the book was rebuilt on newer data"}
        kept.append(p)
    added = sum(1 for x in items if x["id"] not in prev_by_id)
    retired = sum(1 for p in items + kept if p.get("retired_on") == today)
    return items + kept, added, len(items) - added, retired


def save(book, today, line):
    """Write strategies.yaml and STRATEGIES.md; if the book changed, a dated copy and a CHANGELOG line."""
    items = book["strategies"]
    text = yaml.safe_dump(book, allow_unicode=True, sort_keys=False, width=120)
    (HERE / "strategies.yaml").write_text(text)
    (HERE / "STRATEGIES.md").write_text(to_md(book))
    HIST.mkdir(exist_ok=True)
    snaps = sorted(HIST.glob("strategies_*.yaml"))
    strip = lambda t: "\n".join(l for l in t.splitlines() if not l.startswith(("built_on:", "  last_confirmed:")))
    if not snaps or strip(snaps[-1].read_text()) != strip(text):
        (HIST / f"strategies_{today}.yaml").write_text(text)
        with open(HIST / "CHANGELOG.md", "a") as fh:
            if fh.tell() == 0:
                fh.write("# Strategy book changelog\n\nOne line per rebuild that changed the book. Full copies: "
                         "strategies_<date>.yaml in this folder.\n\n")
            fh.write(f"- {today}: {line}; {sum(1 for x in items if x['status'] != 'retired')} active, "
                     f"{sum(1 for x in items if x['status'] == 'retired')} retired in total\n")


def live_only():
    """Apply the monthly review's retirements (live_review.yaml) to the current book, without a rebuild (no caches
    needed): only statuses change; evidence, lessons and everything else stay as they are."""
    today = dt.date.today().isoformat()
    book = yaml.safe_load((HERE / "strategies.yaml").read_text())
    fails = live_retirements()
    before = {x["id"]: x.get("status") for x in book["strategies"]}
    book["strategies"] = [retire_live(x, x, fails, today) for x in book["strategies"]]
    n = sum(1 for x in book["strategies"] if before[x["id"]] != "retired" and x["status"] == "retired")
    save(book, today, f"monthly live review, {n} retired")
    return book, n


def build():
    today = dt.date.today().isoformat()
    d = hi_data.build()
    trn = dict(zip(d["names"], tr_labels(list(d["names"]))))
    lgn = leagues()
    items = (odds_bands(d, trn) + packs(d) + league_items(d, trn, lgn) + v4_items(trn, lgn) + tree_rules(d, trn)
             + tipster_items(trn) + watch_items(trn) + system_items() + htft2_items(trn) + htft3_items(trn)
             + bb_items(trn) + cs_items(trn) + cs_high_items(trn))
    items, added, updated, retired = merge_with_previous(plain(items), today)
    book = {"built_on": today,
            "built_from": "seasons 2024/25 + 2024 (find), 2025/26 + 2025 (confirm), 2026/27 + 2026 so far (exam)",
            "lessons": LESSONS, "strategies": items}
    save(book, today, f"{added} new, {updated} kept/updated, {retired} retired")
    return book


if __name__ == "__main__":
    if "--live-only" in sys.argv:
        b, n = live_only()
        print(f"monthly live review applied: {n} retired")
    else:
        b = build()
        print(pd.Series([s["kind"] for s in b["strategies"]]).value_counts().to_string())
