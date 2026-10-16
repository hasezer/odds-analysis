"""Price + corrections: start from Nesine's own chance for the bet and let LightGBM learn only corrections.

Same targets, walk-forward folds and coverage levels as hi_rank.py. The model's starting point (init_score) is
the logit of the price score of hi_rank (Nesine's own chance, or the goal model for combined bets), so it can
only beat "pick the matches where the bet is cheapest" if the other ~400 features add something real.
Writes cache/hi_boost.parquet (rows like hi_rank, method "price+fix").
"""
from pathlib import Path
import sys
import time

import numpy as np
import pandas as pd
from lightgbm import LGBMClassifier

sys.path.insert(0, str(Path(__file__).resolve().parent))
import hi_data  # noqa: E402
import hi_rank  # noqa: E402
from htft_data import CACHE  # noqa: E402


def logit(p):
    p = np.clip(p, 1e-4, 1 - 1e-4)
    return np.log(p / (1 - p))


def run():
    d = hi_data.build()
    X, Y, per = d["X"], d["Y"], d["per"]
    Fq = hi_rank.goal_model_probs(d)
    rows = []
    for test, train in hi_rank.FOLDS:
        tr, te = np.isin(per, train), per == test
        fcols = np.where(((~np.isnan(X[tr])).sum(0) >= 200) & (d["ffam"] != "fair"))[0]
        for j, (tn, tk, ti) in enumerate(zip(d["tnames"], d["tkeys"], d["tprice"])):
            t0 = time.time()
            y = Y[:, j]
            base = np.where(np.isnan(d["F"][:, ti]), Fq[:, j], d["F"][:, ti]) if ti >= 0 else Fq[:, j]
            base = np.where(np.isnan(base), np.nanmean(y[tr]), base)
            odds = d["O"][te, ti] if ti >= 0 else np.full(te.sum(), np.nan, np.float32)
            okt = tr & ~np.isnan(y)
            clf = LGBMClassifier(n_estimators=150, learning_rate=.02, num_leaves=7, min_child_samples=200,
                                 subsample=.8, subsample_freq=1, colsample_bytree=.5, reg_lambda=5.0, max_bin=63,
                                 n_jobs=2, verbose=-1, random_state=0)
            clf.fit(X[okt][:, fcols], y[okt].astype(int), init_score=logit(base[okt]))
            raw = clf.predict(X[te][:, fcols], raw_score=True) + logit(base[te])
            yt = y[te]
            for c, k, h, ao, ret in hi_rank.top_hits(raw, yt, odds, hi_rank.COVER):
                rows.append({"target": tn, "target_key": tk, "test": test, "method": "price+fix", "cover": c,
                             "bets": k, "hits": h, "hit": h / k * 100, "normal": np.nanmean(yt) * 100,
                             "avg_odds": ao, "return_per_100": ret * 100 if ret == ret else np.nan})
            r5 = [r for r in rows[-5:] if r["cover"] == .05][0]
            print(f"{test} {tn[:42]:42s} top5% price+fix {r5['hit']:.1f}  ({time.time() - t0:.0f}s)", flush=True)
    r = pd.DataFrame(rows)
    r.to_parquet(CACHE / "hi_boost.parquet")
    return r


if __name__ == "__main__":
    run()
