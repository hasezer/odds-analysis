"""Corners, second pass: which technique picks corner over/unders best, on the same number of games?

The first pass (v5_corners.py, RULES_V5_REPORT.md) showed that a team-statistics model predicts total corners
exactly as well as Nesine's line and that every corner band loses (~20% cut). This pass asks the owner's question:
which corner bets are most likely to land, and can anything beat Nesine's own corner chance at picking them?
1. calibration: per line x side x chance band (bands cut on 2024/25), hit rate vs Nesine's fair chance vs the
   break-even rate, and the return per 100, season by season;
2. fair race: inside each later season (2025/26 + 2025, 2026/27 + 2026) every technique takes its 10% / 5% most
   likely games, so all take the same number:
   - Nesine's own corner chance (cut removed);
   - team corner habits (last 15 matches, and the same venue over the last 8; v5_corners.team_history);
   - goal expectation (four goal rates fitted to the goal and result markets, bb_data) and favourite strength;
   - a logistic model fitted on 2024/25: Nesine's chance + habits + goal expectation + favourite strength
     + league corner average; luck control: the same model with the extra signs shuffled within each season;
3. money: return per 100 of each technique's picks at Nesine's closing corner odds.
Writes cache/corners_calibration.parquet and cache/corners_race.parquet.

    python analysis/corners_study.py
"""
from pathlib import Path
import sys

import numpy as np
import pandas as pd
from scipy.stats import poisson
from sklearn.linear_model import LogisticRegression

sys.path.insert(0, str(Path(__file__).resolve().parent))
import bb_data  # noqa: E402
import load  # noqa: E402
import v5_corners as v5  # noqa: E402
from htft3_data import PER  # noqa: E402
from htft3_report import top_hits  # noqa: E402

CACHE = bb_data.CACHE
SEAS = {"A": "2024/25", "B": "2025/26", "C": "2026/27"}
EXTRA = ["hab_rate", "hab_venue", "xg_tot", "fav", "league_avg"]


def table():
    """One row per match x priced corner line: odds, fair chance, result and the signs."""
    f = load.flat()
    c = f[(f["market_key"] == "CORNERS_OU") & f["closing_odds"].notna() & f["in_default_analysis"]]
    w = c.pivot_table(index=["match_id", "line"], columns="selection_key", values="closing_odds").dropna()
    hit = c[c["selection_key"] == "OVER"].groupby(["match_id", "line"])["hit"].first().rename("y_over")
    w = w.join(hit).reset_index()
    w = w[w["y_over"].notna()]
    io, iu = 1 / w["OVER"], 1 / w["UNDER"]
    w["fair_over"], w["margin"] = io / (io + iu), io + iu - 1
    meta = f.drop_duplicates("match_id").set_index("match_id")[["season", "league_id", "kickoff_utc",
                                                               "corners_total"]]
    w = w.join(meta, on="match_id")
    w["per"] = w["season"].map(PER)
    w = w[w["per"].notna()].reset_index(drop=True)
    w = w.join(v5.nesine_rate(w), on="match_id")                 # Nesine's expected corners (all its lines)
    h = v5.team_history()
    w = w.join((((h["h_r15_cor_for"] + h["a_r15_cor_ag"]) + (h["a_r15_cor_for"] + h["h_r15_cor_ag"])) / 2)
               .rename("hab_rate"), on="match_id")
    w = w.join((((h["h_v8_cor_for"] + h["a_v8_cor_ag"]) + (h["a_v8_cor_for"] + h["h_v8_cor_ag"])) / 2)
               .rename("hab_venue"), on="match_id")
    b = bb_data.build()[["match_id", "lam_h1", "lam_a1", "lam_h2", "lam_a2", "fit_rmse", "f_1X2__1", "f_1X2__2"]]
    b = b[b["fit_rmse"] < 0.05]                                   # 2 failed goal-rate fits (rmse ~0.2) dropped
    b = b.assign(xg_tot=b[["lam_h1", "lam_a1", "lam_h2", "lam_a2"]].sum(axis=1),
                 fav=(b["f_1X2__1"] - b["f_1X2__2"]).abs())
    w = w.merge(b[["match_id", "xg_tot", "fav"]], on="match_id", how="left")
    # league corner average over its earlier matches (one value per match, no look-ahead)
    m = w.drop_duplicates("match_id").sort_values("kickoff_utc")
    m["league_avg"] = m.groupby("league_id")["corners_total"].transform(
        lambda v: v.shift(1).expanding(min_periods=50).mean())
    return w.merge(m[["match_id", "league_avg"]], on="match_id", how="left")


def calibration(w):
    rows = []
    for line, g in w.groupby("line"):
        for side in ("OVER", "UNDER"):
            fair = g["fair_over"] if side == "OVER" else 1 - g["fair_over"]
            y = g["y_over"] if side == "OVER" else 1 - g["y_over"]
            a = fair[g["per"] == "A"]
            if len(a) < 1000:
                continue
            q = np.unique(np.r_[0, np.quantile(a, [0.2, 0.4, 0.6, 0.8]), 1])
            band = pd.cut(fair, q, include_lowest=True).astype(str)
            x = pd.DataFrame({"per": g["per"], "band": band, "y": y, "fair": fair, "odds": g[side]})
            for (p, bd), gg in x.groupby(["per", "band"]):
                rows.append({"line": line, "side": side, "chance band": bd, "season": SEAS[p], "bets": len(gg),
                             "hit %": gg["y"].mean() * 100, "fair %": gg["fair"].mean() * 100,
                             "break-even %": (1 / gg["odds"]).mean() * 100,
                             "return per 100": ((gg["y"] * gg["odds"]).mean() - 1) * 100})
    out = pd.DataFrame(rows)
    out.to_parquet(CACHE / "corners_calibration.parquet")
    return out


