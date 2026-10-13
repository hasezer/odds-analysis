"""Cross-market model: HT/FT chances implied by Nesine's *other* markets.

For every match, four goal rates are fitted (home 1st half, away 1st half, home 2nd half, away 2nd half) so that a
simple independent-Poisson model reproduces the other markets' fair probabilities as closely as possible:
team goals o/u (whole match and 1st half), total goals o/u (match and 1st half), 1X2, 1st-half 1X2, 2nd-half 1X2.
The HT/FT market itself is NOT used. The fitted rates then give a second, independent price for each HT/FT outcome.
"""
import numpy as np
import pandas as pd
from scipy.optimize import least_squares
from scipy.stats import poisson

from htft_data import HTFT

G = np.arange(11)                      # goals 0..10 per team per half


def _pmf(lam):
    return poisson.pmf(G, lam)


def _diff_dist(lh, la):
    """Distribution of (home - away) goals, index 0 = -10 ... 20 = +10."""
    return np.convolve(_pmf(lh), _pmf(la)[::-1])


def _res(d):
    n = len(d) // 2
    return d[n + 1:].sum(), d[n], d[:n].sum()          # P(home ahead), P(level), P(away ahead)


def _model(x):
    h1, a1, h2, a2 = np.exp(x)
    m = {}
    m["f_HT_TEAM_OU_HOME_0.5_UNDER"] = np.exp(-h1)
    m["f_HT_TEAM_OU_AWAY_0.5_UNDER"] = np.exp(-a1)
    for side, lam in (("HOME", h1 + h2), ("AWAY", a1 + a2)):
        for ln in (0.5, 1.5, 2.5):
            m[f"f_TEAM_OU_{side}_{ln:g}_UNDER"] = poisson.cdf(int(ln), lam)
    m["f_HT_OU_0.5_UNDER"] = np.exp(-(h1 + a1))
    m["f_HT_OU_1.5_UNDER"] = poisson.cdf(1, h1 + a1)
    for ln in (1.5, 2.5, 3.5, 4.5):
        m[f"f_OU_{ln:g}_UNDER"] = poisson.cdf(int(ln), h1 + a1 + h2 + a2)
    d1, d2 = _diff_dist(h1, a1), _diff_dist(h2, a2)
    for name, d in (("HT_1X2", d1), ("2H_1X2", d2), ("1X2", np.convolve(d1, d2))):
        p1, px, p2 = _res(d)
        m[f"f_{name}__1"], m[f"f_{name}__X"], m[f"f_{name}__2"] = p1, px, p2
    return m, d1, d2


TARGETS = list(_model(np.zeros(4))[0])


def _htft(d1, d2):
    """Joint HT/FT probabilities from the two half-time goal-difference distributions."""
    n1 = len(d1) // 2
    n2 = len(d2) // 2
    out = dict.fromkeys(HTFT, 0.0)
    sgn = lambda v: "1" if v > 0 else ("X" if v == 0 else "2")
    for i, p1 in enumerate(d1):
        if p1 < 1e-12:
            continue
        g1 = i - n1
        for j, p2 in enumerate(d2):
            if p2 < 1e-12:
                continue
            out[f"{sgn(g1)}/{sgn(g1 + j - n2)}"] += p1 * p2
    return out


def fit(w: pd.DataFrame) -> pd.DataFrame:
    T = w[TARGETS].to_numpy()
    rows = []
    for i in range(len(w)):
        t = T[i]
        ok = ~np.isnan(t)
        x0 = np.log([0.6, 0.5, 0.75, 0.65])
        r = least_squares(lambda x: np.array(list(_model(x)[0].values()))[ok] - t[ok], x0, method="lm")
        _, d1, d2 = _model(r.x)
        rows.append((*np.exp(r.x), np.sqrt(np.mean(r.fun ** 2)), *_htft(d1, d2).values()))
    cols = ["lam_h1", "lam_a1", "lam_h2", "lam_a2", "fit_rmse"] + [f"q_{k}" for k in HTFT]
    return pd.DataFrame(rows, columns=cols, index=w.index)


def _fit_chunk(df):
    return fit(df)


def build(refresh: bool = False) -> pd.DataFrame:
    """HT/FT wide table + cross-market Poisson columns (cached)."""
    from concurrent.futures import ProcessPoolExecutor
    import os
    import htft_data as hd

    out = hd.CACHE / "htft_wide_q.parquet"
    if out.exists() and not refresh:
        return pd.read_parquet(out)
    w = hd.build()
    parts = [w.iloc[ix] for ix in np.array_split(np.arange(len(w)), (os.cpu_count() or 1) * 4)]
    with ProcessPoolExecutor() as ex:
        q = pd.concat(ex.map(_fit_chunk, parts))
    w = w.join(q)
    w.to_parquet(out)
    return w


if __name__ == "__main__":
    print(build(refresh=True).shape)
