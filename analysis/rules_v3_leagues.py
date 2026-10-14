"""League x bet scan on real returns: which bets has a league paid in EVERY period?

For every league and every priced bet type (miner.npz selections): return per 100 staked in A, B, C and a
return z-score over all periods (sum of returns / its standard deviation). A combination is listed when
it made money in all three periods and its z >= 2. Luck control: 20 runs with the league labels shuffled
across matches inside each period (each match keeps its own odds and result).
Writes cache/rules_v3_leagues.parquet and cache/rules_v3_leagues_luck.parquet.
"""
from pathlib import Path
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import miner_data as mdat  # noqa: E402
from dashboard import leagues  # noqa: E402
from htft_data import CACHE  # noqa: E402
from rule_miner import nice  # noqa: E402

SHUFFLES = 20
Z_MIN = 2.0


def scan(lg, per, O, Hm, names, min_n=40):
    rows = []
    L = pd.Index(sorted(set(lg)))
    li = L.get_indexer(lg)
    for i, lab in enumerate(names):
        o, y = O[:, i], Hm[:, i]
        ok = ~np.isnan(o) & ~np.isnan(y)
        ret = np.where(ok, y * o - 1, 0.0)
        res = {}
        for p in "ABC":
            m = ok & (per == p)
            n = np.bincount(li[m], minlength=len(L))
            s = np.bincount(li[m], weights=ret[m], minlength=len(L))
            s2 = np.bincount(li[m], weights=ret[m] ** 2, minlength=len(L))
            h = np.bincount(li[m], weights=y[m], minlength=len(L))
            res[p] = (n, s, s2, h)
        n = sum(res[p][0] for p in "ABC"); s = sum(res[p][1] for p in "ABC"); s2 = sum(res[p][2] for p in "ABC")
        var = s2 - s ** 2 / np.maximum(n, 1)
        z = s / np.sqrt(np.maximum(var, 1e-9))
        good = np.all([(res[p][0] >= min_n) & (res[p][1] > 0) for p in "AB"], axis=0) \
            & (res["C"][0] >= 15) & (res["C"][1] > 0) & (z >= Z_MIN)
        for k in np.where(good)[0]:
            row = {"league": L[k], "bet_key": lab, "bet": nice(lab), "z_all": z[k], "matches_all": int(n[k]),
                   "return_per_100_all": s[k] / n[k] * 100}
            for p in "ABC":
                nn, ss, _, hh = (x[k] for x in res[p])
                row.update({f"matches_{p}": int(nn), f"hit_{p}": hh / nn * 100, f"return_per_100_{p}": ss / nn * 100})
            rows.append(row)
    return pd.DataFrame(rows)


def run():
    z = mdat.build()
    O, Hm, per, names = z["O"], z["Hm"], z["per"], list(z["names"])
    lg = z["league"].astype(str)
    real = scan(lg, per, O, Hm, names)
    names_l = leagues()
    if len(real):
        real["league_name"] = real["league"].map(lambda l: names_l.get(l, {}).get("en", l))
        real = real.sort_values("z_all", ascending=False)
    rng = np.random.default_rng(7)
    luck = []
    for s in range(SHUFFLES):
        lg_s = lg.copy()
        for p in "ABC":
            ix = np.where(per == p)[0]
            lg_s[ix] = rng.permutation(lg[ix])
        luck.append(len(scan(lg_s, per, O, Hm, names)))
    real.to_parquet(CACHE / "rules_v3_leagues.parquet")
    pd.DataFrame({"shuffle": range(SHUFFLES), "found": luck}).to_parquet(CACHE / "rules_v3_leagues_luck.parquet")
    return real, luck


if __name__ == "__main__":
    real, luck = run()
    pd.set_option("display.width", 250)
    print(f"real: {len(real)} league x bet combinations;  shuffled: mean {np.mean(luck):.1f}, max {max(luck)}")
    print(real.round(1).to_string())