def logit(p):
    p = np.clip(p, 1e-4, 1 - 1e-4)
    return np.log(p / (1 - p))


def model(g, y, shuffle=None):
    """Logistic on 2024/25: logit(Nesine's chance) + the extra signs (standardised); predictions for every row."""
    per = g["per"].to_numpy()
    F = g[EXTRA].to_numpy(float).copy()
    if shuffle is not None:
        for k in "ABC":
            idx = np.where(per == k)[0]
            F[idx] = F[shuffle.permutation(idx)]
    X = np.column_stack([logit(g["fair"].to_numpy(float)), F])
    ok = ~np.isnan(X).any(axis=1)
    tr = ok & (per == "A")
    mu, sd = X[tr].mean(0), X[tr].std(0) + 1e-9
    lr = LogisticRegression(C=1.0, max_iter=2000).fit((X[tr] - mu) / sd, y[tr])
    p = np.full(len(g), np.nan)
    p[ok] = lr.predict_proba((X[ok] - mu) / sd)[:, 1]
    return p


def race(w, n_luck=20):
    rng = np.random.default_rng(7)
    rows = []
    for line, g0 in w.groupby("line"):
        for side in ("OVER", "UNDER"):
            g = g0.assign(fair=g0["fair_over"] if side == "OVER" else 1 - g0["fair_over"]).reset_index(drop=True)
            y = (g["y_over"] if side == "OVER" else 1 - g["y_over"]).to_numpy(float)
            if (g["per"] == "A").sum() < 1000:
                continue
            sg = 1.0 if side == "OVER" else -1.0
            lam = lambda c: poisson.sf(np.floor(line), g[c].to_numpy(float))  # noqa: E731
            techs = {"Nesine's own chance": g["fair"].to_numpy(float),
                     "team corner habits (last 15)": lam("hab_rate") if side == "OVER" else 1 - lam("hab_rate"),
                     "same-venue habits (last 8)": lam("hab_venue") if side == "OVER" else 1 - lam("hab_venue"),
                     "goal expectation": sg * g["xg_tot"].to_numpy(float),
                     "favourite strength": sg * g["fav"].to_numpy(float),
                     "price + all signs (model)": model(g, y)}
            luck = [model(g, y, shuffle=rng) for _ in range(n_luck)]
            odds = g[side].to_numpy(float)
            per = g["per"].to_numpy()
            ok = ~np.isnan(np.column_stack(list(techs.values()))).any(axis=1)     # same games for all
            for k in "BC":
                m = ok & (per == k)
                if m.sum() < 300:
                    continue
                for share in (0.10, 0.05):
                    n = int(round(share * m.sum()))
                    r = {"line": line, "side": side, "season": SEAS[k], "share": share, "games": n,
                         "normal %": y[m].mean() * 100}
                    for t, s in techs.items():
                        sel = np.where(m)[0][np.argsort(-s[m], kind="stable")[:n]]
                        r[f"{t} hit %"] = top_hits(s[m], y[m], n)[0] / n * 100
                        r[f"{t} return"] = ((y[sel] * odds[sel]).mean() - 1) * 100
                    lk = np.array([top_hits(s[m], y[m], n)[0] / n * 100 for s in luck])
                    r["shuffled signs hit % (mean)"], r["shuffled signs hit % (95th)"] = lk.mean(), np.percentile(lk, 95)
                    rows.append(r)
            print(line, side, "done", flush=True)
    R = pd.DataFrame(rows)
    R.to_parquet(CACHE / "corners_race.parquet")
    return R


def pooled(R):
    """Hits pooled over 2025/26 + 2026/27 (top 10% of each), per line and side."""
    hit_cols = [c for c in R.columns if c.endswith("hit %") and not c.startswith("shuffled")]
    x = R[R["share"] == 0.10].copy()
    for c in hit_cols + ["normal %", "shuffled signs hit % (95th)"]:
        x[c] = x[c] * x["games"]
    g = x.groupby(["line", "side"])
    out = g[hit_cols + ["normal %", "shuffled signs hit % (95th)"]].sum().div(g["games"].sum(), axis=0)
    out.insert(0, "games", g["games"].sum())
    return out


if __name__ == "__main__":
    w = table()
    pd.set_option("display.width", 300)
    pd.set_option("display.max_columns", 40)
    print("cut by line:", w.groupby("line")["margin"].median().round(3).to_dict())
    print("correlations (one row per match):")
    print(w.drop_duplicates("match_id")[["corners_total", "nesine_rate", "hab_rate", "hab_venue", "xg_tot", "fav",
                                         "league_avg"]]
          .corr().round(2).to_string())
    cal = calibration(w)
    print(cal.pivot_table(index=["line", "side", "chance band"], columns="season",
                          values=["hit %", "fair %", "return per 100"]).round(1).to_string())
    R = race(w)
    print(pooled(R).round(1).to_string())
    print(R.round(1).to_string(index=False))
