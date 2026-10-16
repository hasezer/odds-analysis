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


def merge_with_previous(items, today):
    """Keep every earlier strategy: update the ones still passing, retire (never delete) the ones that do not."""
    f = HERE / "strategies.yaml"
    prev = yaml.safe_load(f.read_text())["strategies"] if f.exists() else []
    prev_by_id = {p["id"]: p for p in prev}
    new_ids = {x["id"] for x in items}
    for x in items:
        old = prev_by_id.get(x["id"])
        x["first_added"] = old.get("first_added", today) if old else today
        x["last_confirmed"] = today
    kept = []
    for p in prev:
        if p["id"] in new_ids:
            continue
        if p.get("status") != "retired":
            p = {**p, "status": "retired", "retired_on": today,
                 "retired_reason": "no longer passed the gates when the book was rebuilt on newer data"}
        kept.append(p)
    added = sum(1 for x in items if x["id"] not in prev_by_id)
    retired = sum(1 for p in kept if p.get("retired_on") == today)
    return items + kept, added, len(items) - added, retired


def build():
    today = dt.date.today().isoformat()
    d = hi_data.build()
    trn = dict(zip(d["names"], tr_labels(list(d["names"]))))
    lgn = leagues()
    items = (odds_bands(d, trn) + packs(d) + league_items(d, trn, lgn) + v4_items(trn, lgn) + tree_rules(d, trn)
             + tipster_items(trn) + watch_items(trn) + system_items())
    items, added, updated, retired = merge_with_previous(plain(items), today)
    book = {"built_on": today,
            "built_from": "seasons 2024/25 + 2024 (find), 2025/26 + 2025 (confirm), 2026/27 + 2026 so far (exam)",
            "lessons": LESSONS, "strategies": items}
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
            fh.write(f"- {today}: {added} new, {updated} kept/updated, {retired} retired; "
                     f"{sum(1 for x in items if x['status'] != 'retired')} active, "
                     f"{sum(1 for x in items if x['status'] == 'retired')} retired in total\n")
    return book


if __name__ == "__main__":
    b = build()
    print(pd.Series([s["kind"] for s in b["strategies"]]).value_counts().to_string())
