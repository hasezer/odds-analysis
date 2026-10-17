"""How well teams play vs their results (team match statistics) against Nesine's prices.

Team 'process' from strictly earlier matches (last 10, at least 5):
- shots and shots on target for and against, shot-on-target share, possession, corners;
- expected goals from shots on target (the league's goals per shot on target over its earlier matches) and 'luck':
  goals minus expected goals, scored and conceded (+ = scored more / conceded more than the shots say);
- results: goals for and against, points.
Match features: home minus away differences, each side's luck, and totals (expected goals both ways).
Tests (fit on 2024/25 + 2024, checked on 2025/26 + 2025 and 2026/27 + 2026):
1. beyond the price: logistic regression of each outcome (home win, draw, away win, over 2.5, both score) on
   Nesine's chance (logit) alone vs + the process features; out-of-sample log-loss gain and AUC;
2. money: back a selection when the model's chance x Nesine's closing odds >= 1.05 / 1.10; return per 100 per
   season; luck control: the same pipeline with the process features shuffled within each season (20 runs) and the
   price-only model (Nesine's own calibration) as a second baseline;
3. disagreement: in each later season, the 5% / 10% of games where the stats model is most above the price-only
   model; hit rate vs the price-only chance on the same games, against the same pick with shuffled features;
4. readable rule: back the 'unlucky' side (results far below its shots-on-target record over the last 10).
Writes cache/perf_features.parquet, cache/perf_results.parquet and cache/perf_disagree.parquet.
"""
from pathlib import Path
import sys

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression

sys.path.insert(0, str(Path(__file__).resolve().parent))
import bb_data  # noqa: E402
import load  # noqa: E402
from six_plus import auc  # noqa: E402

CACHE = bb_data.CACHE
SEAS = {"A": "2024/25", "B": "2025/26", "C": "2026/27"}
ROLL = ["sot_f", "sot_a", "shots_f", "shots_a", "poss", "corners_f", "corners_a", "gf", "ga", "xg_f", "xg_a",
        "luck_f", "luck_a", "points"]
FEATS = ["d_sot_share", "d_xg_diff", "d_goal_diff", "d_luck_net", "d_points", "d_poss", "d_shots_share",
         "home_luck_f", "home_luck_a", "away_luck_f", "away_luck_a", "xg_total", "goals_total", "corners_total"]
TARGETS = {"home win": ("y_1", "f_1X2__1", "odds_1X2||1"), "draw": ("y_X", "f_1X2__X", "odds_1X2||X"),
           "away win": ("y_2", "f_1X2__2", "odds_1X2||2"), "over 2.5": ("y_o25", "f_OU_2.5_OVER", "odds_OU|2.5|OVER"),
           "under 2.5": ("y_u25", "f_OU_2.5_UNDER", "odds_OU|2.5|UNDER"),
           "both score": ("y_btts", "f_BTTS__YES", "odds_BTTS||YES"),
           "not both score": ("y_nbtts", "f_BTTS__NO", "odds_BTTS||NO")}


def team_rows():
    m = load.matches()
    m = m[(m["status"] == "finished") & m["ft_home"].notna()].copy()
    m = m[~m["match_id"].astype(str).str.startswith("macko")]
    st = load._read("stats")
    w = st.pivot_table(index="match_id", columns="team_side",
                       values=["shots", "shots_on_target", "possession_pct", "corners"], aggfunc="first")
    w.columns = [f"{a}_{b}" for a, b in w.columns]
    m = m.join(w, on="match_id").sort_values("kickoff_utc").reset_index(drop=True)
    # league goals per shot on target over its earlier matches (no look-ahead)
    g = m["ft_home"] + m["ft_away"]
    s = m["shots_on_target_home"] + m["shots_on_target_away"]
    lg = m["league_id"]
    cg = g.groupby(lg).transform(lambda v: v.shift(1).expanding(min_periods=50).sum())
    cs = s.groupby(lg).transform(lambda v: v.shift(1).expanding(min_periods=50).sum())
    m["conv"] = (cg / cs).fillna(0.31)
    rows = []
    for side, opp in (("home", "away"), ("away", "home")):
        gf, ga = m[f"ft_{side}"], m[f"ft_{opp}"]
        r = pd.DataFrame({"match_id": m["match_id"], "team": m[f"{side}_team_id"], "kick": m["kickoff_utc"],
                          "side": side, "sot_f": m[f"shots_on_target_{side}"], "sot_a": m[f"shots_on_target_{opp}"],
                          "shots_f": m[f"shots_{side}"], "shots_a": m[f"shots_{opp}"],
                          "poss": m[f"possession_pct_{side}"], "corners_f": m[f"corners_{side}"],
                          "corners_a": m[f"corners_{opp}"], "gf": gf, "ga": ga,
                          "points": np.where(gf > ga, 3, np.where(gf == ga, 1, 0))})
        r["xg_f"], r["xg_a"] = m["conv"] * r["sot_f"], m["conv"] * r["sot_a"]
        r["luck_f"], r["luck_a"] = r["gf"] - r["xg_f"], r["ga"] - r["xg_a"]
        rows.append(r)
    t = pd.concat(rows).sort_values(["team", "kick"]).reset_index(drop=True)
    roll = t.groupby("team")[ROLL].transform(lambda v: v.shift(1).rolling(10, min_periods=5).mean())
    t[[f"r_{c}" for c in ROLL]] = roll.to_numpy()
    feat = [f"r_{c}" for c in ROLL]
    h = t[t["side"] == "home"].set_index("match_id")[feat].add_prefix("home_")
    a = t[t["side"] == "away"].set_index("match_id")[feat].add_prefix("away_")
    return h.join(a)


