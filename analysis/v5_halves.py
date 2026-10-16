"""Rule hunt v5 / study 2: do teams' own first-half / second-half habits beat Nesine's half split?

Nesine's core prices imply expected goals per half (goal-rate model of ml_data: lam_h1, lam_a1, lam_h2, lam_a2).
Bookmakers often split goals between halves with one league-wide ratio. If some teams are persistently "slow
starters" or "late scorers", half-time markets should be mispriced for them.

  1. persistence: is a team's share of 1st-half goals (its matches, for + against) in one season correlated with the
     next season's, beyond what Nesine's split already says?
  2. signal: team half profile (prior matches only, last 15 and season-long) minus Nesine's implied 1st-half share
  3. strategy check, walk-forward (bands cut on A): 1st-half goals over/under 0.5 and 1.5, HT draw, 2nd-half
     result... hit rate vs break-even and return per 100, by signal band, in B and C
Writes cache/v5_halves.parquet.
"""
from pathlib import Path
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import load  # noqa: E402
import ml_data as md  # noqa: E402
from htft_data import CACHE  # noqa: E402

PER = lambda s: np.where(np.isin(s, ["2024/25", "2024"]), "A", np.where(np.isin(s, ["2025/26", "2025"]), "B", "C"))


def profiles(mt):
    """Rolling (prior matches only) share of a team's match goals scored in the 1st half, and the market's."""
    rows = []
    for side in ("home", "away"):
        rows.append(pd.DataFrame({"match_id": mt["match_id"], "team": mt[f"{side}_team_id"], "kick": mt["kickoff_utc"],
                                  "venue": side, "g1": mt["ht_home"] + mt["ht_away"],
                                  "g": mt["ft_home"] + mt["ft_away"],
                                  "x1": mt["lam_h1"] + mt["lam_a1"], "x": mt["lam_h1"] + mt["lam_a1"] + mt["lam_h2"]
                                  + mt["lam_a2"]}))
    t = pd.concat(rows).sort_values(["team", "kick"]).reset_index(drop=True)
    g = t.groupby("team")
    out = t[["match_id", "venue"]].copy()
    for w in (10, 30):
        for c in ("g1", "g", "x1", "x"):
            out[f"{c}_{w}"] = g[c].shift(1).groupby(t["team"]).transform(lambda v: v.rolling(w, min_periods=5).sum())
        # actual 1st-half share minus the market's 1st-half share, over the team's last w matches
        out[f"surplus1_{w}"] = out[f"g1_{w}"] / out[f"g_{w}"].replace(0, np.nan) - out[f"x1_{w}"] / out[f"x_{w}"]
        out[f"ht_goals_vs_exp_{w}"] = (out[f"g1_{w}"] - out[f"x1_{w}"]) / w
    h = out[out["venue"] == "home"].drop(columns="venue").set_index("match_id").add_prefix("h_")
    a = out[out["venue"] == "away"].drop(columns="venue").set_index("match_id").add_prefix("a_")
    return h.join(a, how="inner")


def run():
    mt, sel = md.build()
    mt = mt[mt["ht_home"].notna()].copy()
    p = profiles(mt)
    d = mt.set_index("match_id").join(p, how="inner")
    d["per"] = PER(d["season"])
    d["sig"] = d["h_ht_goals_vs_exp_30"] + d["a_ht_goals_vs_exp_30"]       # both teams' 1st-half goal surplus
    d["sig10"] = d["h_ht_goals_vs_exp_10"] + d["a_ht_goals_vs_exp_10"]
    d["ht_goals"] = d["ht_home"] + d["ht_away"]
    d["ht_exp"] = d["lam_h1"] + d["lam_a1"]
    # 1) persistence: does the signal predict this match's 1st-half goals beyond Nesine's expectation?
    pers = d.groupby("per").apply(lambda g: pd.Series({
        "matches": int(g["sig"].notna().sum()),
        "corr(signal, HT goals - expected)": g[["sig"]].assign(r=g["ht_goals"] - g["ht_exp"]).dropna().corr().iloc[0, 1],
        "corr(signal10, HT goals - expected)": g[["sig10"]].assign(r=g["ht_goals"] - g["ht_exp"]).dropna().corr().iloc[
            0, 1]}))
    # 2) strategy bands on priced half-time markets
    s = sel[sel["market_key"].isin(["HT_OU", "HT_1X2", "HT_BTTS"])].copy()
    s["lab"] = s["market_key"] + "|" + s["line"].map(lambda v: "" if pd.isna(v) else f"{v:g}") + "|" + s["selection_key"]
    x = s.merge(d[["per", "sig"]], left_on="match_id", right_index=True)
    x = x[x["sig"].notna()]
    cuts = np.nanquantile(d.loc[d["per"] == "A", "sig"], [.1, .3, .7, .9])
    x["band"] = pd.cut(x["sig"], [-np.inf, *cuts, np.inf], labels=["lowest 10%", "10-30%", "middle", "70-90%",
                                                                   "highest 10%"])
    x["ret"] = x["hit"] * x["closing_odds"] - 1
    bands = x.groupby(["lab", "band", "per"], observed=True).agg(
        bets=("ret", "size"), hit_pct=("hit", "mean"), breakeven=("closing_odds", lambda o: (1 / o).mean()),
        ret=("ret", "mean")).reset_index()
    bands["hit_pct"] *= 100
    bands["breakeven"] *= 100
    bands["ret"] *= 100
    bands.to_parquet(CACHE / "v5_halves.parquet")
    return pers, bands


if __name__ == "__main__":
    pers, bands = run()
    pd.set_option("display.width", 220)
    print(pers.round(3).to_string())
    w = bands.pivot_table(index=["lab", "band"], columns="per", values=["hit_pct", "ret"], observed=True)
    print(w.round(1).to_string())
