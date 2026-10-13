"""Whole-book models: predict each selection from ALL ~160 prices of the match.

For every one of the 162 common selection types, three learners see the full price list (log odds, missing = median
plus a missing flag) and the league:
  lr   logistic regression (L2)
  gbm  gradient boosting
  knn  'similar matches': outcome rate of the 300 most similar past price lists
Protocol (fixed before running): train on A, choose the betting threshold on B (edge in {0, 5, 10, 20%}; needs
>= 100 bets, return > 0 and t >= 2 on B), then retrain on A+B and bet period C once with that threshold.
Writes cache/book_models.parquet.
"""
from pathlib import Path
import sys
import warnings

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.neighbors import KNeighborsClassifier
from sklearn.preprocessing import StandardScaler

sys.path.insert(0, str(Path(__file__).resolve().parent))
import miner_data as mdat  # noqa: E402
from htft_data import CACHE  # noqa: E402

warnings.filterwarnings("ignore")
EDGES = [0.0, 0.05, 0.10, 0.20]


def design(z):
    L = np.log(z["O"])
    with np.errstate(all="ignore"):
        med = np.nan_to_num(np.nanmedian(L[z["per"] == "A"], axis=0))     # markets new after period A -> 0
    miss = np.isnan(L)
    X = np.where(miss, med, L)
    keep_miss = miss.mean(0) > .02
    lg = pd.get_dummies(pd.Series(z["league"])).to_numpy(np.float32)
    return np.hstack([X, miss[:, keep_miss].astype(np.float32), lg]).astype(np.float32)


def tstat(profit):
    n = len(profit)
    if n < 2:
        return np.nan, np.nan
    m = profit.mean()
    return m * 100, m / (profit.std(ddof=1) / np.sqrt(n))


def learners():
    return {
        "lr": lambda: LogisticRegression(C=0.05, max_iter=3000),
        "gbm": lambda: HistGradientBoostingClassifier(max_iter=150, learning_rate=.06, max_leaf_nodes=15, max_bins=63,
                                                      min_samples_leaf=100, l2_regularization=5.0,
                                                      early_stopping=True, validation_fraction=.15,
                                                      n_iter_no_change=15, random_state=0),
        "knn": lambda: KNeighborsClassifier(n_neighbors=300, weights="uniform"),
    }


def run(shard=0, nshards=1):
    z = mdat.build()
    X = design(z)
    O, Hm, per, names = z["O"], z["Hm"], z["per"], z["names"]
    rows = []
    for s in range(len(names)):
        if s % nshards != shard:
            continue
        ok = ~np.isnan(Hm[:, s]) & ~np.isnan(O[:, s])
        A, B, C = ok & (per == "A"), ok & (per == "B"), ok & (per == "C")
        if A.sum() < 2000 or B.sum() < 1000:
            continue
        y = Hm[:, s]
        for name, make in learners().items():
            sc = StandardScaler().fit(X[A])
            m = make().fit(sc.transform(X[A]), y[A].astype(int))
            pB = m.predict_proba(sc.transform(X[B]))[:, 1]
            best = None
            for e in EDGES:
                bet = pB * O[B, s] - 1 > e
                prof = (y[B][bet] * O[B, s][bet]) - 1
                roi, t = tstat(prof)
                if bet.sum() >= 100 and roi > 0 and t >= 2 and (best is None or t > best[2]):
                    best = (e, roi, t, int(bet.sum()))
            row = {"bet": names[s], "model": name}
            if best is None:
                # still report the B result at the default 5% edge for the overview
                bet = pB * O[B, s] - 1 > .05
                roi, t = tstat((y[B][bet] * O[B, s][bet]) - 1)
                row.update({"passed_B": False, "edge": .05, "bets_B": int(bet.sum()), "roi_B": roi, "t_B": t})
            else:
                e, roi, t, n = best
                sc2 = StandardScaler().fit(X[A | B])
                m2 = make().fit(sc2.transform(X[A | B]), y[A | B].astype(int))
                pC = m2.predict_proba(sc2.transform(X[C]))[:, 1]
                betC = pC * O[C, s] - 1 > e
                rC, tC = tstat((y[C][betC] * O[C, s][betC]) - 1)
                row.update({"passed_B": True, "edge": e, "bets_B": n, "roi_B": roi, "t_B": t,
                            "bets_C": int(betC.sum()), "roi_C": rC, "t_C": tC})
            rows.append(row)
        r = pd.DataFrame(rows)
        print(f"shard {shard}: bet type {s + 1}/{len(names)} done; passed B so far: {int(r['passed_B'].sum())}",
              flush=True)
    r = pd.DataFrame(rows)
    r.to_parquet(CACHE / f"book_models_{shard}of{nshards}.parquet")
    return r


if __name__ == "__main__":
    shard, nshards = (int(sys.argv[1]), int(sys.argv[2])) if len(sys.argv) > 2 else (0, 1)
    r = run(shard, nshards)
    pd.set_option("display.width", 250)
    print(r[r["passed_B"]].round(2).to_string())
