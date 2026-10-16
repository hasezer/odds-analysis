"""Rule hunt v5 / study 5: money scan of every non-odds condition x every bet type.

Conditions: the 913 non-price atoms of rules_v3_data (team form, previous match, last meeting, market
disagreement, league / calendar, Nesine's cut, expected corners). For each condition x priced bet type: return per 100
at closing odds in A, B, C. Kept when it made money in all three (A, B >= 80 bets; C >= 20) with return z >= 2.5.
Luck control: 5 runs with every condition shuffled across matches within each season (prevalence kept).
Writes cache/v5_conditions.parquet and cache/v5_conditions_luck.parquet.
"""
from pathlib import Path
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import miner_data as mdat  # noqa: E402
import rules_v3_data as v3  # noqa: E402
from htft_data import CACHE  # noqa: E402
from rule_miner import nice  # noqa: E402

SHUFFLES = 5


def scan(X, R, R2, per, minA=80, minC=20, zmin=2.5):
    """X: N x K conditions (0/1), R / R2: N x S returns and squared returns (0 where not priced), counts via V."""
    st = {}
    for p in "ABC":
        m = per == p
        Xp = X[m].T.astype(np.float32)
        st[p] = (Xp @ (R[m] != 0).astype(np.float32) + Xp @ ((R[m] == 0) & V[m]).astype(np.float32),
                 Xp @ R[m], Xp @ R2[m])
    n = sum(st[p][0] for p in "ABC")
    s = sum(st[p][1] for p in "ABC")
    s2 = sum(st[p][2] for p in "ABC")
    z = s / np.sqrt(np.maximum(s2 - s ** 2 / np.maximum(n, 1), 1e-9))
    ok = (st["A"][0] >= minA) & (st["B"][0] >= minA) & (st["C"][0] >= minC) & (z >= zmin)
    for p in "ABC":
        ok &= st[p][1] > 0
    return ok, z, st


if __name__ == "__main__":
    z = mdat.build()
    a = v3.build()
    keep = a["fam"] != "price"
    keep &= a["fam"] != "equal"
    X, en, fam = a["X"][:, keep], a["en"][keep], a["fam"][keep]
    O, Hm, per, names = z["O"], z["Hm"], z["per"], list(z["names"])
    V = ~np.isnan(O) & ~np.isnan(Hm)
    R = np.where(V, Hm * O - 1, 0).astype(np.float32)
    R2 = R ** 2
    ok, zz, st = scan(X, R, R2, per)
    rows = []
    for k, j in zip(*np.where(ok)):
        row = {"condition": en[k], "family": fam[k], "bet": nice(names[j]), "bet_key": names[j], "z_all": zz[k, j]}
        for p in "ABC":
            row[f"bets_{p}"] = int(st[p][0][k, j])
            row[f"return_per_100_{p}"] = st[p][1][k, j] / max(st[p][0][k, j], 1) * 100
        rows.append(row)
    res = pd.DataFrame(rows).sort_values("z_all", ascending=False) if rows else pd.DataFrame()
    rng = np.random.default_rng(13)
    luck = []
    for s in range(SHUFFLES):
        Xs = X.copy()
        for p in "ABC":
            ix = np.where(per == p)[0]
            Xs[ix] = Xs[rng.permutation(ix)]
        luck.append(int(scan(Xs, R, R2, per)[0].sum()))
    res.to_parquet(CACHE / "v5_conditions.parquet")
    pd.DataFrame({"shuffle": range(SHUFFLES), "found": luck}).to_parquet(CACHE / "v5_conditions_luck.parquet")
    pd.set_option("display.width", 250); pd.set_option("display.max_colwidth", 90)
    print(f"conditions {X.shape[1]} x bets {len(names)}; real {len(res)}; shuffled {luck}")
    if len(res):
        print(res.head(40).round(1).to_string())
