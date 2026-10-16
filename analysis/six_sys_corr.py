"""Are 6+ games (and goals above expectation) correlated between matches? Nesine multiplies the odds of a combo
coupon as if its games were independent; positive correlation would make a combo of related games worth more.

Pairs of matches:
  same league, same day      |  different leagues, same day  |  same league, 7 days apart (placebo)
For each: joint 6+ lift = P(both 6+) / expected under independence (using calibrated 6+ chances), and the correlation
of goal residuals (goals - Nesine's expected goals). Confidence intervals by bootstrap over days.
Also league momentum: does a league's goal residual over its previous 30 matches (this season) predict the next
match's residual / 6+? And same-day momentum: residual of the league's earlier kick-offs that day -> later matches.
Writes cache/six_sys_corr.parquet.
"""
from pathlib import Path
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import six_plus as sp  # noqa: E402
import six_sys_data as sd  # noqa: E402
from htft_data import CACHE  # noqa: E402


def pair_sums(df, key):
    """Per group: sum over unordered pairs of y_i*y_j, p_i*p_j, r_i*r_j and number of pairs."""
    g = df.groupby(key)
    s = pd.DataFrame({
        "n": g.size(),
        "sy": g["y6"].sum(), "syy": g["y6"].apply(lambda v: (v ** 2).sum()),
        "sp": g["p6_cal"].sum(), "spp": g["p6_cal"].apply(lambda v: (v ** 2).sum()),
        "sr": g["res"].sum(), "srr": g["res"].apply(lambda v: (v ** 2).sum())})
    s["pairs"] = s["n"] * (s["n"] - 1) / 2
    s["yy"] = (s["sy"] ** 2 - s["syy"]) / 2
    s["pp"] = (s["sp"] ** 2 - s["spp"]) / 2
    s["rr"] = (s["sr"] ** 2 - s["srr"]) / 2
    return s


def summarize(s, var_r, rng, label, boot=500):
    def stat(x):
        return x["yy"].sum() / x["pp"].sum(), x["rr"].sum() / x["pairs"].sum() / var_r
    lift, corr = stat(s)
    idx = np.arange(len(s))
    bl, bc = [], []
    for _ in range(boot):
        b = s.iloc[rng.choice(idx, len(idx))]
        a, c = stat(b)
        bl.append(a); bc.append(c)
    return {"pairs": label, "pair count": int(s["pairs"].sum()), "both 6+ observed": int(s["yy"].sum()),
            "both 6+ expected if independent": round(float(s["pp"].sum()), 1), "joint 6+ lift": lift,
            "lift 95% low": np.percentile(bl, 2.5), "lift 95% high": np.percentile(bl, 97.5),
            "goal-residual correlation": corr, "corr 95% low": np.percentile(bc, 2.5),
            "corr 95% high": np.percentile(bc, 97.5)}


def run():
    S = sd.build()
    S = S[S["lam"].notna()].copy()
    S["res"] = S["goals"] - S["lam"]
    S["res"] -= S.groupby("per")["res"].transform("mean")          # remove season-level drift
    var_r = S["res"].var()
    rng = np.random.default_rng(0)
    rows = []
    for p in ["all", "A", "B", "C"]:
        x = S if p == "all" else S[S["per"] == p]
        same = pair_sums(x, ["league", "date"])
        day = pair_sums(x, ["date"])
        cross = day.copy()                                   # same day minus same league = different leagues
        sl = same.groupby(level="date")[["yy", "pp", "rr", "pairs"]].sum()
        cross[["yy", "pp", "rr", "pairs"]] = cross[["yy", "pp", "rr", "pairs"]] - sl.reindex(cross.index).fillna(0)
        # placebo: league's matches on day d paired with its matches on day d+7
        x2 = x.assign(d=pd.to_datetime(x["date"]))
        a = x2.groupby(["league", "d"]).agg(sy=("y6", "sum"), sp=("p6_cal", "sum"), sr=("res", "sum"), n=("y6", "size"))
        b = a.copy(); b.index = b.index.set_levels(b.index.levels[1] - pd.Timedelta(days=7), level=1)
        j = a.join(b, rsuffix="_7", how="inner")
        plac = pd.DataFrame({"yy": j["sy"] * j["sy_7"], "pp": j["sp"] * j["sp_7"], "rr": j["sr"] * j["sr_7"],
                             "pairs": j["n"] * j["n_7"]})
        for lab, s in (("same league, same day", same), ("different leagues, same day", cross),
                       ("same league, 7 days apart (placebo)", plac)):
            r = summarize(s[s["pairs"] > 0], var_r, rng, lab)
            r["season"] = {"all": "all", **sp.SEAS}[p]
            rows.append(r)
    corr = pd.DataFrame(rows)
    # league momentum: previous 30 matches of the league this season (strictly earlier days)
    S = S.sort_values("kick")
    mom = []
    for (lg, per), g in S.groupby(["league", "per"]):
        dd = g.groupby("date")["res"].agg(["sum", "size"])
        cs, cn = dd["sum"].cumsum().shift(1), dd["size"].cumsum().shift(1)
        # rolling over the last ~30 matches: use days until 30 matches reached
        roll_s = dd["sum"].rolling(10, min_periods=3).sum().shift(1)
        roll_n = dd["size"].rolling(10, min_periods=3).sum().shift(1)
        m = g[["date"]].join((roll_s / roll_n).rename("league_mom"), on="date")
        m = m.join((cs / cn).rename("league_season_res"), on="date")
        mom.append(m[["league_mom", "league_season_res"]])
    S = S.join(pd.concat(mom))
    # same-day momentum: league's earlier kick-offs that day (finished >= 2 h before this kick-off)
    S["sameday_prior"] = np.nan
    for (lg, dt), g in S.groupby(["league", "date"]):
        if len(g) < 2:
            continue
        k = g["kick"].to_numpy()
        r = g["res"].to_numpy()
        vals = []
        for i in range(len(g)):
            prior = k <= k[i] - np.timedelta64(2, "h")
            vals.append(r[prior].mean() if prior.any() else np.nan)
        S.loc[g.index, "sameday_prior"] = vals
    mrows = []
    for col in ("league_mom", "league_season_res", "sameday_prior"):
        for p, nm in [("all", "all")] + list(sp.SEAS.items()):
            x = S if p == "all" else S[S["per"] == p]
            x = x[x[col].notna()]
            if len(x) < 100:
                continue
            mrows.append({"signal": col, "season": nm, "matches": len(x),
                          "corr with goal residual": np.corrcoef(x[col], x["res"])[0, 1],
                          "6+ beyond price (strat. AUC)": sp.strat_auc(x[col].to_numpy(), x["y6"].to_numpy(),
                                                                       x["p6"].to_numpy())})
    momdf = pd.DataFrame(mrows)
    corr.to_parquet(CACHE / "six_sys_corr.parquet")
    momdf.to_parquet(CACHE / "six_sys_momentum.parquet")
    S[["league_mom", "league_season_res", "sameday_prior"]].to_parquet(CACHE / "six_sys_momentum_values.parquet")
    return corr, momdf


if __name__ == "__main__":
    corr, mom = run()
    pd.set_option("display.width", 250)
    print(corr.round(3).to_string())
    print(mom.round(4).to_string())
