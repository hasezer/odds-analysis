"""Rule hunt v5 / study 1: corners from the teams' own corner statistics vs Nesine's corner lines.

Idea: corner lines may be priced from a generic model; teams' corner habits (won, conceded, crosses, shots,
possession, home/away) are strong and stable. If our team-based expectation disagrees with Nesine's line, does
the over/under hit more often than its price says, on seasons the model never saw?

Steps
  1. team history (prior matches only, all our matches): rolling means of corners won / conceded, crosses for /
     against, shots for / against, possession, home-only and away-only versions
  2. Nesine's expected corners: Poisson rate matching the fair over-chance of each priced corner line
  3. model: LightGBM Poisson regression of total corners on team history + Nesine's rate, walk-forward
     (train A -> test B, train A+B -> test C); a "Nesine only" model as the honest baseline
  4. for every priced corner line: model chance vs Nesine fair chance -> bet the side the model favours when the
     gap is large; hit rate vs break-even and return per 100, by gap band
Writes cache/v5_corners.parquet (one row per match x line, with model chances) and cache/v5_corners_bands.parquet.
"""
from pathlib import Path
import sys

import numpy as np
import pandas as pd
from lightgbm import LGBMRegressor
from scipy.stats import poisson

sys.path.insert(0, str(Path(__file__).resolve().parent))
import load  # noqa: E402
from htft_data import CACHE  # noqa: E402

PER = lambda s: np.where(np.isin(s, ["2024/25", "2024"]), "A", np.where(np.isin(s, ["2025/26", "2025"]), "B", "C"))


def team_history():
    m = load.matches()
    m = m[(m["status"] == "finished")].sort_values("kickoff_utc")
    st = load._read("stats").pivot_table(index="match_id", columns="team_side",
                                         values=["corners", "crosses", "shots", "shots_on_target", "possession_pct",
                                                 "fouls"])
    st.columns = [f"{a}_{b}" for a, b in st.columns]
    m = m.join(st, on="match_id")
    rows = []
    for side, opp in (("home", "away"), ("away", "home")):
        rows.append(pd.DataFrame({
            "match_id": m["match_id"], "team": m[f"{side}_team_id"], "kick": m["kickoff_utc"], "venue": side,
            "cor_for": m[f"corners_{side}"], "cor_ag": m[f"corners_{opp}"], "cro_for": m[f"crosses_{side}"],
            "cro_ag": m[f"crosses_{opp}"], "sh_for": m[f"shots_{side}"], "sh_ag": m[f"shots_{opp}"],
            "poss": m[f"possession_pct_{side}"], "fouls": m[f"fouls_{side}"]}))
    t = pd.concat(rows).sort_values(["team", "kick"]).reset_index(drop=True)
    vals = ["cor_for", "cor_ag", "cro_for", "cro_ag", "sh_for", "sh_ag", "poss", "fouls"]
    out = t[["match_id", "venue"]].copy()
    g = t.groupby("team")
    for c in vals:
        s = g[c].shift(1)
        for w in (6, 15):
            out[f"r{w}_{c}"] = s.groupby(t["team"]).transform(lambda v: v.rolling(w, min_periods=3).mean())
    # same-venue history (home team at home, away team away)
    gv = t.groupby(["team", "venue"])
    for c in ("cor_for", "cor_ag", "cro_for"):
        s = gv[c].shift(1)
        out[f"v8_{c}"] = s.groupby([t["team"], t["venue"]]).transform(lambda v: v.rolling(8, min_periods=3).mean())
    out["n_prev"] = g.cumcount()
    h = out[out["venue"] == "home"].drop(columns="venue").set_index("match_id").add_prefix("h_")
    a = out[out["venue"] == "away"].drop(columns="venue").set_index("match_id").add_prefix("a_")
    return h.join(a, how="inner")


def corner_lines():
    f = load.flat()
    c = f[(f["market_key"] == "CORNERS_OU") & f["closing_odds"].notna()]
    w = c.pivot_table(index=["match_id", "line"], columns="selection_key", values="closing_odds").dropna()
    w = w.reset_index()
    imp_o, imp_u = 1 / w["OVER"], 1 / w["UNDER"]
    w["fair_over"] = imp_o / (imp_o + imp_u)
    w["margin"] = imp_o + imp_u - 1
    return w


