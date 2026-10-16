"""6+ goals deep dive, studies 2-5 (uses six_plus.data()).

2 tail calibration: actual 6+ rate vs Nesine's 6+ chance (p6), by expected total goals x how one-sided the match is
  (favourite's odds). Where is 6+ under- / over-priced, consistently in all three seasons? + return of the 6+ bet.
3 kinds of 6+ games: shootout (both teams 2+), one-sided (loser <= 1), and the score lines; what the odds looked like.
4 which bet to play: among the matches where 6+ is most likely (top 5/10/20% by p6), the return of 6+, over 4.5,
  'other' correct score, both halves over 1.5, home/away 3+ goals, 1st-half over 1.5.
5 teams: does a team keep producing more 6+ games than its odds say, season after season? (vs shuffled teams)
Writes cache/six_plus_*.parquet.
"""
from pathlib import Path
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import load  # noqa: E402
import six_plus as sp  # noqa: E402
from htft_data import CACHE  # noqa: E402

SEAS = sp.SEAS


def calib(D, X):
    lam = X[["model: lam_h1", "model: lam_a1", "model: lam_h2", "model: lam_a2"]].sum(1)
    fav = np.exp(np.minimum(X["odds: Result home"], X["odds: Result away"]))
    d = D.assign(lam=lam, fav=fav)
    d["goals_band"] = pd.cut(d["lam"], [0, 2.4, 2.8, 3.2, 3.6, 10], labels=["< 2.4", "2.4–2.8", "2.8–3.2", "3.2–3.6",
                                                                          "3.6+"])
    d["fav_band"] = pd.cut(d["fav"], [1, 1.3, 1.6, 2.0, 2.6, 50], labels=["fav ≤ 1.30", "1.30–1.60", "1.60–2.00",
                                                                        "2.00–2.60", "> 2.60 (even)"])
    d["ret"] = d["y"] * d["odds6"] - 1
    rows = []
    for (gb, fb), g in d.groupby(["goals_band", "fav_band"], observed=True):
        row = {"expected goals": gb, "favourite": fb}
        for p, nm in SEAS.items():
            x = g[g["per"] == p]
            row.update({f"n {nm}": len(x), f"actual % {nm}": x["y"].mean() * 100,
                        f"Nesine says % {nm}": x["p6"].mean() * 100,
                        f"return {nm}": x["ret"].mean() * 100 if x["odds6"].notna().any() else np.nan})
        row.update({"n all": len(g), "actual % all": g["y"].mean() * 100, "Nesine says % all": g["p6"].mean() * 100,
                    "return all": g["ret"].mean() * 100})
        rows.append(row)
    return pd.DataFrame(rows)


def kinds(D, X):
    s = D[D["y"] == 1].copy()
    lo, hi = np.minimum(s["fh"], s["fa"]), np.maximum(s["fh"], s["fa"])
    s["kind"] = np.where(lo >= 2, "shootout (both teams 2+)", np.where(hi >= 5, "rout (one team 5+, other 0-1)",
                                                                        "one-sided (other team 0-1)"))
    s["score"] = s["fh"].astype(int).astype(str) + "-" + s["fa"].astype(int).astype(str)
    s["fav_won"] = np.where(np.exp(X.loc[s.index, "odds: Result home"]) <= np.exp(X.loc[s.index, "odds: Result away"]),
                            s["fh"] > s["fa"], s["fa"] > s["fh"])
    s["ht_goals"] = s["hh"] + s["ha"]
    s["fav"] = np.exp(np.minimum(X.loc[s.index, "odds: Result home"], X.loc[s.index, "odds: Result away"]))
    s["odds6"] = s["odds6"]
    k = s.groupby("kind").agg(games=("y", "size"), median_fav_odds=("fav", "median"), median_6plus_odds=("odds6", "median"),
                              fav_won_pct=("fav_won", "mean"), median_ht_goals=("ht_goals", "median"))
    k["fav_won_pct"] *= 100
    sc = s["score"].value_counts().rename("games").to_frame()
    ht = s["ht_goals"].value_counts().sort_index().rename("games").to_frame()
    return k, sc, ht


