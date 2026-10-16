"""Honest forward test of the deep rule book.

Rules are ranked using ONLY periods A + B (2024/25 + 2024, 2025/26 + 2025). The top K rules per bet are then applied
to period C (2026/27 + 2026 so far), which played no part in ranking: every C match where at least one rule fires is
'bet' once at Nesine's closing price. Compared with: the bet's normal C hit rate and the price-implied rate.
Writes cache/rules_forward.parquet.
"""
from pathlib import Path
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import miner_data as mdat  # noqa: E402
import rules_deep as rd  # noqa: E402
from htft_data import CACHE  # noqa: E402


def run(ks=(5, 10, 30, 100)):
    z = mdat.build()
    O, F, per, names = z["O"], z["F"], z["per"], list(z["names"])
    spec, lab, mkt = rd.atoms(z)
    XC = rd.masks(spec, O[per == "C"])
    T, own, price_lab = rd.build_targets(z["match_ids"])
    r = pd.read_parquet(CACHE / "rules_deep.parquet")
    nAB = r["matches_A"] + r["matches_B"]
    hAB = r["hits_A"] + r["hits_B"]
    bAB = (r["normal_A"] * r["matches_A"] + r["normal_B"] * r["matches_B"]) / nAB / 100
    r["z_AB"] = (hAB / nAB - bAB) / np.sqrt(bAB * (1 - bAB) / nAB)
    rows = []
    for t, g in r.groupby("target", sort=False):
        if t not in price_lab or price_lab[t] not in names:
            continue
        j = names.index(price_lab[t])
        y = np.nan_to_num(T[t][per == "C"])
        o, f = O[per == "C", j], F[per == "C", j]
        okp = ~np.isnan(o) & ~np.isnan(f) & ~np.isnan(T[t][per == "C"])
        allC = {"bets": int(okp.sum()), "hit": y[okp].mean() * 100, "price": f[okp].mean() * 100,
                "roi": (y[okp] * o[okp] - 1).mean() * 100}
        g = g.sort_values("z_AB", ascending=False)
        for k in ks:
            fire = np.zeros(len(y), bool)
            for a in g["atoms"].head(k):
                fire |= np.prod(XC[:, [int(x) for x in a.split(",")]], axis=1) > 0
            m = fire & okp
            n = int(m.sum())
            hit = y[m].mean() * 100 if n else np.nan
            prof = y[m] * o[m] - 1
            roi = prof.mean() * 100 if n else np.nan
            se = prof.std(ddof=1) / np.sqrt(n) * 100 if n > 1 else np.nan
            rows.append({"bet": t, "top_rules": k, "C_bets": n, "C_hit_%": hit, "C_price_says_%": f[m].mean() * 100 if n else np.nan,
                         "C_return_%": roi, "C_return_low": roi - 1.96 * se if n > 1 else np.nan,
                         "C_return_high": roi + 1.96 * se if n > 1 else np.nan,
                         "all_C_bets": allC["bets"], "all_C_hit_%": allC["hit"], "all_C_return_%": allC["roi"]})
    out = pd.DataFrame(rows)
    out.to_parquet(CACHE / "rules_forward.parquet")
    return out


if __name__ == "__main__":
    pd.set_option("display.width", 250); pd.set_option("display.max_rows", 300)
    out = run()
    print(out.round(1).to_string(index=False))
