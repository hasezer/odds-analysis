"""Internal 'sure bet' scan: can stakes spread over Nesine's own markets for one match guarantee a profit?

Every goal-based selection is a set of (home 1st half, away 1st half, home 2nd half, away 2nd half) score cells
(0..7 goals each, 4,096 cells; see ml_data.predicate). For each match a linear programme finds the stakes (summing
to 1) that maximise the WORST-case return over all cells:
    max t   s.t.  sum_i s_i * odds_i * [cell in selection i] - 1 >= t  for every cell,  sum s_i = 1, s_i >= 0
t > 0 is a sure bet; t close to 0 is a 'cheap hedge'. Corners are left out (different outcome space).
Writes cache/arb_scan.parquet (one row per match: best guaranteed return and the stakes used).
"""
from pathlib import Path
import os
import sys

import numpy as np
import pandas as pd
from scipy.optimize import linprog

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ml_data as md  # noqa: E402
from htft_data import CACHE  # noqa: E402


def masks(sel):
    keys = sel.groupby("market_key")["selection_key"].unique().to_dict()
    lab = sel[["market_key", "line", "selection_key"]].drop_duplicates()
    out = {}
    for r in lab.itertuples(index=False):
        m = md.predicate(r.market_key, r.line, r.selection_key, keys.get(r.market_key, []))
        if m is not None:
            out[(r.market_key, -1.0 if pd.isna(r.line) else r.line, r.selection_key)] = m
    return out


def solve(rows, M):
    """rows: DataFrame of one match's priced selections. Returns (best worst-case return, stakes)."""
    cols, odds, labs = [], [], []
    for r in rows.itertuples(index=False):
        k = (r.market_key, -1.0 if pd.isna(r.line) else r.line, r.selection_key)
        if k in M:
            cols.append(M[k]); odds.append(r.closing_odds); labs.append(f"{k[0]}|{'' if k[1] == -1 else k[1]}|{k[2]}")
    if len(cols) < 2:
        return np.nan, ""
    W = np.stack(cols, 1).astype(float) * np.array(odds)[None, :] - 1.0     # cells x bets: return per unit stake
    n = W.shape[1]
    c = np.zeros(n + 1); c[-1] = -1.0                                       # maximise t
    A_ub = np.hstack([-W, np.ones((W.shape[0], 1))])                         # t - W s <= 0
    b_ub = np.zeros(W.shape[0])
    A_eq = np.hstack([np.ones((1, n)), np.zeros((1, 1))])
    res = linprog(c, A_ub=A_ub, b_ub=b_ub, A_eq=A_eq, b_eq=[1.0],
                  bounds=[(0, None)] * n + [(None, None)], method="highs")
    if not res.success:
        return np.nan, ""
    s = res.x[:n]
    used = "; ".join(f"{labs[i]} @{odds[i]:.2f} x{s[i]:.3f}" for i in np.argsort(-s) if s[i] > 1e-4)
    return res.x[-1], used


def _chunk(args):
    ids, sel, M = args
    out = []
    g = sel.groupby("match_id")
    for mid in ids:
        t, used = solve(g.get_group(mid), M)
        out.append((mid, t, used))
    return out


def run():
    from concurrent.futures import ProcessPoolExecutor
    mt, sel = md.build()
    sel = sel[(sel["market_key"] != "CORNERS_OU") & sel["closing_odds"].notna()]
    # Oct-Nov 2025: 211 matches carry a different market ('goal in 1st half / 2nd half') under the HT_2H_BTTS id
    hb = sel[sel["market_key"] == "HT_2H_BTTS"].pivot_table(index="match_id", columns="selection_key",
                                                              values="closing_odds")
    bad = hb.index[hb["NO/NO"] > hb["YES/YES"]]
    sel = sel[~((sel["market_key"] == "HT_2H_BTTS") & sel["match_id"].isin(bad))]
    M = masks(sel)
    ids = sel["match_id"].unique()
    parts = np.array_split(ids, (os.cpu_count() or 1) * 8)
    res = []
    with ProcessPoolExecutor() as ex:
        for k, r in enumerate(ex.map(_chunk, [(p, sel[sel["match_id"].isin(p)], M) for p in parts])):
            res += r
            print(f"chunk {k + 1}/{len(parts)} done", flush=True)
    r = pd.DataFrame(res, columns=["match_id", "best_guaranteed_return", "stakes"])
    r = r.merge(mt[["match_id", "league_id", "season", "kickoff_utc"]], on="match_id")
    r.to_parquet(CACHE / "arb_scan.parquet")
    return r


if __name__ == "__main__":
    r = run()
    print(r["best_guaranteed_return"].describe())
    print("sure bets (> 0):", int((r["best_guaranteed_return"] > 0).sum()))