def nesine_rate(lines):
    """One Poisson corner rate per match: the one that best matches all its priced lines."""
    from scipy.optimize import minimize_scalar
    out = {}
    for mid, g in lines.groupby("match_id"):
        L, p = g["line"].to_numpy(), g["fair_over"].to_numpy()
        res = minimize_scalar(lambda lam: ((poisson.sf(np.floor(L), lam) - p) ** 2).sum(), bounds=(3, 20),
                              method="bounded")
        out[mid] = res.x
    return pd.Series(out, name="nesine_rate")


def run():
    m = load.matches()
    m = m[m["status"] == "finished"][["match_id", "league_id", "season", "kickoff_utc"]]
    ct = load._read("stats").groupby("match_id")["corners"].agg(["sum", "count"])
    m = m.join(ct[ct["count"] == 2]["sum"].rename("corners_total"), on="match_id")
    lines = corner_lines()
    rate = nesine_rate(lines)
    hist = team_history()
    d = m.set_index("match_id").join(rate, how="inner").join(hist, how="inner")
    d = d[d["corners_total"].notna()]
    d["per"] = PER(d["season"])
    d["lg"] = d["league_id"].astype("category").cat.codes
    feats = [c for c in d.columns if c.startswith(("h_", "a_"))] + ["nesine_rate", "lg"]
    d["pred_model"] = np.nan
    d["pred_base"] = np.nan
    for test, train in (("B", ["A"]), ("C", ["A", "B"])):
        tr, te = d["per"].isin(train), d["per"] == test
        for col, fs in (("pred_model", feats), ("pred_base", ["nesine_rate", "lg"])):
            reg = LGBMRegressor(objective="poisson", n_estimators=400, learning_rate=.03, num_leaves=15,
                                min_child_samples=100, subsample=.8, subsample_freq=1, colsample_bytree=.7,
                                reg_lambda=1.0, verbose=-1, random_state=0)
            reg.fit(d.loc[tr, fs], d.loc[tr, "corners_total"])
            d.loc[te, col] = reg.predict(d.loc[te, fs])
    x = lines.merge(d[["per", "league_id", "corners_total", "nesine_rate", "pred_model", "pred_base"]],
                    left_on="match_id", right_index=True)
    x = x[x["pred_model"].notna()]
    for col in ("model", "base"):
        x[f"p_over_{col}"] = poisson.sf(np.floor(x["line"]), x[f"pred_{col}"])
    x["over_hit"] = (x["corners_total"] > x["line"]).astype(float)
    x["gap"] = x["p_over_model"] - x["fair_over"]           # > 0: model likes OVER more than Nesine does
    x.to_parquet(CACHE / "v5_corners.parquet")
    rows = []
    edges = [-1, -.15, -.10, -.06, -.03, .03, .06, .10, .15, 1]
    labs = ["under, gap > 15", "under, 10-15", "under, 6-10", "under, 3-6", "no bet (|gap| < 3)", "over, 3-6",
            "over, 6-10", "over, 10-15", "over, gap > 15"]
    x["band"] = pd.cut(x["gap"], edges, labels=labs)
    for (p, b), g in x.groupby(["per", "band"], observed=True):
        side_over = b.startswith("over")
        hit = g["over_hit"] if side_over else 1 - g["over_hit"]
        odds = g["OVER"] if side_over else g["UNDER"]
        rows.append({"test": p, "band": b, "bets": len(g), "hit_pct": hit.mean() * 100,
                     "breakeven_pct": (1 / odds).mean() * 100, "return_per_100": (hit * odds - 1).mean() * 100})
    bands = pd.DataFrame(rows)
    bands.to_parquet(CACHE / "v5_corners_bands.parquet")
    err = d[d["pred_model"].notna()]
    acc = err.groupby("per").apply(lambda g: pd.Series({
        "matches": len(g), "mae_nesine": (g["corners_total"] - g["nesine_rate"]).abs().mean(),
        "mae_base": (g["corners_total"] - g["pred_base"]).abs().mean(),
        "mae_model": (g["corners_total"] - g["pred_model"]).abs().mean(),
        "corr_model_vs_nesine": np.corrcoef(g["pred_model"], g["nesine_rate"])[0, 1]}))
    return x, bands, acc


if __name__ == "__main__":
    x, bands, acc = run()
    pd.set_option("display.width", 220)
    print(acc.round(3).to_string())
    print(bands.round(1).to_string())
