"""Score the walk-forward predictions (analysis/cache/ml_oos.parquet from ml_walkforward.py).

Only out-of-sample predictions are used (every prediction was made by a model trained on earlier matches only).
Betting rules are fixed in advance: bet a selection when model probability x odds is above 1 + edge, edge in
{0%, 5%, 10%, 20%}. Results are split into B = 2025 + 2025/26 and C = 2026 + 2026/27 (so far): a real signal has to
show up in both.
"""
from pathlib import Path
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from htft_data import CACHE  # noqa: E402

EDGES = [0.0, 0.05, 0.10, 0.20]


def _ll(y, p):
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return -(y * np.log(p) + (1 - y) * np.log(1 - p)).mean()


def roi_ci(d):
    """ROI with a match-clustered 95% interval."""
    if len(d) == 0:
        return np.nan, np.nan, np.nan
    g = d.groupby("match_id").agg(p=("profit", "sum"), n=("profit", "size"))
    roi = g["p"].sum() / g["n"].sum()
    k = len(g)
    se = np.sqrt(k / max(k - 1, 1) * ((g["p"] - roi * g["n"]) ** 2).sum()) / g["n"].sum() if k > 1 else np.nan
    return roi * 100, (roi - 1.96 * se) * 100, (roi + 1.96 * se) * 100


def evaluate(res=None):
    res = pd.read_parquet(CACHE / "ml_oos.parquet") if res is None else res
    res = res.copy()
    res["sub"] = np.where(res["kickoff_utc"] < pd.Timestamp("2026-01-01", tz="UTC"), "B", "C")
    res.loc[res["period"] == "discovery", "sub"] = "B"       # (none expected: predictions start 2025-01-01)
    res["profit"] = np.where(res["hit"], res["closing_odds"] - 1, -1.0)
    res["base"] = res["fair"].fillna(res["implied"])

    acc = []
    for mk, d in res.groupby("market_key"):
        y = d["hit"].to_numpy(float)
        acc.append({"market": mk, "predictions": len(d),
                    "logloss_price": _ll(y, d["base"].to_numpy()),
                    "logloss_lr": _ll(y, d["p_lr"].to_numpy()),
                    "logloss_gbm": _ll(y, d["p_gbm"].to_numpy())})
    acc = pd.DataFrame(acc)
    acc["gbm_vs_price_pct"] = (acc["logloss_price"] - acc["logloss_gbm"]) / acc["logloss_price"] * 100
    acc["lr_vs_price_pct"] = (acc["logloss_price"] - acc["logloss_lr"]) / acc["logloss_price"] * 100

    bets = []
    for model in ("p_gbm", "p_lr"):
        ev = res[model] * res["closing_odds"] - 1
        for edge in EDGES:
            b = res[ev > edge]
            for mk, d in list(b.groupby("market_key")) + [("ALL MARKETS", b)]:
                row = {"model": model[2:], "edge": f">{edge:.0%}", "market": mk}
                for sub in ("B", "C"):
                    s = d[d["sub"] == sub]
                    r, lo, hi = roi_ci(s)
                    row.update({f"bets_{sub}": len(s), f"roi_{sub}": r, f"low_{sub}": lo, f"high_{sub}": hi})
                bets.append(row)
    bets = pd.DataFrame(bets)
    return acc.round(5), bets.round(1)


if __name__ == "__main__":
    pd.set_option("display.width", 250); pd.set_option("display.max_rows", 500)
    acc, bets = evaluate()
    print(acc.sort_values("gbm_vs_price_pct", ascending=False).to_string(index=False))
    print(bets[bets["market"] == "ALL MARKETS"].to_string(index=False))
    both = bets[(bets["roi_B"] > 0) & (bets["roi_C"] > 0) & (bets["bets_B"] >= 100) & (bets["bets_C"] >= 50)]
    print("\npositive in both B and C:\n", both.to_string(index=False))
