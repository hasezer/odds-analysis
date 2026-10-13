"""Rule book: price conditions under which an outcome lands much more often than usual (hit-rate lift).

Conditions (one match's closing prices, 162 common selection types):
  equal   |odds_a - odds_b| <= 0.10                       e.g. "Over 4.5 ≈ Both halves over 1.5"
  cheaper odds_a < odds_b (only pairs where that is unusual, < 35% of matches)
  low     odds_a <= the 10% / 25% lowest level seen in period A
Outcome: any of the 162 selections whose market is different from the condition's market(s).

A rule is kept only if, in EACH period (A = 2024/25 + 2024, B = 2025/26 + 2025, C = 2026/27 + 2026):
  bets >= 200 (A, B) and >= 60 (C), and the hit rate is significantly above the outcome's normal rate (z >= 3 in A
  and B, z >= 1.5 in C), with lift >= 1.25 in every period.
Reported for information: Nesine's own price-implied rate in the same matches, and the return per bet.
Writes cache/rule_book.parquet.
"""
from pathlib import Path
import sys
import time

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import miner_data as mdat  # noqa: E402
from htft_data import CACHE  # noqa: E402

READABLE = {
    "1X2": "Result", "DC": "Double chance", "OU": "Goals", "HT_OU": "1st-half goals", "BTTS": "Both teams score",
    "HT_BTTS": "1st-half both score", "2H_BTTS": "2nd-half both score", "HT_1X2": "1st-half result",
    "2H_1X2": "2nd-half result", "TEAM_OU_HOME": "Home goals", "TEAM_OU_AWAY": "Away goals",
    "HT_TEAM_OU_HOME": "Home 1st-half goals", "HT_TEAM_OU_AWAY": "Away 1st-half goals", "GOAL_RANGE": "Total goals",
    "BOTH_HALVES_OVER": "Both halves over", "HT_FT": "HT/FT", "CORRECT_SCORE": "Score",
    "HT_CORRECT_SCORE": "1st-half score", "1X2_AND_OU": "Result & goals", "1X2_AND_BTTS": "Result & both score",
    "OU_AND_BTTS": "Goals & both score", "HT_1X2_AND_HT_OU": "1st-half result & goals",
    "HT_1X2_AND_HT_BTTS": "1st-half result & both score", "HT_2H_BTTS": "Both score 1st/2nd half",
    "CORNERS_OU": "Corners", "TEAM_WIN_EITHER_HALF_HOME": "Home wins a half",
    "TEAM_WIN_EITHER_HALF_AWAY": "Away wins a half", "TEAM_WIN_BOTH_HALVES_HOME": "Home wins both halves",
    "TEAM_WIN_BOTH_HALVES_AWAY": "Away wins both halves",
}
WORD = {"OVER": "over", "UNDER": "under", "YES": "yes", "NO": "no"}


def nice(lab):
    mk, line, sk = lab.split("|")
    name = READABLE.get(mk, mk)
    if mk in ("1X2", "HT_1X2", "2H_1X2"):
        sk = {"1": "home", "X": "draw", "2": "away"}[sk]
    elif mk == "GOAL_RANGE":
        sk = f"{sk} goals"
        return f"{name} {sk.replace(' goals', '')}"
    else:
        sk = " & ".join(WORD.get(p, p) for p in sk.split("&"))
        sk = "/".join(WORD.get(p, p) for p in sk.split("/"))
    return f"{name} {sk} {line}".strip() if line else f"{name} {sk}"


