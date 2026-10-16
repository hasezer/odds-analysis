"""Do some teams (or leagues) keep beating Nesine's price on a bet, season after season?

For every team (all its matches, home only, away only) or league, and every priced bet type:
  z_p = (hits - Nesine's fair chance summed) / sqrt(sum f(1-f))   in period p (A, B, C)
Persistence test: across all team x bet pairs with enough matches, is z_A correlated with z_B? (no skill = 0)
A pair is listed when z_A >= 2 and z_B >= 2 (it beat the price in both periods); C is the exam.
Luck control: the same count after shuffling which team each B result belongs to (within the bet type).
Writes cache/rules_v3_teams.parquet and cache/rules_v3_teams_summary.parquet.
"""
from pathlib import Path
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import load  # noqa: E402
import miner_data as mdat  # noqa: E402
from dashboard import leagues  # noqa: E402
from htft_data import CACHE  # noqa: E402
from rule_miner import nice  # noqa: E402

MIN_N = {"team (all matches)": 25, "team at home": 12, "team away": 12, "league": 25}


def run():
    z = mdat.build()
    O, F, Hm, per, names, ids = z["O"], z["F"], z["Hm"], z["per"], list(z["names"]), z["match_ids"]
    m = load.matches().set_index("match_id").reindex(ids)
    tn = load.flat()[["home_team_id", "home_team_tr"]].drop_duplicates("home_team_id").set_index("home_team_id")
    tname = tn["home_team_tr"].to_dict()
    lg = leagues()
    groups = {
        "team (all matches)": [("home", m["home_team_id"].to_numpy()), ("away", m["away_team_id"].to_numpy())],
        "team at home": [("home", m["home_team_id"].to_numpy())],
        "team away": [("away", m["away_team_id"].to_numpy())],
        "league": [("", z["league"])],
    }
    rows, summ = [], []
    rng = np.random.default_rng(1)
    for i, lab in enumerate(names):
        y, f, o = Hm[:, i], F[:, i], O[:, i]
        ok = ~np.isnan(y) & ~np.isnan(f) & ~np.isnan(o)
        if ok.sum() < 3000:
            continue
        for gname, parts in groups.items():
            frames = []
            for _, who in parts:
                frames.append(pd.DataFrame({"who": who[ok], "per": per[ok], "y": y[ok], "f": f[ok],
                                            "ret": y[ok] * o[ok] - 1}))
            d = pd.concat(frames)
            d["r"], d["s"] = d["y"] - d["f"], d["f"] * (1 - d["f"])
            g = d.groupby(["who", "per"]).agg(n=("y", "size"), hits=("y", "sum"), price=("f", "sum"), r=("r", "sum"),
                                               s=("s", "sum"), ret=("ret", "sum")).unstack("per")
            if not {"A", "B"} <= set(g.columns.get_level_values(1)):
                continue
            zz = {p: g[("r", p)] / np.sqrt(g[("s", p)]) for p in "ABC" if ("r", p) in g.columns}
            enough = (g[("n", "A")] >= MIN_N[gname]) & (g[("n", "B")] >= MIN_N[gname])
            zA, zB = zz["A"][enough], zz["B"][enough]
            corr = np.corrcoef(zA, zB)[0, 1] if enough.sum() > 10 else np.nan
            # luck: shuffle B results across the groups (keep each match's result with its price)
            dB = d[d["per"] == "B"].copy()
            dB["who"] = rng.permutation(dB["who"].to_numpy())
            gB = dB.groupby("who").agg(r=("r", "sum"), s=("s", "sum"), n=("y", "size"))
            zBs = (gB["r"] / np.sqrt(gB["s"])).reindex(zA.index)
            nBs = gB["n"].reindex(zA.index)
            both = (zA >= 2) & (zB >= 2)
            both_luck = int(((zA >= 2) & (zBs >= 2) & (nBs >= MIN_N[gname])).sum())
            summ.append({"bet": nice(lab), "bet_key": lab, "group": gname, "pairs": int(enough.sum()),
                         "corr_A_B": corr, "beat_both": int(both.sum()), "beat_both_by_luck": both_luck})
            for w in zA.index[both]:
                row = {"bet": nice(lab), "bet_key": lab, "group": gname, "who": w,
                       "name": lg.get(w, {}).get("en", w) if gname == "league" else tname.get(w, w)}
                for p in "ABC":
                    if ("n", p) not in g.columns or pd.isna(g.loc[w, ("n", p)]):
                        row.update({f"n_{p}": 0, f"hit_{p}": np.nan, f"price_{p}": np.nan, f"z_{p}": np.nan,
                                    f"ret_{p}": np.nan})
                        continue
                    n = g.loc[w, ("n", p)]
                    row.update({f"n_{p}": int(n), f"hit_{p}": g.loc[w, ("hits", p)] / n * 100,
                                f"price_{p}": g.loc[w, ("price", p)] / n * 100, f"z_{p}": zz[p][w],
                                f"ret_{p}": g.loc[w, ("ret", p)] / n * 100})
                rows.append(row)
    r, s = pd.DataFrame(rows), pd.DataFrame(summ)
    r.to_parquet(CACHE / "rules_v3_teams.parquet")
    s.to_parquet(CACHE / "rules_v3_teams_summary.parquet")
    return r, s


if __name__ == "__main__":
    r, s = run()
    print(s.groupby("group")[["pairs", "beat_both", "beat_both_by_luck"]].sum().to_string())
    print(s.groupby("group")["corr_A_B"].describe().to_string())
    if len(r):
        r["C_ok"] = r["hit_C"] > r["price_C"]
        print(r.groupby("group")["C_ok"].agg(["size", "mean"]).to_string())
