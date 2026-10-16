"""6+ goals deep dive, study 8: exhaustive 1- and 2-threshold rules over the markets that matter most for 6+.

Markets (closing odds): 6+ itself, score 'other', 1st-half score 'other', score 0-0, 1st-half score 0-0, over 4.5,
total goals 0-1, total goals 4-5, BTTS yes, home 3+, away 3+, favourite's match odds.
Each market gets thresholds at its period-A 2%..50% quantiles on the 6+-friendly side; a rule is one threshold or two
(on different markets). Find on A (>= 100 matches, hit >= 1.5x normal), confirm on B (>= 60 matches, hit >= 1.4x
normal), grade on C (reported). For every rule: hit rate of the same number of matches with the cheapest 6+ price
(is the rule better than just following the 6+ odds?).
Writes cache/six_plus_rules.parquet and output/six_plus_rules.xlsx.
"""
from pathlib import Path
import itertools
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import six_plus as sp  # noqa: E402
from htft_data import CACHE  # noqa: E402

OUT = Path(__file__).resolve().parent / "output"
MK = {  # name: (feature, direction: "low" = small odds favour 6+, "high" = large odds favour 6+)
    "6+ odds": ("odds: Total goals 6+", "low"), "score 'other' odds": ("odds: Score OTHER", "low"),
    "1st-half score 'other' odds": ("odds: 1st-half score OTHER", "low"), "score 0-0 odds": ("odds: Score 0-0", "high"),
    "1st-half 0-0 odds": ("odds: 1st-half score 0-0", "high"), "over 4.5 odds": ("odds: Goals over 4.5", "low"),
    "total goals 0-1 odds": ("odds: Total goals 0-1", "high"), "total goals 4-5 odds": ("odds: Total goals 4-5", "low"),
    "BTTS yes odds": ("odds: Both teams score yes", "low"), "home 3+ odds": ("odds: Home goals over 2.5", "low"),
    "away 3+ odds": ("odds: Away goals over 2.5", "low"), "favourite's odds": ("fav", "low"),
}
QS = [.02, .04, .06, .08, .10, .15, .20, .30, .40, .50]


def run():
    D, X, _ = sp.data()
    V = {}
    for nm, (f, _) in MK.items():
        V[nm] = np.exp(np.minimum(X["odds: Result home"], X["odds: Result away"])) if f == "fav" else np.exp(X[f])
    A, B, C = (D["per"] == p for p in "ABC")
    y = D["y"].to_numpy()
    atoms = []
    for nm, (f, dirn) in MK.items():
        v = V[nm].to_numpy()
        for q in QS:
            thr = np.nanquantile(v[A], q if dirn == "low" else 1 - q)
            m = (v <= thr) if dirn == "low" else (v >= thr)
            atoms.append((nm, "≤" if dirn == "low" else "≥", round(float(thr), 2), m & ~np.isnan(v)))
    base = {p: y[m.to_numpy()].mean() for p, m in zip("ABC", (A, B, C))}
    p6 = D["p6"].to_numpy()
    rows = []
    cands = [(a,) for a in atoms] + [(a, b) for a, b in itertools.combinations(atoms, 2) if a[0] != b[0]]
    for rule in cands:
        m = np.logical_and.reduce([r[3] for r in rule])
        st = {}
        for p, pm in zip("ABC", (A, B, C)):
            mm = m & pm.to_numpy()
            st[p] = (int(mm.sum()), y[mm].mean() if mm.sum() else np.nan)
        if st["A"][0] < 100 or st["A"][1] < 1.5 * base["A"]:
            continue
        if st["B"][0] < 60 or st["B"][1] < 1.4 * base["B"]:
            continue
        row = {"rule": "  AND  ".join(f"{r[0]} {r[1]} {r[2]:.2f}" for r in rule), "conditions": len(rule)}
        for p, nm in sp.SEAS.items():
            row[f"matches {nm}"], row[f"6+ hit % {nm}"] = st[p][0], st[p][1] * 100
            row[f"normal % {nm}"] = base[p] * 100
            pm = (D["per"] == p).to_numpy()
            k = st[p][0]
            order = np.argsort(-np.nan_to_num(p6[pm], nan=-1))[:k]
            row[f"cheapest-6+ filter same size % {nm}"] = y[pm][order].mean() * 100 if k else np.nan
        mm = m
        o6 = D["odds6"].to_numpy()
        ok = mm & ~np.isnan(o6)
        row["avg 6+ odds"] = np.nanmean(o6[ok]) if ok.any() else np.nan
        row["return per 100 (6+)"] = np.nanmean(y[ok] * o6[ok] - 1) * 100 if ok.any() else np.nan
        rows.append(row)
    r = pd.DataFrame(rows)
    r["beats odds filter in B and C"] = (r["6+ hit % 2025/26"] > r["cheapest-6+ filter same size % 2025/26"]) & \
        (r["6+ hit % 2026/27"] > r["cheapest-6+ filter same size % 2026/27"])
    r = r.sort_values("6+ hit % 2025/26", ascending=False)
    r.to_parquet(CACHE / "six_plus_rules.parquet")
    return r


if __name__ == "__main__":
    r = run()
    pd.set_option("display.width", 260); pd.set_option("display.max_colwidth", 90)
    print(len(r), "rules confirmed; beat the odds filter in B and C:", int(r["beats odds filter in B and C"].sum()))
    cols = ["rule", "matches 2024/25", "6+ hit % 2024/25", "matches 2025/26", "6+ hit % 2025/26",
            "matches 2026/27", "6+ hit % 2026/27", "cheapest-6+ filter same size % 2026/27", "avg 6+ odds",
            "return per 100 (6+)"]
    print(r[cols].head(25).round(1).to_string())
    print(r[r["beats odds filter in B and C"]][cols].head(15).round(1).to_string())