def run():
    z = mdat.build()
    O, Hm, F, per, names = z["O"], z["Hm"], z["F"], z["per"], z["names"]
    S = len(names)
    mk = np.array([n.split("|")[0] for n in names])
    P = {}
    for p in "ABC":
        ix = per == p
        avail = (~np.isnan(Hm[ix]) & ~np.isnan(O[ix])).astype(np.float32)
        hh = np.nan_to_num(Hm[ix]) * avail
        ff = np.nan_to_num(F[ix]) * avail * (~np.isnan(F[ix]))
        fa = avail * (~np.isnan(F[ix]))
        prof = (hh * np.nan_to_num(O[ix]) - 1) * avail
        base = hh.sum(0) / np.maximum(avail.sum(0), 1)
        P[p] = dict(o=O[ix], avail=avail, hh=hh, ff=ff, fa=fa, prof=prof, base=base)

    # ---- conditions
    conds = []                                   # (kind, a, b, threshold) evaluated per period
    oA = P["A"]["o"]
    for i in range(S):
        col = oA[:, i]
        if np.isnan(col).mean() < .5:
            for q in (.10, .25):
                conds.append(("low", i, -1, float(np.nanquantile(col, q))))
    for i in range(S):
        for j in range(i + 1, S):
            if mk[i] == mk[j]:
                continue
            a, b = oA[:, i], oA[:, j]
            ok = ~np.isnan(a) & ~np.isnan(b)
            if ok.sum() < 1000:
                continue
            if (np.abs(a[ok] - b[ok]) <= .10).sum() >= 200:
                conds.append(("equal", i, j, .10))
            share = (a[ok] < b[ok]).mean()
            if .005 < share < .35:
                conds.append(("cheaper", i, j, 0))
            elif .005 < 1 - share < .35:
                conds.append(("cheaper", j, i, 0))
    print(f"{len(conds):,} conditions x {S} outcomes", flush=True)

    def mask(c, o):
        kind, i, j, t = c
        if kind == "low":
            return o[:, i] <= t
        a, b = o[:, i], o[:, j]
        return (np.abs(a - b) <= t) if kind == "equal" else (a < b)

    rows = []
    t0 = time.time()
    B = 3000
    for c0 in range(0, len(conds), B):
        cc = conds[c0:c0 + B]
        st = {}
        for p in "ABC":
            d = P[p]
            Cm = np.stack([np.nan_to_num(mask(c, d["o"]), nan=0) for c in cc], 1).astype(np.float32)
            n = Cm.T @ d["avail"]
            h = Cm.T @ d["hh"]
            e = Cm.T @ d["ff"]
            ne = Cm.T @ d["fa"]
            pr = Cm.T @ d["prof"]
            rate = h / np.maximum(n, 1)
            base = d["base"][None, :]
            z = (rate - base) / np.sqrt(base * (1 - base) / np.maximum(n, 1) + 1e-12)
            st[p] = (n, rate, z, e / np.maximum(ne, 1), pr / np.maximum(n, 1), base)
        nA, rA, zA = st["A"][:3]; nB, rB, zB = st["B"][:3]; nC, rC, zC = st["C"][:3]
        lift = lambda p: st[p][1] / np.maximum(st[p][5], 1e-9)
        keep = ((nA >= 200) & (nB >= 200) & (nC >= 60) & (zA >= 3) & (zB >= 3) & (zC >= 1.5)
                & (lift("A") >= 1.25) & (lift("B") >= 1.25) & (lift("C") >= 1.25))
        for ci, si in zip(*np.where(keep)):
            kind, i, j, t = cc[ci]
            if mk[si] == mk[i] or (j >= 0 and mk[si] == mk[j]):
                continue
            if kind == "low":
                text = f"{nice(names[i])} odds ≤ {t:.2f}"
            elif kind == "equal":
                text = f"{nice(names[i])} ≈ {nice(names[j])} (within 0.10)"
            else:
                text = f"{nice(names[i])} cheaper than {nice(names[j])}"
            row = {"rule": text, "then": nice(names[si]), "kind": kind, "cond_a": names[i],
                   "cond_b": names[j] if j >= 0 else "", "outcome": names[si]}
            for p in "ABC":
                n, rate, zz, imp, roi, base = (x[ci, si] if np.ndim(x) == 2 and x.shape[0] > 1 else x[0, si]
                                               for x in st[p])
                row.update({f"matches_{p}": int(n), f"hit_{p}": rate * 100, f"normal_{p}": base * 100,
                            f"priced_{p}": imp * 100, f"roi_{p}": roi * 100})
            rows.append(row)
        print(f"conditions {c0 + len(cc):>7,}/{len(conds):,}  rules kept: {len(rows):,}  ({time.time() - t0:.0f}s)",
              flush=True)
    r = pd.DataFrame(rows)
    for p in "ABC":
        r[f"lift_{p}"] = r[f"hit_{p}"] / r[f"normal_{p}"]
    r["matches_all"] = r[["matches_A", "matches_B", "matches_C"]].sum(1)
    for k in ("hit", "normal", "priced"):
        r[f"{k}_all"] = sum(r[f"{k}_{p}"] * r[f"matches_{p}"] for p in "ABC") / r["matches_all"]
    r["lift_all"] = r["hit_all"] / r["normal_all"]
    r["roi_all"] = sum(r[f"roi_{p}"] * r[f"matches_{p}"] for p in "ABC") / r["matches_all"]
    r.to_parquet(CACHE / "rule_book.parquet")
    return r


if __name__ == "__main__":
    r = run()
    print(len(r), "rules")