def features():
    tm = team_rows()
    d = bb_data.build()
    cols = ["match_id", "per", "league", "ft_home", "ft_away"] + sorted({c for v in TARGETS.values() for c in v[1:]})
    d = d[[c for c in cols if c in d.columns]].join(tm, on="match_id")
    H = lambda c: d[f"home_r_{c}"]  # noqa: E731
    A = lambda c: d[f"away_r_{c}"]  # noqa: E731
    share = lambda f, a: f / (f + a).replace(0, np.nan)  # noqa: E731
    d["d_sot_share"] = share(H("sot_f"), H("sot_a")) - share(A("sot_f"), A("sot_a"))
    d["d_shots_share"] = share(H("shots_f"), H("shots_a")) - share(A("shots_f"), A("shots_a"))
    d["d_xg_diff"] = (H("xg_f") - H("xg_a")) - (A("xg_f") - A("xg_a"))
    d["d_goal_diff"] = (H("gf") - H("ga")) - (A("gf") - A("ga"))
    d["d_luck_net"] = (H("luck_f") - H("luck_a")) - (A("luck_f") - A("luck_a"))
    d["d_points"] = H("points") - A("points")
    d["d_poss"] = H("poss") - A("poss")
    for side, f in (("home", H), ("away", A)):
        d[f"{side}_luck_f"], d[f"{side}_luck_a"] = f("luck_f"), f("luck_a")
    d["xg_total"] = H("xg_f") + H("xg_a") + A("xg_f") + A("xg_a")
    d["goals_total"] = H("gf") + H("ga") + A("gf") + A("ga")
    d["corners_total"] = H("corners_f") + H("corners_a") + A("corners_f") + A("corners_a")
    hg, ag = d["ft_home"], d["ft_away"]
    d["y_1"], d["y_X"], d["y_2"] = (hg > ag).astype(int), (hg == ag).astype(int), (hg < ag).astype(int)
    d["y_o25"] = ((hg + ag) > 2.5).astype(int)
    d["y_u25"] = 1 - d["y_o25"]
    d["y_btts"] = ((hg > 0) & (ag > 0)).astype(int)
    d["y_nbtts"] = 1 - d["y_btts"]
    d.to_parquet(CACHE / "perf_features.parquet")
    return d


def logit(p):
    p = np.clip(p, 1e-4, 1 - 1e-4)
    return np.log(p / (1 - p))


def fit_predict(d, ycol, pcol, feats, shuffle=None):
    """Logistic model on 2024/25: logit(Nesine chance) [+ standardised features]; predictions for every game."""
    per = d["per"].to_numpy()
    y = d[ycol].to_numpy(float)
    X = [logit(d[pcol].to_numpy(float))]
    if feats:
        F = d[feats].to_numpy(float).copy()
        if shuffle is not None:
            for k in "ABC":
                m = np.where(per == k)[0]
                F[m] = F[shuffle.permutation(m)]
        X += [F[:, j] for j in range(F.shape[1])]
    X = np.column_stack(X)
    ok = ~np.isnan(X).any(axis=1) & ~np.isnan(y)
    tr = ok & (per == "A")
    mu, sd = X[tr].mean(0), X[tr].std(0) + 1e-9
    lr = LogisticRegression(C=1.0, max_iter=2000).fit((X[tr] - mu) / sd, y[tr])
    p = np.full(len(d), np.nan)
    p[ok] = lr.predict_proba((X[ok] - mu) / sd)[:, 1]
    return p, ok


def logloss(y, p):
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return -np.mean(y * np.log(p) + (1 - y) * np.log(1 - p))


def money(d, p, ycol, ocol, ok, edge):
    per = d["per"].to_numpy()
    y, o = d[ycol].to_numpy(float), d[ocol].to_numpy(float)
    bet = ok & ~np.isnan(o) & (p * o >= 1 + edge)
    out = {}
    for k, nm in SEAS.items():
        m = bet & (per == k)
        out[nm] = (int(m.sum()), ((y[m] * o[m]).sum() / m.sum() - 1) * 100 if m.sum() else np.nan)
    return out


