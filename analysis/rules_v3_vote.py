"""Rule stacking: when MANY rules point at the same bet in one match, does it hit even more often?

Three groups of rules per bet: "hit" and "price" (passed that track's A and B gates) and "money" (any of them that
made money in both A and B). Rules are taken from `rules_v3.py --keep-ab` (cache/rules_v3_ab.parquet): found on period A and confirmed on B,
WITHOUT looking at C. For every C match (2026/27 + 2026, never used to pick these rules) we count how many of the
bet's rules are true, and compare hit rate, Nesine's price and return across those counts.
Writes cache/rules_v3_vote.parquet.
"""
from pathlib import Path
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import miner_data as mdat  # noqa: E402
import rules_v3 as rv  # noqa: E402
import rules_v3_data as v3  # noqa: E402
from htft_data import CACHE  # noqa: E402

BUCKETS = [(0, 0, "no rule"), (1, 4, "1–4 rules"), (5, 19, "5–19 rules"), (20, 99, "20–99 rules"),
           (100, 10 ** 9, "100+ rules")]


def run():
    r = pd.read_parquet(CACHE / "rules_v3_ab.parquet")
    z, a = mdat.build(), v3.build()
    C = z["per"] == "C"
    XC = a["X"][C]
    tg = {t["key"]: t for t in rv.targets(z)}
    out = []
    for tk, g in r.groupby("target_key"):
        t = tg[tk]
        y, f, o = t["y"][C], t["f"][C], t["o"][C]
        g = g.assign(ab_money=(g["priced_A"] >= 100) & (g["priced_B"] >= 100) & (g["ret_A"] > 0) & (g["ret_B"] > 0))
        for track in ("hit", "price", "money"):
            rules = g[g[f"ab_{track}"]]
            if not len(rules):
                continue
            cnt = np.zeros(C.sum(), int)
            for at in rules["atoms"]:
                cnt += XC[:, [int(x) for x in at.split(",")]].all(1)
            ok = ~np.isnan(y)
            for lo, hi, lab in BUCKETS:
                m = ok & (cnt >= lo) & (cnt <= hi)
                pm = m & ~np.isnan(f) & ~np.isnan(o)
                out.append({"bet": t["name"], "bet_key": tk, "track": track, "rules": len(rules), "bucket": lab,
                            "matches_C": int(m.sum()), "hit_C": y[m].mean() * 100 if m.sum() else np.nan,
                            "normal_C": y[ok].mean() * 100,
                            "price_says_C": f[pm].mean() * 100 if pm.sum() else np.nan,
                            "return_per_100_C": (y[pm] * o[pm] - 1).mean() * 100 if pm.sum() else np.nan})
    v = pd.DataFrame(out)
    v.to_parquet(CACHE / "rules_v3_vote.parquet")
    return v


if __name__ == "__main__":
    v = run()
    pd.set_option("display.width", 200)
    print(v.round(1).to_string())