def instruments(D, X, d):
    names = list(d["names"])
    O = pd.DataFrame(d["O"], index=d["ids"], columns=names).loc[D.index]
    goals = D["fh"] + D["fa"]
    h1 = D["hh"] + D["ha"]
    h2 = goals - h1
    bets = {"6+ goals": ("GOAL_RANGE||6+", goals >= 6), "over 4.5 (5+ goals)": ("OU|4.5|OVER", goals >= 5),
            "correct score 'other'": ("CORRECT_SCORE||OTHER", None),
            "both halves over 1.5": ("BOTH_HALVES_OVER|1.5|YES", (h1 >= 2) & (h2 >= 2)),
            "home team 3+": ("TEAM_OU_HOME|2.5|OVER", D["fh"] >= 3), "away team 3+": ("TEAM_OU_AWAY|2.5|OVER", D["fa"] >= 3),
            "1st-half over 1.5": ("HT_OU|1.5|OVER", h1 >= 2), "over 3.5": ("OU|3.5|OVER", goals >= 4)}
    cs = [n for n in names if n.startswith("CORRECT_SCORE|") and not n.endswith("OTHER")]
    listed = {tuple(map(int, n.split("|")[-1].split("-"))) for n in cs}
    other = pd.Series([(int(a), int(b)) not in listed for a, b in zip(D["fh"], D["fa"])], index=D.index)
    rows = []
    for share in (.05, .10, .20, 1.0):
        for p, nm in list(SEAS.items()) + [("all", "all")]:
            x = D if p == "all" else D[D["per"] == p]
            thr = x["p6"].quantile(1 - share)
            top = x.index[x["p6"] >= thr]
            for bn, (key, hit) in bets.items():
                h = other if hit is None else hit
                o = O.loc[top, key] if key in O else pd.Series(np.nan, index=top)
                ok = o.notna()
                if ok.sum() < 20:
                    continue
                rows.append({"matches played": "every match" if share == 1 else f"top {int(share * 100)}% by 6+ chance",
                             "season": nm, "bet": bn, "bets": int(ok.sum()), "hit %": h[top][ok].mean() * 100,
                             "avg odds": o[ok].mean(), "break-even %": (1 / o[ok]).mean() * 100,
                             "return per 100": (h[top][ok] * o[ok] - 1).mean() * 100})
    return pd.DataFrame(rows)


def teams(D):
    m = load.matches().set_index("match_id").loc[D.index]
    rows = []
    for side in ("home_team_id", "away_team_id"):
        rows.append(pd.DataFrame({"team": m[side], "per": D["per"], "y": D["y"], "p": D["p6"]}))
    t = pd.concat(rows)

    def zs(tt):
        g = tt.groupby(["team", "per"]).agg(n=("y", "size"), h=("y", "sum"), e=("p", "sum"),
                                            v=("p", lambda p: (p * (1 - p)).sum())).unstack("per")
        return g, (g["h"] - g["e"]) / np.sqrt(g["v"])
    g, z = zs(t)
    ok = (g["n"]["A"] >= 20) & (g["n"]["B"] >= 20)
    corr = np.corrcoef(z["A"][ok], z["B"][ok])[0, 1]
    both = int(((z["A"] >= 1.5) & (z["B"] >= 1.5) & ok).sum())
    rng = np.random.default_rng(9)
    luck = []
    for _ in range(50):
        ts = t.copy()
        for p in "ABC":
            ix = (ts["per"] == p).to_numpy()
            ts.loc[ix, "team"] = rng.permutation(ts.loc[ix, "team"].to_numpy())
        gs, zz = zs(ts)
        oks = (gs["n"]["A"] >= 20) & (gs["n"]["B"] >= 20)
        luck.append(int(((zz["A"] >= 1.5) & (zz["B"] >= 1.5) & oks).sum()))
    tn = pd.read_parquet(Path(__file__).resolve().parents[1] / "data" / "teams" / "part-0000.parquet").set_index(
        "team_id")["name_tr"]
    sel = z.index[(z["A"] >= 1.5) & (z["B"] >= 1.5) & ok]
    det = pd.DataFrame({"team": tn.reindex(sel).fillna(pd.Series(sel, index=sel)).to_numpy()}, index=sel)
    for p, nm in SEAS.items():
        det[f"6+ games {nm}"] = g["h"][p].reindex(sel).to_numpy()
        det[f"odds expected {nm}"] = g["e"][p].reindex(sel).round(1).to_numpy()
        det[f"matches {nm}"] = g["n"][p].reindex(sel).to_numpy()
    return corr, both, luck, det


if __name__ == "__main__":
    D, X, d = sp.data()
    pd.set_option("display.width", 260)
    c = calib(D, X)
    c.to_parquet(CACHE / "six_plus_calib.parquet")
    cols = ["expected goals", "favourite", "n all", "actual % all", "Nesine says % all", "return all"] + \
        [f"actual % {s}" for s in SEAS.values()] + [f"Nesine says % {s}" for s in SEAS.values()] + \
        [f"return {s}" for s in SEAS.values()]
    print(c[cols].round(1).to_string())
    k, sc, ht = kinds(D, X)
    print(k.round(2).to_string()); print(sc.head(15).T.to_string()); print(ht.T.to_string())
    ins = instruments(D, X, d)
    ins.to_parquet(CACHE / "six_plus_instruments.parquet")
    print(ins[ins["season"] == "all"].pivot_table(index="bet", columns="matches played",
                                                   values=["hit %", "return per 100"]).round(1).to_string())
    corr, both, luck, det = teams(D)
    print(f"team 6+ surplus season-to-season correlation {corr:.3f}; teams above odds (z>=1.5) in A and B: {both}; "
          f"shuffled: mean {np.mean(luck):.1f} max {max(luck)}")
    det.to_parquet(CACHE / "six_plus_teams.parquet")
    print(det.to_string())
