"""Brute-force price-relationship miner.

Condition = how two prices of the same match relate: the ratio odds_i / odds_j falls in one of 10 bands (cut at the
deciles of period A), or the two prices are within 0.10 of each other ("equal"). Every pair of the 162 common
selection types is used (13,041 pairs), and every condition is tested against every selection as the bet.

Three gates (fixed before running):
  find     period A (2024/25 + 2024):  >= 150 bets, return > 0, t >= T_FIND (3 found nothing; now 2)
  confirm  period B (2025/26 + 2025):  >= 100 bets, return > 0, t >= 2
  exam     period C (2026/27 + 2026):  reported as is (looked at only for patterns that passed both gates)
A shuffled run (outcomes shuffled across matches inside each period) shows how many passes pure luck produces.
Writes cache/miner_hits.parquet.
"""
from pathlib import Path
import sys
import time

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import miner_data as mdat  # noqa: E402
from htft_data import CACHE  # noqa: E402

NB = 10
BATCH = 600                      # pairs per batch
T_FIND = 2.0                     # t-score needed in period A (3.0 found nothing, real or shuffled)


def stats(Cm, H, A, P):
    """Per (condition, bet): bets, hits, profit sum, profit^2 sum."""
    return Cm.T @ A, Cm.T @ H, Cm.T @ P, Cm.T @ (P * P)


def run(shuffle=False, seed=0):
    z = mdat.build()
    O, Hm, per, names = z["O"], z["Hm"], z["per"], z["names"]
    S = O.shape[1]
    logO = np.log(O)
    rng = np.random.default_rng(seed)
    data = {}
    for p in "ABC":
        ix = np.where(per == p)[0]
        o, h = O[ix], Hm[ix]
        if shuffle:                                           # break the link between prices and outcomes
            perm = rng.permutation(len(ix))
            o, h = o[perm], h[perm]
        avail = (~np.isnan(h) & ~np.isnan(o)).astype(np.float32)
        hh = np.nan_to_num(h) * avail
        prof = (hh * np.nan_to_num(o) - 1) * avail
        data[p] = (ix, avail, hh, prof)

    pairs = [(i, j) for i in range(S) for j in range(i + 1, S)]
    cutsA = {}
    out = []
    t0 = time.time()
    for b0 in range(0, len(pairs), BATCH):
        bp = pairs[b0:b0 + BATCH]
        res = {}
        for p in "ABC":
            ix, avail, hh, prof = data[p]
            lo = logO[ix]
            masks, keys = [], []
            for (i, j) in bp:
                r = lo[:, i] - lo[:, j]
                ok = ~np.isnan(r)
                if p == "A":
                    cutsA[(i, j)] = np.quantile(r[ok], np.linspace(0, 1, NB + 1)[1:-1]) if ok.sum() > 500 else None
                cuts = cutsA[(i, j)]
                if cuts is None:
                    continue
                band = np.digitize(np.where(ok, r, 0), cuts)
                for k in range(NB):
                    masks.append((band == k) & ok); keys.append((i, j, k))
                eq = ok & (np.abs(np.exp(lo[:, i]) - np.exp(lo[:, j])) <= 0.10)
                masks.append(eq); keys.append((i, j, -1))
            Cm = np.stack(masks, axis=1).astype(np.float32)
            res[p] = (keys, stats(Cm, hh, avail, prof))
        keys = res["A"][0]
        nA, hA, pA, qA = res["A"][1]
        nB, hB, pB, qB = res["B"][1]
        nC, hC, pC, qC = res["C"][1]

        def t(n, ps, qs):
            m = ps / np.maximum(n, 1)
            v = qs / np.maximum(n, 1) - m * m
            return m, m / np.sqrt(np.maximum(v, 1e-9) / np.maximum(n, 1))

        mA, tA = t(nA, pA, qA)
        mB, tB = t(nB, pB, qB)
        mC, tC = t(nC, pC, qC)
        passA = (nA >= 150) & (mA > 0) & (tA >= T_FIND)
        for ci, si in zip(*np.where(passA)):
            i, j, k = keys[ci]
            out.append({"price_a": names[i], "price_b": names[j], "band": "equal (±0.10)" if k == -1 else k,
                        "bet": names[si],
                        "bets_A": int(nA[ci, si]), "roi_A": mA[ci, si] * 100, "t_A": tA[ci, si],
                        "bets_B": int(nB[ci, si]), "roi_B": mB[ci, si] * 100, "t_B": tB[ci, si],
                        "bets_C": int(nC[ci, si]), "roi_C": mC[ci, si] * 100, "t_C": tC[ci, si]})
        if b0 // BATCH % 5 == 0:
            print(f"{'shuffled ' if shuffle else ''}pairs {b0 + len(bp):>6}/{len(pairs)}  passed find gate so far: "
                  f"{len(out):>6}  ({time.time() - t0:.0f}s)", flush=True)
    r = pd.DataFrame(out, columns=["price_a", "price_b", "band", "bet", "bets_A", "roi_A", "t_A", "bets_B", "roi_B",
                                   "t_B", "bets_C", "roi_C", "t_C"])
    r["band"] = r["band"].astype(str)
    r["confirmed"] = (r["bets_B"] >= 100) & (r["roi_B"] > 0) & (r["t_B"] >= 2)
    r.to_parquet(CACHE / f"miner_hits{'_shuffled' if shuffle else ''}.parquet")
    return r


if __name__ == "__main__":
    shuffle = "--shuffle" in sys.argv
    r = run(shuffle=shuffle)
    print(f"passed find gate: {len(r)}   passed confirm gate: {int(r['confirmed'].sum())}")
