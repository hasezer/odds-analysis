"""Do the v3 rules raise high-odds hit rates BEYOND what the odds of those matches already say? (2026/27 exam)

Rules: v3 hit-track rules picked on A + B only (cache/rules_v3_ab.parquet), for the high-odds targets of hi_data.
For each rule's C matches:
  hit          actual hit rate (outcome from the score, every match)
  odds_say     the bet's own price (Nesine's chance, or the goal model for combined bets), calibrated on A + B
  z            (hits - expected) / sqrt(variance): above 0 = beat the odds
  odds_filter  hit rate of the same number of C matches where the bet was cheapest (plain odds filter)
The odds' chance is also shifted (one logit offset) so that over ALL C matches it equals the C hit rate: a whole
season with more goals than the odds expected must not make every goal-heavy rule look good.
No-edge twin: the same rules with C results drawn at random from the calibrated odds (5 draws) -> how many rules
reach z >= 2 if odds were the whole story.
Writes cache/hi_compare.parquet and cache/hi_compare_luck.parquet.
"""
from pathlib import Path
import sys

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression

sys.path.insert(0, str(Path(__file__).resolve().parent))
import hi_data  # noqa: E402
import hi_rank  # noqa: E402
import rules_v3_data as v3  # noqa: E402
from htft_data import CACHE  # noqa: E402

DRAWS = 5


def calibrated(d, Fq, j, ti, fit_mask):
    y = d["Y"][:, j]
    ps = np.where(np.isnan(d["F"][:, ti]), Fq[:, j], d["F"][:, ti]) if ti >= 0 else Fq[:, j].copy()
    ps = np.where(np.isnan(ps), np.nanmean(y), ps)
    lg = np.log(np.clip(ps, 1e-4, 1 - 1e-4) / (1 - np.clip(ps, 1e-4, 1 - 1e-4)))[:, None]
    ok = fit_mask & ~np.isnan(y)
    cal = LogisticRegression(C=1e6).fit(lg[ok], y[ok].astype(int))
    return ps, cal.predict_proba(lg)[:, 1]


def run():
    d = hi_data.build()
    Fq = hi_rank.goal_model_probs(d)
    per = d["per"]
    C = per == "C"
    a = v3.build()
    XC = a["X"][C]
    r = pd.read_parquet(CACHE / "rules_v3_ab.parquet", columns=["target_key", "target", "rule", "conditions",
                                                                "atoms", "families", "ab_hit", "hit_A", "hit_B",
                                                                "matches_A", "matches_B"])
    r = r[r["ab_hit"]]
    tk = list(d["tkeys"])
    rng = np.random.default_rng(5)
    rows, luck = [], []
    for key, g in r.groupby("target_key"):
        if key not in tk:
            continue
        j = tk.index(key)
        ti = d["tprice"][j]
        y = d["Y"][C, j]
        ps, pcal = calibrated(d, Fq, j, ti, np.isin(per, ["A", "B"]))
        ps, pcal = ps[C], pcal[C]
        ok = ~np.isnan(y)
        from scipy.optimize import brentq
        lp = np.log(pcal / (1 - pcal))
        shift = brentq(lambda c: (1 / (1 + np.exp(-(lp[ok] + c)))).mean() - y[ok].mean(), -3, 3)
        pcal = 1 / (1 + np.exp(-(lp + shift)))                 # season-level drift removed
        cum = np.concatenate([[0], np.cumsum(y[ok][np.argsort(-ps[ok], kind="stable")])])
        sims = (rng.random((DRAWS, len(y))) < pcal[None, :]).astype(float)
        M = np.stack([XC[:, [int(x) for x in at.split(",")]].all(1) for at in g["atoms"]], 1) & ok[:, None]
        n = M.sum(0)
        h = np.nan_to_num(y) @ M
        e = pcal @ M
        v = (pcal * (1 - pcal)) @ M
        z = (h - e) / np.sqrt(np.maximum(v, 1e-9))
        zs = ((sims * ok) @ M - e[None, :]) / np.sqrt(np.maximum(v, 1e-9))[None, :]
        big = n >= 30
        luck.append({"target": g["target"].iloc[0], "target_key": key, "rules": int(big.sum()),
                     "z>=2 real": int(((z >= 2) & big).sum()),
                     "z>=2 no-edge twin (avg)": float(((zs >= 2) & big[None, :]).sum(1).mean()),
                     "z<=-2 real": int(((z <= -2) & big).sum())})
        out = g.assign(matches_C=n, hits_C=h, hit_C=h / np.maximum(n, 1) * 100, odds_say_C=e / np.maximum(n, 1) * 100,
                       z_beyond_odds_C=z, normal_C=np.nanmean(y) * 100,
                       odds_filter_same_size_C=[cum[min(k, len(cum) - 1)] / max(k, 1) * 100 for k in n])
        rows.append(out[big])
        print(f"{g['target'].iloc[0][:40]:40s} rules {big.sum():6d}  z>=2 {luck[-1]['z>=2 real']:5d}  "
              f"twin {luck[-1]['z>=2 no-edge twin (avg)']:7.1f}  z<=-2 {luck[-1]['z<=-2 real']:5d}", flush=True)
    res = pd.concat(rows)
    res.drop(columns=["ab_hit"]).to_parquet(CACHE / "hi_compare.parquet")
    pd.DataFrame(luck).to_parquet(CACHE / "hi_compare_luck.parquet")
    return res, pd.DataFrame(luck)


if __name__ == "__main__":
    res, luck = run()
    print(luck[["rules", "z>=2 real", "z>=2 no-edge twin (avg)", "z<=-2 real"]].sum())
