"""Learned goal model: gradient boosting (Poisson loss) predicts home/away goals in each half from the full price list,
then every selection of every goal market is priced from those four rates.

Protocol as in book_models.py: fit on A, pick each bet type's threshold on B (>= 100 bets, return > 0, t >= 2),
refit on A+B, bet C once. Writes cache/learned_goals.parquet.
"""
from pathlib import Path
import sys
import warnings

import numpy as np
import pandas as pd
from scipy.stats import poisson
from sklearn.ensemble import HistGradientBoostingRegressor

sys.path.insert(0, str(Path(__file__).resolve().parent))
import book_models as bm  # noqa: E402
import load  # noqa: E402
import miner_data as mdat  # noqa: E402
import ml_data as md  # noqa: E402
from htft_data import CACHE  # noqa: E402

warnings.filterwarnings("ignore")


def rates(X, Y, fit_mask, pred_mask):
    out = np.zeros((pred_mask.sum(), 4), np.float32)
    for k in range(4):
        m = HistGradientBoostingRegressor(loss="poisson", max_iter=300, learning_rate=.03, max_leaf_nodes=15,
                                          min_samples_leaf=100, l2_regularization=5.0, early_stopping=True,
                                          validation_fraction=.15, random_state=0)
        m.fit(X[fit_mask], Y[fit_mask, k])
        out[:, k] = m.predict(X[pred_mask])
    return out


def price(L, names):
    """Probability of each named selection given the four goal rates (rows of L)."""
    g = md._g
    masks, cols = [], []
    keys = {}
    for n in names:
        mk, line, sk = n.split("|")
        keys.setdefault(mk, []).append(sk)
    for j, n in enumerate(names):
        mk, line, sk = n.split("|")
        p = md.predicate(mk, float(line) if line else np.nan, sk, keys[mk])
        if p is not None:
            masks.append(p.astype(np.float32)); cols.append(j)
    M = np.stack(masks, 1)
    Q = np.full((len(L), len(names)), np.nan, np.float32)
    for ix in np.array_split(np.arange(len(L)), max(1, len(L) // 1500)):
        pm = [poisson.pmf(g[None, :], L[ix, k][:, None]).astype(np.float32) for k in range(4)]
        joint = (pm[0][:, :, None, None, None] * pm[1][:, None, :, None, None] * pm[2][:, None, None, :, None]
                 * pm[3][:, None, None, None, :]).reshape(len(ix), -1)
        Q[np.ix_(ix, cols)] = joint @ M
    return Q


def run():
    z = mdat.build()
    X = bm.design(z)
    m = load.matches().set_index("match_id").loc[z["match_ids"]]
    Y = np.stack([m["ht_home"], m["ht_away"], m["ft_home"] - m["ht_home"], m["ft_away"] - m["ht_away"]], 1)
    Y = Y.astype(np.float32)
    okY = ~np.isnan(Y).any(1)
    per, O, Hm, names = z["per"], z["O"], z["Hm"], z["names"]
    A, B, C = okY & (per == "A"), okY & (per == "B"), okY & (per == "C")
    QB = price(rates(X, Y, A, B), names)
    QC = price(rates(X, Y, A | B, C), names)
    rows = []
    for s, n in enumerate(names):
        if np.isnan(QB[:, s]).all():
            continue
        oB, yB, qB = O[B, s], Hm[B, s], QB[:, s]
        okB = ~np.isnan(oB) & ~np.isnan(yB)
        best = None
        for e in bm.EDGES:
            bet = okB & (qB * oB - 1 > e)
            roi, t = bm.tstat(yB[bet] * oB[bet] - 1)
            if bet.sum() >= 100 and roi > 0 and t >= 2 and (best is None or t > best[2]):
                best = (e, roi, t, int(bet.sum()))
        row = {"bet": n}
        bet5 = okB & (qB * oB - 1 > .05)
        r5, t5 = bm.tstat(yB[bet5] * oB[bet5] - 1)
        row.update({"bets_B_at5": int(bet5.sum()), "roi_B_at5": r5})
        if best:
            e, roi, t, nb = best
            oC, yC, qC = O[C, s], Hm[C, s], QC[:, s]
            betC = ~np.isnan(oC) & ~np.isnan(yC) & (qC * oC - 1 > e)
            rC, tC = bm.tstat(yC[betC] * oC[betC] - 1)
            row.update({"passed_B": True, "edge": e, "bets_B": nb, "roi_B": roi, "t_B": t, "bets_C": int(betC.sum()),
                        "roi_C": rC, "t_C": tC})
        else:
            row["passed_B"] = False
        rows.append(row)
    r = pd.DataFrame(rows)
    r.to_parquet(CACHE / "learned_goals.parquet")
    return r


if __name__ == "__main__":
    r = run()
    pd.set_option("display.width", 250)
    print("bet types:", len(r), " passed B:", int(r["passed_B"].sum()))
    print(r[r["passed_B"]].round(2).to_string())
