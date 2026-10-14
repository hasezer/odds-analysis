"""League tendencies for high-odds bets: does a league produce a result more often than normal, EVERY season?

For each league and each high-odds target: hit rate in A, B and C vs the normal rate of that period
(all leagues), and vs the chance the goal model gives those same matches (is it already in the prices?).
A pair is listed when the league is above normal in A and B with z >= 2 each; C is the exam.
Luck control: 50 runs with the league labels shuffled within each period.
Writes cache/hi_leagues.parquet and cache/hi_leagues_luck.parquet.
"""
from pathlib import Path
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import hi_data  # noqa: E402
import hi_rank  # noqa: E402
from dashboard import leagues  # noqa: E402
from htft_data import CACHE  # noqa: E402

SHUFFLES = 50


def scan(lg, per, Y, Fq, tnames, detail=True):
    L = sorted(set(lg))
    li = pd.Index(L).get_indexer(lg)
    rows, count = [], 0
    for j, tn in enumerate(tnames):
        y = Y[:, j]
        st = {}
        for p in "ABC":
            m = (per == p) & ~np.isnan(y)
            base = y[m].mean()
            n = np.bincount(li[m], minlength=len(L))
            h = np.bincount(li[m], weights=y[m], minlength=len(L))
            q = np.bincount(li[m], weights=np.nan_to_num(Fq[m, j], nan=base), minlength=len(L))
            z = (h - n * base) / np.sqrt(np.maximum(n * base * (1 - base), 1e-9))
            st[p] = (n, h, q, base, z)
        good = (st["A"][4] >= 2) & (st["B"][4] >= 2) & (st["A"][0] >= 100) & (st["B"][0] >= 100)
        count += int(good.sum())
        if not detail:
            continue
        for k in np.where(good)[0]:
            row = {"league": L[k], "target": tn}
            for p in "ABC":
                n, h, q, base, z = (x[k] if np.ndim(x) else x for x in st[p])
                row.update({f"matches_{p}": int(n), f"hit_{p}": h / max(n, 1) * 100, f"normal_{p}": base * 100,
                            f"model_{p}": q / max(n, 1) * 100, f"z_{p}": z})
            rows.append(row)
    return pd.DataFrame(rows), count


def run():
    d = hi_data.build()
    Fq = hi_rank.goal_model_probs(d)
    lg, per = d["league"].astype(str), d["per"]
    real, n_real = scan(lg, per, d["Y"], Fq, list(d["tnames"]))
    rng = np.random.default_rng(3)
    luck = []
    for s in range(SHUFFLES):
        ls = lg.copy()
        for p in "ABC":
            ix = np.where(per == p)[0]
            ls[ix] = rng.permutation(lg[ix])
        luck.append(scan(ls, per, d["Y"], Fq, list(d["tnames"]), detail=False)[1])
    names = leagues()
    if len(real):
        real["league_name"] = real["league"].map(lambda l: names.get(l, {}).get("en", l))
        real["held_in_C"] = real["hit_C"] > real["normal_C"]
        real = real.sort_values("z_B", ascending=False)
    real.to_parquet(CACHE / "hi_leagues.parquet")
    pd.DataFrame({"shuffle": range(SHUFFLES), "found": luck}).to_parquet(CACHE / "hi_leagues_luck.parquet")
    return real, n_real, luck


if __name__ == "__main__":
    real, n, luck = run()
    pd.set_option("display.width", 250)
    print(f"real {n}; shuffled mean {np.mean(luck):.1f} max {max(luck)}")
    if len(real):
        print(f"held in C: {real['held_in_C'].mean():.2f}")
        print(real[["league_name", "target", "matches_A", "hit_A", "normal_A", "model_A", "hit_B", "normal_B",
                    "model_B", "matches_C", "hit_C", "normal_C", "model_C"]].round(1).to_string())
