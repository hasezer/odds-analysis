"""6+ goals deep dive. Shared data + study 1 (profile: which signals separate 6+ games, and which know more than
the 6+ price itself).

p6 = the match's 6+ chance from Nesine: its own 6+ market (cut removed) where offered, else the goal model fitted to
its core prices. "Beyond the price" = how well a signal separates 6+ games among matches with the SAME p6
(stratified AUC over 20 p6 bands; 0.5 = nothing extra).
"""
from pathlib import Path
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import hi_data  # noqa: E402
import hi_rank  # noqa: E402
import load  # noqa: E402
from htft_data import CACHE  # noqa: E402

OUT = Path(__file__).resolve().parent / "output"
SEAS = {"A": "2024/25", "B": "2025/26", "C": "2026/27"}


def data():
    """Matches with outcome, scores, p6, the 6+ odds and all hi_data features (cached in memory per process)."""
    d = hi_data.build()
    tk = list(d["tkeys"])
    j = tk.index("GOAL_RANGE||6+")
    Fq = hi_rank.goal_model_probs(d)
    names = list(d["names"])
    i6 = names.index("GOAL_RANGE||6+")
    p6 = np.where(np.isnan(d["F"][:, i6]), Fq[:, j], d["F"][:, i6])
    m = load.matches().set_index("match_id").reindex(d["ids"])
    D = pd.DataFrame({"y": d["Y"][:, j], "p6": p6, "q6": Fq[:, j], "odds6": d["O"][:, i6], "per": d["per"],
                      "league": d["league"], "fh": m["ft_home"].to_numpy(), "fa": m["ft_away"].to_numpy(),
                      "hh": m["ht_home"].to_numpy(), "ha": m["ht_away"].to_numpy()}, index=d["ids"])
    X = pd.DataFrame(d["X"], columns=d["fnames"], index=d["ids"])
    ok = D["y"].notna() & D["p6"].notna()
    return D[ok], X[ok], d


def auc(score, y):
    """Rank AUC; NaN scores dropped."""
    ok = ~np.isnan(score)
    s, t = score[ok], y[ok]
    n1, n0 = t.sum(), (1 - t).sum()
    if n1 < 10 or n0 < 10:
        return np.nan
    r = pd.Series(s).rank().to_numpy()
    return (r[t == 1].sum() - n1 * (n1 + 1) / 2) / (n1 * n0)


def strat_auc(score, y, p, nb=20):
    """AUC within p bands, averaged with weights = number of 6+ games in the band."""
    bands = pd.qcut(p, nb, labels=False, duplicates="drop")
    num = den = 0.0
    for b in np.unique(bands):
        m = bands == b
        a = auc(score[m], y[m])
        if a == a:
            w = y[m].sum()
            num += a * w; den += w
    return num / den if den else np.nan


def profile(D, X):
    rows = []
    for c in X.columns:
        v = X[c].to_numpy(float)
        if np.isnan(v).mean() > .6:
            continue
        row = {"signal": c, "family": c.split(":")[0], "coverage": 1 - np.isnan(v).mean(),
               "AUC (all)": auc(v, D["y"].to_numpy())}
        for p, nm in SEAS.items():
            m = (D["per"] == p).to_numpy()
            row[f"beyond price {nm}"] = strat_auc(v[m], D["y"].to_numpy()[m], D["p6"].to_numpy()[m])
        y6, n6 = D["y"].to_numpy() == 1, D["y"].to_numpy() == 0
        row["median in 6+ games"] = np.nanmedian(v[y6])
        row["median in other games"] = np.nanmedian(v[n6])
        rows.append(row)
    r = pd.DataFrame(rows)
    bp = r[[f"beyond price {s}" for s in SEAS.values()]]
    r["beyond price (min distance from 0.5, same direction)"] = np.where(
        (bp > .5).all(1), (bp - .5).min(1), np.where((bp < .5).all(1), (bp - .5).max(1), 0))
    r["base AUC of the 6+ price itself"] = auc(D["p6"].to_numpy(), D["y"].to_numpy())
    return r.sort_values("beyond price (min distance from 0.5, same direction)", key=abs, ascending=False)


if __name__ == "__main__":
    D, X, _ = data()
    print(f"matches {len(D)}, 6+ games {int(D['y'].sum())} ({D['y'].mean() * 100:.1f}%)")
    r = profile(D, X)
    r.to_parquet(CACHE / "six_plus_profile.parquet")
    pd.set_option("display.width", 250); pd.set_option("display.max_colwidth", 60)
    print("AUC of the 6+ price itself:", round(r["base AUC of the 6+ price itself"].iloc[0], 3))
    print(r.sort_values("AUC (all)", key=lambda s: (s - .5).abs(), ascending=False).head(15)[
        ["signal", "AUC (all)", "median in 6+ games", "median in other games"]].round(3).to_string())
    print(r.head(25)[["signal", "AUC (all)", "beyond price 2024/25", "beyond price 2025/26", "beyond price 2026/27",
                      "beyond price (min distance from 0.5, same direction)"]].round(3).to_string())
