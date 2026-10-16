"""Test the owner's list of tipster rules (16 Oct 2026) on all our matches. Uses rule_tester.py.

Interpretations (written down before testing):
  favourite = the side with the lower match-result odds; "within 0.10" = absolute odds difference <= 0.10.
  Rule 22 (HT/FT score market "0:1 / 4+") cannot be tested: Nesine's market is not in our collection.
Writes output/tipster_rules.xlsx and prints one summary line per rule and bet.
"""
from pathlib import Path
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import rule_tester as rt  # noqa: E402

OUT = Path(__file__).resolve().parent / "output" / "tipster_rules.xlsx"


def fav(W, home_key, away_key):
    """(outcome, odds) of a favourite-team bet: home label when home is favourite, else away label."""
    hit = pd.Series(np.where(W["home_fav"], rt.outcome(W, home_key), rt.outcome(W, away_key)), index=W.index)
    odds = pd.Series(np.where(W["home_fav"], W.get(home_key), W.get(away_key)), index=W.index)
    return hit, odds


def run():
    W = rt.team_history(rt.wide())
    o = lambda k: W[k] if k in W.columns else pd.Series(np.nan, index=W.index)
    between = lambda s, lo, hi: (s >= lo) & (s <= hi)
    near = lambda a, b, tol: (o(a) - o(b)).abs() <= tol + 1e-9
    bet = lambda k: (rt.outcome(W, k), o(k))
    res = []

    def add(no, text, cond, hit, odds):
        r = rt.test(W, cond, hit, odds, name=f"{no}. {text}")
        r.insert(0, "no", no)
        res.append(r)

    one, two = o("1X2||1"), o("1X2||2")
    add(1, "Home or away odds 1.81-1.90 -> both teams score: yes",
        between(one, 1.81, 1.90) | between(two, 1.81, 1.90), *bet("BTTS||YES"))
    add(2, "Favourite odds 1.40-1.70 -> favourite scores 2+ (team over 1.5)",
        between(W["fav_odds"], 1.40, 1.70), *fav(W, "TEAM_OU_HOME|1.5|OVER", "TEAM_OU_AWAY|1.5|OVER"))
    add(3, "1st-half BTTS yes ~ half-by-half 'No/Yes' (within 0.10) -> 1st-half BTTS yes",
        near("HT_BTTS||YES", "HT_2H_BTTS||NO/YES", .10), *bet("HT_BTTS||YES"))
    for sk in ("YES/YES", "NO/YES", "YES/NO"):
        add(4, f"Every game: half-by-half BTTS {sk}", pd.Series(True, index=W.index), *bet(f"HT_2H_BTTS||{sk}"))
    # 4 combined: all three on every game (3 stakes per game)
    keys = ["HT_2H_BTTS||YES/YES", "HT_2H_BTTS||NO/YES", "HT_2H_BTTS||YES/NO"]
    pay = sum(rt.outcome(W, k) * o(k) for k in keys)
    allp = pd.concat([o(k) for k in keys], axis=1).notna().all(1)
    rows = []
    for p in ["2024/25", "2025/26", "2026/27", "all"]:
        m = allp & ((W["period"] == p) if p != "all" else True)
        if m.sum():
            rows.append({"no": 4, "rule": "4. All three (Yes/Yes + No/Yes + Yes/No) on every game", "period": p,
                         "matches": int(m.sum()), "hits": int((pay[m] > 0).sum()),
                         "hit_pct": (pay[m] > 0).mean() * 100, "return_per_100": (pay[m].sum() - 3 * m.sum())
                         / (3 * m.sum()) * 100})
    res.append(pd.DataFrame(rows))
    # 5: 0-1 goals odds vs 6+ goals
    h6, o6 = bet("GOAL_RANGE||6+")
    bins = [0, 3.5, 4.0, 4.5, 5.0, 5.5, 6.0, 7.0, 8.5, 100]
    g = pd.DataFrame({"band": pd.cut(o("GOAL_RANGE||0-1"), bins), "hit": h6, "odds": o6, "period": W["period"]})
    g = g[g["odds"].notna() & g["band"].notna()]
    t5 = g.groupby(["band", "period"], observed=True).agg(matches=("hit", "size"), hit_pct=("hit", "mean"),
                                                         avg_6plus_odds=("odds", "mean")).reset_index()
    t5["hit_pct"] *= 100
    t5["return_per_100"] = g.groupby(["band", "period"], observed=True).apply(
        lambda x: (x["hit"] * x["odds"] - 1).mean() * 100).to_numpy()
    c45 = between(o("GOAL_RANGE||4-5"), 2.75, 3.10)
    add(6, "Total goals 4-5 odds 2.75-3.10 -> over 3.5", c45, *bet("OU|3.5|OVER"))
    add(6, "Total goals 4-5 odds 2.75-3.10 -> 1st-half over 1.5", c45, *bet("HT_OU|1.5|OVER"))
    add(7, "Total goals 0-1 odds > 4.20 -> over 3.5", o("GOAL_RANGE||0-1") > 4.20, *bet("OU|3.5|OVER"))
    c23 = between(o("GOAL_RANGE||2-3"), 1.80, 2.00)
    for k, nm in (("GOAL_RANGE||2-3", "total goals 2-3"), ("CORRECT_SCORE||1-1", "score 1-1"),
                  ("CORRECT_SCORE||2-1", "score 2-1"), ("CORRECT_SCORE||1-2", "score 1-2")):
        add(8, f"Total goals 2-3 odds 1.80-2.00 -> {nm}", c23, *bet(k))
    c9 = (o("HT_CORRECT_SCORE||OTHER") < 5) & (o("CORRECT_SCORE||OTHER") < 8)
    add(9, "1st-half score 'other' < 5 & score 'other' < 8 -> over 3.5", c9, *bet("OU|3.5|OVER"))
    add(9, "1st-half score 'other' < 5 & score 'other' < 8 -> 6+ goals", c9, *bet("GOAL_RANGE||6+"))
    fav_ht05 = pd.Series(np.where(W["home_fav"], o("HT_TEAM_OU_HOME|0.5|OVER"), o("HT_TEAM_OU_AWAY|0.5|OVER")),
                         index=W.index)
    add(10, "Over 2.5 ~ favourite 1st-half over 0.5 (within 0.10) -> favourite scores 2+",
        (o("OU|2.5|OVER") - fav_ht05).abs() <= .10 + 1e-9, *fav(W, "TEAM_OU_HOME|1.5|OVER", "TEAM_OU_AWAY|1.5|OVER"))
    add(11, "Over 4.5 ~ both halves over 1.5 (within 0.20) -> 6+ goals",
        near("OU|4.5|OVER", "BOTH_HALVES_OVER|1.5|YES", .20), *bet("GOAL_RANGE||6+"))
    add(12, "1st-half home/away lead & both scored < 8 -> both halves over 1.5",
        (o("HT_1X2_AND_HT_BTTS||1&YES") < 8) | (o("HT_1X2_AND_HT_BTTS||2&YES") < 8), *bet("BOTH_HALVES_OVER|1.5|YES"))
    add(13, "1st-half score 2-2 odds < 38 -> 1st-half BTTS yes", o("HT_CORRECT_SCORE||2-2") < 38, *bet("HT_BTTS||YES"))
    add(14, "BTTS no odds > 2.20 -> BTTS yes", o("BTTS||NO") > 2.20, *bet("BTTS||YES"))
    comeback = W["h_prev_htft"].isin(["2/1", "1/2"]) | W["a_prev_htft"].isin(["2/1", "1/2"])
    add(15, "A team's previous match was HT/FT 2/1 or 1/2 -> 1st-half draw", comeback, *bet("HT_1X2||X"))
    ex = [1.65, 1.67, 1.75]
    h16 = pd.Series(np.where(one.isin(ex), rt.outcome(W, "HT_1X2||1"), rt.outcome(W, "HT_1X2||2")), index=W.index)
    o16 = pd.Series(np.where(one.isin(ex), o("HT_1X2||1"), o("HT_1X2||2")), index=W.index)
    add(16, "A team's odds exactly 1.65 / 1.67 / 1.75 -> that team wins the 1st half", one.isin(ex) | two.isin(ex),
        h16, o16)
    c17 = between(o("CORRECT_SCORE||0-0"), 7, 8) & between(o("CORRECT_SCORE||1-0"), 5, 6)
    add(17, "Score 0-0 odds 7-8 & score 1-0 odds 5-6 -> favourite wins & under 2.5", c17,
        *fav(W, "1X2_AND_OU|2.5|1&UNDER", "1X2_AND_OU|2.5|2&UNDER"))
    c18 = ((W["h_one_one_last5"] + W["a_one_one_last5"]) >= 2) & (o("1X2||X") < 3.05) & \
        between(o("OU|2.5|UNDER"), 1.40, 1.60) & (W["fav_odds"] >= 1.80)
    add(18, "2+ 1-1 draws in both teams' last 5, draw < 3.05, under 2.5 ~1.50, favourite >= 1.80 -> draw", c18,
        *bet("1X2||X"))
    add(19, "Draw & under 2.5 odds 2.86-2.99 -> HT/FT X/X", between(o("1X2_AND_OU|2.5|X&UNDER"), 2.86, 2.99),
        *bet("HT_FT||X/X"))
    add(20, "Home 2.04-2.77 & away 2.64-2.77 -> HT/FT 1/2", between(one, 2.04, 2.77) & between(two, 2.64, 2.77),
        *bet("HT_FT||1/2"))
    add(21, "Home 2.70-2.75 & away 2.04-2.07 -> HT/FT 2/1", between(one, 2.70, 2.75) & between(two, 2.04, 2.07),
        *bet("HT_FT||2/1"))
    out = pd.concat(res, ignore_index=True)
    from htft_data import CACHE
    out.to_parquet(CACHE / "tipster_rules.parquet")
    with pd.ExcelWriter(OUT) as xw:
        summ = out[out["period"] == "all"].drop(columns="period")
        summ.round(2).to_excel(xw, sheet_name="Summary (all seasons)", index=False)
        out.round(2).to_excel(xw, sheet_name="By season", index=False)
        t5.round(2).to_excel(xw, sheet_name="Rule 5 (0-1 vs 6+)", index=False)
        for ws in xw.sheets.values():
            ws.set_column(0, 0, 5); ws.set_column(1, 1, 80); ws.set_column(2, 12, 14)
    return out, t5


if __name__ == "__main__":
    out, t5 = run()
    pd.set_option("display.width", 260); pd.set_option("display.max_colwidth", 85)
    piv = out.pivot_table(index=["no", "rule"], columns="period", values="hit_pct", sort=False)
    a = out[out["period"] == "all"].set_index(["no", "rule"])
    show = a[["matches", "hit_pct", "normal_pct", "breakeven_pct", "avg_odds", "return_per_100", "z"]].join(
        piv[["2024/25", "2025/26", "2026/27"]].add_prefix("hit "))
    print(show.round(1).to_string())
    print(t5.pivot_table(index="band", columns="period", values=["matches", "hit_pct", "return_per_100"],
                         observed=True).round(1).to_string())