def run(n_luck=20):
    d = features()
    per = d["per"].to_numpy()
    rows = []
    rng = np.random.default_rng(5)
    for name, (yc, pc, oc) in TARGETS.items():
        y = d[yc].to_numpy(float)
        p0, ok0 = fit_predict(d, yc, pc, [])
        p1, ok1 = fit_predict(d, yc, pc, FEATS)
        ok = ok0 & ok1
        r = {"target": name}
        for k, nm in SEAS.items():
            m = ok & (per == k)
            r[f"log-loss gain x1000 {nm}"] = (logloss(y[m], p0[m]) - logloss(y[m], p1[m])) * 1000
            r[f"AUC price {nm}"], r[f"AUC price+process {nm}"] = auc(p0[m], y[m]), auc(p1[m], y[m])
            r[f"normal % {nm}"] = y[per == k].mean() * 100
        for edge in (0.05, 0.10):
            for tag, p in (("price+process", p1), ("price only", p0)):
                res = money(d, p, yc, oc, ok, edge)
                for nm, (n, ret) in res.items():
                    r[f"{tag} edge {int(edge * 100)}% bets {nm}"] = n
                    r[f"{tag} edge {int(edge * 100)}% return {nm}"] = ret
            luck = []
            for _ in range(n_luck):
                ps, oks = fit_predict(d, yc, pc, FEATS, shuffle=rng)
                res = money(d, ps, yc, oc, oks & ok, edge)
                luck.append([res[nm][1] for nm in ("2025/26", "2026/27")])
            luck = np.array(luck, float)
            r[f"luck edge {int(edge * 100)}% return 2025/26 (mean)"] = np.nanmean(luck[:, 0])
            r[f"luck edge {int(edge * 100)}% return 2026/27 (mean)"] = np.nanmean(luck[:, 1])
            r[f"luck edge {int(edge * 100)}% return 2025/26 (best)"] = np.nanmax(luck[:, 0])
            r[f"luck edge {int(edge * 100)}% return 2026/27 (best)"] = np.nanmax(luck[:, 1])
        rows.append(r)
        print(name, "done", flush=True)
    R = pd.DataFrame(rows)
    R.to_parquet(CACHE / "perf_results.parquet")
    return d, R


def disagree(d, n_luck=20):
    """Games where the stats model rates a selection most above the price-only model: does it hit more than the
    price-only chance on those games? Real features vs shuffled features (same pipeline, same number of games)."""
    per = d["per"].to_numpy()
    rng = np.random.default_rng(11)
    out = []
    for name, (yc, pc, oc) in TARGETS.items():
        y, o = d[yc].to_numpy(float), d[oc].to_numpy(float)
        p0, ok0 = fit_predict(d, yc, pc, [])
        runs = [("real", *fit_predict(d, yc, pc, FEATS))]
        runs += [(f"luck {i}", *fit_predict(d, yc, pc, FEATS, shuffle=rng)) for i in range(n_luck)]
        for tag, p1, ok1 in runs:
            ok = ok0 & ok1 & ~np.isnan(o)
            ratio = np.where(ok, p1 / p0, np.nan)
            for share in (0.10, 0.05):
                for k in "BC":
                    idx = np.where(ok & (per == k))[0]
                    top = idx[np.argsort(-ratio[idx], kind="stable")[:int(round(share * len(idx)))]]
                    out.append({"target": name, "run": tag, "share": share, "season": SEAS[k], "games": len(top),
                                "hit %": y[top].mean() * 100, "price-only chance %": p0[top].mean() * 100,
                                "return per 100": ((y[top] * o[top]).sum() / len(top) - 1) * 100})
        print(name, "disagreement done", flush=True)
    D = pd.DataFrame(out)
    D["lift"] = D["hit %"] - D["price-only chance %"]
    D.to_parquet(CACHE / "perf_disagree.parquet")
    real = D[D["run"] == "real"].set_index(["target", "share", "season"])
    luck = D[D["run"] != "real"].groupby(["target", "share", "season"])["lift"]
    real["luck lift (mean)"], real["luck lift (95th pct)"] = luck.mean(), luck.quantile(0.95)
    return real.drop(columns="run").reset_index()


def unlucky(d):
    """Readable rule: back the side whose results lag its shots (net luck, last 10) the most; per season."""
    per = d["per"].to_numpy()
    A = per == "A"
    out = []
    for side, ycol, ocol, sign in (("home", "y_1", "odds_1X2||1", -1), ("away", "y_2", "odds_1X2||2", 1)):
        x = d["d_luck_net"].to_numpy(float) * sign          # high = this side has been unluckier than its opponent
        for share in (0.10, 0.05):
            thr = np.nanquantile(x[A], 1 - share)
            for k, nm in SEAS.items():
                m = (per == k) & (x >= thr) & d[ocol].notna().to_numpy()
                y, o = d.loc[m, ycol].to_numpy(float), d.loc[m, ocol].to_numpy(float)
                out.append({"back": f"{side} side when it was the unluckier one", "share": share, "season": nm,
                            "bets": int(m.sum()), "hit %": y.mean() * 100, "implied %": (1 / o).mean() * 100,
                            "fair %": d.loc[m, ycol.replace("y_", "f_1X2__")].mean() * 100,
                            "return per 100": ((y * o).sum() / len(y) - 1) * 100})
    return pd.DataFrame(out)


if __name__ == "__main__":
    d, R = run()
    pd.set_option("display.width", 300)
    pd.set_option("display.max_columns", 80)
    print(R.round(2).T.to_string())
    print(disagree(d).round(2).to_string(index=False))
    print(unlucky(d).round(2).to_string(index=False))
